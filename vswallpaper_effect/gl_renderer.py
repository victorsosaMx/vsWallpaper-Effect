from __future__ import annotations

import os
import time

import gi

gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import GdkPixbuf, GLib, Gtk

from .model import AppConfig
from .utils import darken_hex, hex_to_rgb
from .wallpaper import WallpaperManager

try:
    import OpenGL.GL as gl
except ImportError:
    gl = None

# Cairo + Pango for building the matrix glyph atlas at startup.
try:
    import cairo as _cairo
    gi.require_version("Pango", "1.0")
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import Pango as _Pango
    from gi.repository import PangoCairo as _PangoCairo
    _HAS_PANGO = True

    # Dynamically load the custom Matrix font
    import ctypes
    fontconfig = ctypes.CDLL("libfontconfig.so.1")
    fontconfig.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    font_path = os.path.join(os.path.dirname(__file__), "font", "matrix code nfi.ttf")
    if os.path.exists(font_path):
        fontconfig.FcConfigAppFontAddFile(None, font_path.encode('utf-8'))
except Exception as e:
    print("vsWallpaper-Effect: Matrix font load exception:", e)
    _HAS_PANGO = False

MATRIX_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_ATLAS_CELL = 20   # px per glyph cell (slightly larger for clarity)
_ATLAS_COLS = 8


def _build_glyph_atlas():
    """Render MATRIX_CHARS onto a Cairo surface; return alpha bytes + dimensions.

    Returns (alpha_bytes, width, height, n_cols, n_rows) or None if Pango
    is not available.  The alpha channel encodes glyph coverage (white glyph
    on transparent background).
    """
    if not _HAS_PANGO:
        return None
    num = len(MATRIX_CHARS)
    n_rows = (num + _ATLAS_COLS - 1) // _ATLAS_COLS
    W = _ATLAS_COLS * _ATLAS_CELL
    H = n_rows * _ATLAS_CELL
    surface = _cairo.ImageSurface(_cairo.FORMAT_ARGB32, W, H)
    cr = _cairo.Context(surface)
    cr.set_source_rgba(0.0, 0.0, 0.0, 0.0)
    cr.paint()
    cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
    layout = _PangoCairo.create_layout(cr)
    layout.set_font_description(_Pango.FontDescription("Sans 16"))
    for i, char in enumerate(MATRIX_CHARS):
        col = i % _ATLAS_COLS
        row = i // _ATLAS_COLS
        cr.move_to(col * _ATLAS_CELL, row * _ATLAS_CELL)
        layout.set_text(char, -1)
        _PangoCairo.show_layout(cr, layout)
    surface.flush()
    return bytes(surface.get_data()), W, H, _ATLAS_COLS, n_rows


VERTEX_SHADER = """#version 130
in vec2 position;
in vec2 texcoord;
out vec2 v_texcoord;
void main() {
    gl_Position = vec4(position, 0.0, 1.0);
    v_texcoord = texcoord;
}
"""

# Common declarations shared by all fragment shaders.
_FRAG_COMMON = """#version 130
precision mediump float;
in vec2 v_texcoord;
out vec4 frag_color;
uniform float u_time;
uniform vec2  u_resolution;
uniform vec3  u_accent;
uniform float u_density;
uniform float u_speed;
uniform float u_opacity;
uniform int   u_has_wallpaper;
uniform sampler2D u_wallpaper_tex;
uniform vec2  u_wallpaper_size;

// Cover-fill: scale texture to fill the screen, centered.
vec3 sample_wallpaper(vec2 uv) {
    float sx = u_resolution.x / u_wallpaper_size.x;
    float sy = u_resolution.y / u_wallpaper_size.y;
    float s  = max(sx, sy);
    vec2 tc;
    tc.x = (uv.x - 0.5) * (u_resolution.x / (u_wallpaper_size.x * s)) + 0.5;
    tc.y = 1.0 - ((uv.y - 0.5) * (u_resolution.y / (u_wallpaper_size.y * s)) + 0.5);
    return texture(u_wallpaper_tex, tc).rgb;
}
"""

# ---------------------------------------------------------------------------
# Rain — faithful port of vsFetch Cairo rain
#   Drops fall at 15° from vertical, random length 10–45 px, alpha 0.3–1.0,
#   speed 4–10 px/tick.  Tick rate in vsFetch: 16 ms ≈ 62.5 fps.
#   Uses rotated "rain-space" coordinates so the check is a simple 1-D
#   interval test rather than a distance-to-segment calculation.
# ---------------------------------------------------------------------------
FRAGMENT_SHADER_RAIN = _FRAG_COMMON + """
// Simple 1-D hash (no vec2 overhead needed for column indexing)
float h1(float n) { return fract(sin(n * 127.1 + 311.7) * 43758.5453); }

void main() {
    vec2 uv = v_texcoord;
    vec2 px = uv * u_resolution;

    vec3 color = (u_has_wallpaper == 1) ? sample_wallpaper(uv) : vec3(0.02, 0.05, 0.08);

    // 15-degree angle (matches vsFetch ANGLE = math.radians(15))
    const float SIN_A = 0.25882;   // sin(15°)
    const float COS_A = 0.96593;   // cos(15°)

    // Rain-space axes:
    //   rs_u: perpendicular to drop direction  (identifies column)
    //   rs_v: along drop direction             (tracks position in drop)
    float rs_u = px.x * (-COS_A) + px.y * SIN_A;
    float rs_v = px.x *   SIN_A  + px.y * COS_A;

    // Column width = screen width / number-of-drops
    // density=100 → ~50 drops at default (matches vsFetch default AN["drops"]=100)
    float col_w = u_resolution.x / max(u_density * 0.5, 1.0);

    // Rain-space diagonal (total path before wrapping)
    float diag = u_resolution.x * SIN_A + u_resolution.y * COS_A;

    float rain_a = 0.0;

    // Check the column the pixel falls in and the adjacent one
    // (a pixel can be on a drop from either side when near a column boundary)
    float base_col = floor(rs_u / col_w);
    for (int ci = 0; ci <= 1; ci++) {
        float col_idx = base_col + float(ci);
        float col_ctr = (col_idx + 0.5) * col_w;

        // Cairo line-width is 1.2 px → half-width ≈ 0.6
        if (abs(rs_u - col_ctr) > 0.65) continue;

        // Per-drop properties, deterministic from column index
        float h0 = h1(col_idx * 1.0);
        float h1_ = h1(col_idx * 2.3 + 1.7);
        float h2 = h1(col_idx * 3.7 + 5.3);

        float drop_len = mix(10.0, 45.0, h1_);               // vsFetch: 10–45
        float speed    = mix(4.0, 10.0, h0) * u_speed * 62.5; // px/sec at 62.5 fps
        float alpha    = mix(0.3, 1.0, h2);                   // vsFetch: 0.3–1.0

        float range  = diag + drop_len + 150.0;
        // v_head is the leading edge of the drop in rain-space
        float v_head = mod(rs_v + h0 * range + u_time * speed, range) - drop_len;

        if (rs_v >= v_head - drop_len && rs_v <= v_head) {
            // Fade: tail dim → head bright (linear, matching Cairo alpha behaviour)
            float t = (rs_v - (v_head - drop_len)) / drop_len;  // 0=tail 1=head
            rain_a = max(rain_a, alpha * (0.15 + 0.85 * t));
        }
    }

    if (rain_a > 0.0) {
        color = mix(color, u_accent, rain_a * u_opacity);
    }

    // Subtle fog at top: matches "config.fog" glow in the Cairo version
    float fog = exp(-uv.y * 3.5) * 0.12 * u_opacity;
    color = mix(color, u_accent, fog);

    frag_color = vec4(color, 1.0);
}
"""

# ---------------------------------------------------------------------------
# Matrix — column-based cell grid, closest achievable to vsFetch without a
#   font texture.  Head cell is white; trail fades as (1-i/trail)^1.5 in
#   the accent colour — exact formula from vsFetch draw_matrix().
#   Character "mutation" is simulated with a time-stepped hash (≈12 fps).
# ---------------------------------------------------------------------------
FRAGMENT_SHADER_MATRIX = _FRAG_COMMON + """
// Glyph texture atlas (one character per cell, rendered by Cairo/Pango at startup).
uniform sampler2D u_glyph_atlas;
uniform float     u_atlas_cols;
uniform float     u_atlas_rows;
uniform float     u_num_chars;

float hash12(vec2 p) {
    vec3 q = fract(vec3(p.xyx) * 0.1031);
    q += dot(q, q.yzx + 33.33);
    return fract((q.x + q.y) * q.z);
}

void main() {
    vec2 uv = v_texcoord;
    vec2 px = uv * u_resolution;
    float H  = u_resolution.y;

    vec3 color = (u_has_wallpaper == 1) ? sample_wallpaper(uv) : vec3(0.02, 0.05, 0.08);

    // Cell size matches _ATLAS_CELL in Python.
    const float CW = 20.0;
    const float CH = 20.0;

    // Flip y so row 0 is at the top — characters fall downward.
    float col_idx = floor(px.x / CW);
    float row_idx = floor((H - px.y) / CH);
    vec2  cell_uv = fract(vec2(px.x, H - px.y) / vec2(CW, CH));

    // Per-column properties
    float h0 = hash12(vec2(col_idx, 0.0));
    float h1 = hash12(vec2(col_idx, 1.0));
    float h2 = hash12(vec2(col_idx, 2.0));

    float speed     = mix(2.0, 7.0, h0) * u_speed * 62.5 / CH;
    float trail_len = floor(mix(8.0, 22.0, h1));
    float num_rows  = H / CH;
    float range     = num_rows + trail_len;

    // Animated head row — increases with time → head moves downward.
    float head_row = mod(u_time * speed + h2 * range, range) - trail_len;
    float dist     = head_row - row_idx;   // 0 = head, positive = in trail

    if (dist >= 0.0 && dist < trail_len) {
        float t = dist / trail_len;

        float trail_alpha;
        vec3  char_color;
        if (dist < 1.0) {
            trail_alpha = 1.0;
            char_color  = vec3(1.0);        // head: white
        } else {
            trail_alpha = pow(1.0 - t, 1.5);
            char_color  = u_accent;
        }

        // Pick character — mutates at ~12 fps.
        float time_step = floor(u_time * 12.0);
        float char_idx  = floor(hash12(vec2(col_idx * 17.3 + row_idx, time_step)) * u_num_chars);
        float ac = mod(char_idx, u_atlas_cols);
        float ar = floor(char_idx / u_atlas_cols);
        vec2  atlas_uv = (vec2(ac, ar) + cell_uv) / vec2(u_atlas_cols, u_atlas_rows);
        float glyph_a  = texture(u_glyph_atlas, atlas_uv).a;

        if (glyph_a > 0.05) {
            float a = trail_alpha * u_opacity * glyph_a;
            color = mix(color, char_color, clamp(a, 0.0, 1.0));
        }
    }

    frag_color = vec4(color, 1.0);
}
"""

# ---------------------------------------------------------------------------
# Aurora — faithful port of vsFetch Cairo aurora
#   3 sine-wave bands filled downward with a linear gradient.
#   Parameters identical to vsFetch: y_frac 0.50/0.63/0.76, amp 50/60/45,
#   freq 0.007/0.005/0.009, phase-rates match spd*62.5.
#   Colors: accent / hue+120° / hue-120°  (maps to vsFetch accent/hi/ok).
# ---------------------------------------------------------------------------
FRAGMENT_SHADER_AURORA = _FRAG_COMMON + """
uniform float u_vertical_pos;  // 0.0=top  1.0=bottom
uniform vec3  u_color2;        // second aurora band color
uniform vec3  u_color3;        // third aurora band color

void main() {
    vec2 uv = v_texcoord;
    vec2 px = uv * u_resolution;
    float W  = u_resolution.x;
    float H  = u_resolution.y;

    vec3 color = (u_has_wallpaper == 1) ? sample_wallpaper(uv) : vec3(0.02, 0.05, 0.08);

    float h_scale = H / 680.0;
    float w_scale = 700.0 / W;

    vec3 c0 = u_accent;
    vec3 c1 = u_color2;
    vec3 c2 = u_color3;

    // Bands distributed ±0.13*H around the vertical_pos center
    float yc = (1.0 - u_vertical_pos) * H;
    float y0 = yc - 0.13 * H;
    float y1 = yc;
    float y2 = yc + 0.13 * H;

    float amp0  = 50.0 * h_scale;
    float ph0   = 0.0 + u_time * 0.012 * 62.5 * u_speed;
    float wy0   = y0 + amp0 * sin(px.x * 0.007 * w_scale + ph0);
    if (px.y >= wy0) {
        float gt = clamp((px.y - (y0 - 2.0*amp0)) / (4.0*amp0), 0.0, 1.0);
        float a  = (gt < 0.4) ? (0.55 * gt / 0.4) : (0.55 * (1.0 - (gt-0.4)/0.6));
        color = mix(color, c0, clamp(a * u_opacity / 0.55, 0.0, 1.0));
    }

    float amp1  = 60.0 * h_scale;
    float ph1   = 2.1 + u_time * 0.009 * 62.5 * u_speed;
    float wy1   = y1 + amp1 * sin(px.x * 0.005 * w_scale + ph1);
    if (px.y >= wy1) {
        float gt = clamp((px.y - (y1 - 2.0*amp1)) / (4.0*amp1), 0.0, 1.0);
        float a  = (gt < 0.4) ? (0.45 * gt / 0.4) : (0.45 * (1.0 - (gt-0.4)/0.6));
        color = mix(color, c1, clamp(a * u_opacity / 0.55, 0.0, 1.0));
    }

    float amp2  = 45.0 * h_scale;
    float ph2   = 4.2 + u_time * 0.015 * 62.5 * u_speed;
    float wy2   = y2 + amp2 * sin(px.x * 0.009 * w_scale + ph2);
    if (px.y >= wy2) {
        float gt = clamp((px.y - (y2 - 2.0*amp2)) / (4.0*amp2), 0.0, 1.0);
        float a  = (gt < 0.4) ? (0.40 * gt / 0.4) : (0.40 * (1.0 - (gt-0.4)/0.6));
        color = mix(color, c2, clamp(a * u_opacity / 0.55, 0.0, 1.0));
    }

    frag_color = vec4(color, 1.0);
}
"""

# ---------------------------------------------------------------------------
# Warp — faithful port of vsFetch Cairo warp starfield
#   Stars radiate from the screen centre with exponential acceleration:
#     dist += speed * (1 + dist / (max_r * 0.4))  per 16-ms tick
#   Trail length grows with distance: max(2, dist * 0.15).
#   Line width grows: 0.5 + (dist/max_r) * 1.5 px.
#   Alpha fades in from centre: min(1, dist / (max_r * 0.3)).
#   Analytical inverse of the recurrence to reconstruct position at u_time.
# ---------------------------------------------------------------------------
FRAGMENT_SHADER_WARP = _FRAG_COMMON + """
float hash12(vec2 p) {
    vec3 q = fract(vec3(p.xyx) * 0.1031);
    q += dot(q, q.yzx + 33.33);
    return fract((q.x + q.y) * q.z);
}

void main() {
    vec2 uv    = v_texcoord;
    vec2 px    = uv * u_resolution;
    vec2 ctr   = u_resolution * 0.5;
    vec2 dp    = px - ctr;

    vec3 color = (u_has_wallpaper == 1) ? sample_wallpaper(uv) : vec3(0.02, 0.05, 0.08);

    float theta = atan(dp.y, dp.x);
    float r     = length(dp);
    float max_r = length(ctr) * 1.2;

    // Stars are evenly spaced in angle (density ≈ number of stars)
    float num_stars = max(u_density * 0.4, 20.0);
    const float PI  = 3.14159265;
    float lane_w    = (2.0 * PI) / num_stars;

    // Exponential recurrence solution:
    //   dist(t) = A * (exp(speed * t / A) - 1),   A = max_r * 0.4
    //   Period T = A / speed * ln(3.5)  (when dist reaches max_r)
    float A = max_r * 0.4;
    const float LN35 = 1.25276;  // ln(3.5)

    float warp_a   = 0.0;
    float base_idx = floor((theta + PI) / lane_w);

    // Check the star lane the pixel is in, plus two neighbours
    for (int li = -1; li <= 1; li++) {
        float lane_idx   = base_idx + float(li);
        float lane_theta = (lane_idx + 0.5) * lane_w - PI;

        float h0 = hash12(vec2(lane_idx, 0.0));
        float h1 = hash12(vec2(lane_idx, 1.0));

        // vsFetch: speed 1–3 * speed_mult per tick; ticks at 62.5 fps
        float spd   = mix(1.0, 3.0, h0) * u_speed * 62.5;  // px/sec
        float alpha = mix(0.4, 1.0, h1);

        float T     = A * LN35 / spd;                       // period in seconds
        float t_now = mod(u_time + h0 * T, T);
        float dist  = A * (exp(t_now * spd / A) - 1.0);
        dist = min(dist, max_r);

        if (dist < 1.0) continue;

        float trail_len = max(2.0, dist * 0.15);  // vsFetch formula

        if (r >= dist - trail_len && r <= dist + 2.0) {
            // vsFetch: alpha * min(1, dist / (max_r * 0.3))
            float r_alpha  = min(1.0, dist / (max_r * 0.3));
            float trail_t  = clamp((r - (dist - trail_len)) / trail_len, 0.0, 1.0);

            // vsFetch: line_width = 0.5 + (dist/max_dist) * 1.5
            float line_w   = 0.5 + (dist / max_r) * 1.5;
            float ang_px   = abs(sin(theta - lane_theta)) * max(r, 1.0);

            if (ang_px < line_w) {
                float a = alpha * r_alpha * trail_t;
                warp_a = max(warp_a, a);
            }
        }
    }

    if (warp_a > 0.0) {
        color = mix(color, u_accent, warp_a * u_opacity);
    }

    frag_color = vec4(color, 1.0);
}
"""

# ---------------------------------------------------------------------------
# Snow — grid of circular flakes falling with sine drift
#   Each grid cell owns one flake; 3×3 neighbor check per pixel.
#   Falls from top (GL y=H) to bottom (GL y=0), wraps vertically.
# ---------------------------------------------------------------------------
FRAGMENT_SHADER_SNOW = _FRAG_COMMON + """
float hash11(float p) {
    p = fract(p * 0.1031);
    p *= p + 33.33;
    p *= p + p;
    return fract(p);
}

void main() {
    vec2 uv = v_texcoord;
    vec2 px = uv * u_resolution;
    float W = u_resolution.x;
    float H = u_resolution.y;

    vec3 color = (u_has_wallpaper == 1) ? sample_wallpaper(uv) : vec3(0.02, 0.05, 0.08);

    float cols     = floor(4.0 + u_density * 0.10);
    float rows     = floor(cols * H / W * 1.8);
    float cell_w   = W / cols;
    float cell_h   = H / rows;

    float snow_acc = 0.0;
    vec2 cell_idx  = floor(vec2(px.x / cell_w, px.y / cell_h));

    for (int dy = -1; dy <= 1; dy++) {
        for (int dx = -1; dx <= 1; dx++) {
            vec2  nc    = cell_idx + vec2(float(dx), float(dy));
            float nc_x  = mod(nc.x + cols, cols);
            float nc_y  = nc.y;
            float idx   = nc_x * 7919.0 + nc_y * 3571.0;

            float speed      = 0.25 + hash11(idx * 1.23) * 0.75;
            float size       = 1.5  + hash11(idx * 2.34) * 4.0;
            float phase      = hash11(idx * 3.45) * 6.2832;
            float drift      = cell_w * (0.2 + hash11(idx * 4.56) * 0.35);
            float drift_spd  = 0.3  + hash11(idx * 5.67) * 0.7;
            float y_start    = hash11(idx * 6.78) * H;
            float alpha_base = 0.4  + hash11(idx * 7.89) * 0.55;

            float fall = mod(y_start + u_time * speed * u_speed * 55.0, H);
            float fy   = H - fall;
            float fx   = (nc_x + 0.5) * cell_w + drift * sin(u_time * drift_spd * u_speed + phase);

            float dist  = length(px - vec2(fx, fy));
            float flake = smoothstep(size, size * 0.1, dist) * alpha_base;
            snow_acc = max(snow_acc, flake);
        }
    }

    // Ice-white tinted with accent
    vec3 snow_col = mix(vec3(0.88, 0.93, 1.0), u_accent, 0.12);
    color = mix(color, snow_col, snow_acc * u_opacity);
    frag_color = vec4(color, 1.0);
}
"""

# ---------------------------------------------------------------------------
# Gradient — animated mesh-gradient: 2-4 soft color blobs drifting in
#   independent Lissajous paths.  u_vertical_pos controls blob radius
#   (coverage): 0=tight (50% of screen), 1=full-screen blobs.
#   u_color2 / u_color3 are the second and third blob colors.
# ---------------------------------------------------------------------------
FRAGMENT_SHADER_GRADIENT = _FRAG_COMMON + """
uniform vec3  u_color2;
uniform vec3  u_color3;
uniform float u_vertical_pos;   // blob coverage 0=tight  1=full-screen

void main() {
    vec2 uv = v_texcoord;
    vec2 px  = uv * u_resolution;
    float W  = u_resolution.x;
    float H  = u_resolution.y;

    // Background: darkest color, or wallpaper when one is loaded.
    vec3 color = (u_has_wallpaper == 1) ? sample_wallpaper(uv) : u_color3;

    float t = u_time * u_speed * 0.3;

    // Blob coverage radius in pixels (matching Python: 0.50..1.00 * max(W,H))
    float R = (0.50 + u_vertical_pos * 0.50) * max(W, H);

    // Blob centres follow independent Lissajous figures (phases match _BLOB_PARAMS)
    vec2 b1 = vec2(0.5 + 0.35*sin(t*0.23),         0.5 + 0.35*cos(t*0.17))        * u_resolution;
    vec2 b2 = vec2(0.5 + 0.35*sin(t*0.19 + 2.09),  0.5 + 0.35*cos(t*0.28 + 3.72))* u_resolution;
    vec2 b3 = vec2(0.5 + 0.35*sin(t*0.31 + 5.24),  0.5 + 0.35*cos(t*0.21 + 1.38))* u_resolution;

    // Quadratic falloff: soft edge matching RadialGradient stop at 0.6
    float a1 = max(0.0, 1.0 - length(px - b1) / R);          a1 *= a1;
    float a2 = max(0.0, 1.0 - length(px - b2) / (R * 0.85)); a2 *= a2;
    float a3 = max(0.0, 1.0 - length(px - b3) / (R * 0.70)); a3 *= a3;

    color = mix(color, u_accent, clamp(a1 * 0.90 * u_opacity, 0.0, 1.0));
    color = mix(color, u_color2, clamp(a2 * 0.75 * u_opacity, 0.0, 1.0));
    color = mix(color, u_accent, clamp(a3 * 0.45 * u_opacity, 0.0, 1.0));

    // Extra blob at density >= 70 (Python n_blobs >= 3)
    if (u_density >= 70.0) {
        vec2 b4 = vec2(0.5 + 0.35*sin(t*0.14 + 1.11), 0.5 + 0.35*cos(t*0.36 + 4.90)) * u_resolution;
        float a4 = max(0.0, 1.0 - length(px - b4) / (R * 0.60)); a4 *= a4;
        color = mix(color, u_color3, clamp(a4 * 0.35 * u_opacity, 0.0, 1.0));
    }

    frag_color = vec4(color, 1.0);
}
"""

# ---------------------------------------------------------------------------
# Stars — three-layer parallax starfield with hash-based placement.
#   Layer 0 (far): many tiny dim static dots.
#   Layer 1 (mid): moderate size and brightness.
#   Layer 2 (near): fewer, larger, twinkle via sin(time).
#   u_density scales grid cell count (more cells = more stars).
# ---------------------------------------------------------------------------
FRAGMENT_SHADER_STARS = _FRAG_COMMON + """
float hash12(vec2 p) {
    vec3 q = fract(vec3(p.xyx) * 0.1031);
    q += dot(q, q.yzx + 33.33);
    return fract((q.x + q.y) * q.z);
}

// One parallax layer: hash-grid of circular stars, 3x3 neighbour check.
float star_layer(vec2 px, float W, float H,
                 float n_cols, float size_px, float alpha_max,
                 float twinkle_spd, float seed) {
    float n_rows = n_cols * H / W;
    float cw = W / n_cols;
    float ch = H / n_rows;
    vec2 cell = floor(px / vec2(cw, ch));
    float acc = 0.0;
    for (int dy = -1; dy <= 1; dy++) {
        for (int dx = -1; dx <= 1; dx++) {
            vec2  nc  = cell + vec2(float(dx), float(dy));
            float nx  = mod(nc.x, n_cols);
            float ny  = mod(nc.y, n_rows);
            float idx = nx * 7919.0 + ny * 3571.0 + seed;
            float sx  = (nx + 0.15 + 0.70 * hash12(vec2(idx, 1.1))) * cw;
            float sy  = (ny + 0.15 + 0.70 * hash12(vec2(idx, 2.2))) * ch;
            float sz  = size_px * (0.5 + 0.8 * hash12(vec2(idx, 3.3)));
            float ba  = alpha_max * (0.3 + 0.7 * hash12(vec2(idx, 4.4)));
            if (twinkle_spd > 0.0) {
                float ph = hash12(vec2(idx, 5.5)) * 6.2832;
                ba *= 0.5 + 0.5 * sin(u_time * twinkle_spd + ph);
            }
            acc = max(acc, smoothstep(sz, sz * 0.1, length(px - vec2(sx, sy))) * ba);
        }
    }
    return acc;
}

void main() {
    vec2 uv = v_texcoord;
    vec2 px  = uv * u_resolution;
    float W  = u_resolution.x;
    float H  = u_resolution.y;

    vec3 color = (u_has_wallpaper == 1) ? sample_wallpaper(uv) : vec3(0.02, 0.05, 0.08);

    float base_cols = max(6.0, u_density * 0.12 + 4.0);

    float a0 = star_layer(px, W, H, base_cols * 3.5, 1.1, 0.30, 0.0,             0.0);
    float a1 = star_layer(px, W, H, base_cols * 2.0, 2.0, 0.58, 0.0,           999.0);
    float a2 = star_layer(px, W, H, base_cols * 1.0, 3.2, 0.95, 2.0 * u_speed, 1999.0);

    color = mix(color, u_accent, max(max(a0, a1), a2) * u_opacity);
    frag_color = vec4(color, 1.0);
}
"""

# ---------------------------------------------------------------------------
# Waves — multi-layer horizontal sine waves scrolling rightward.
#   3 layers: i=0 back (slow, dark, lower amp), i=2 front (fast, bright).
#   u_vertical_pos = water level (0=top  1=bottom).
#   Pixel below the wave surface gets a gradient fill fading with depth.
# ---------------------------------------------------------------------------
FRAGMENT_SHADER_WAVES = _FRAG_COMMON + """
uniform float u_vertical_pos;   // water level: 0=top  1=bottom
uniform vec3  u_color2;
uniform vec3  u_color3;

void main() {
    vec2 uv = v_texcoord;
    vec2 px  = uv * u_resolution;
    float W  = u_resolution.x;
    float H  = u_resolution.y;

    vec3 color = (u_has_wallpaper == 1) ? sample_wallpaper(uv) : vec3(0.02, 0.05, 0.08);

    // GL uv.y = 0 at bottom, 1 at top; u_vertical_pos 0=top → v_water=1
    float v_water    = 1.0 - u_vertical_pos;
    float freq_scale = 0.5 + u_density / 80.0;

    vec3 layer_colors[3];
    layer_colors[0] = u_color3;  // back
    layer_colors[1] = u_color2;  // mid
    layer_colors[2] = u_accent;  // front

    for (int i = 0; i < 3; i++) {
        float depth  = float(i) / 2.0;          // 0=back  1=front
        float front  = 1.0 - depth;

        float spd    = (0.3 + front * 0.7) * u_speed;
        float amp    = 0.025 + front * 0.055;   // UV fraction of H
        float fr1    = freq_scale * (2.8 + depth * 1.4) * 3.14159265 / W;
        float fr2    = freq_scale * (1.5 + depth * 0.8) * 3.14159265 / W;
        float ph1    = float(i) * 1.31 + u_time * spd * 2.81;   // 0.045*62.5
        float ph2    = float(i) * 2.71 + u_time * spd * 1.75;   // 0.028*62.5
        float y_off  = depth * 0.045;                            // back layers lower
        float l_alpha = 0.50 + front * 0.35;

        float v_base = v_water - y_off;
        float v_surf = v_base - (amp * sin(px.x * fr1 + ph1) + amp * 0.4 * sin(px.x * fr2 + ph2));

        if (uv.y < v_surf) {
            float below = v_surf - uv.y;
            float t     = clamp(below / (amp * 4.0), 0.0, 1.0);
            float a     = mix(l_alpha * 0.85, l_alpha * 0.08, t) * u_opacity;
            color       = mix(color, layer_colors[i], clamp(a, 0.0, 1.0));
        }
    }

    frag_color = vec4(color, 1.0);
}
"""

# ---------------------------------------------------------------------------
# Droplets — circular ripples spawning at random grid points on a cycle.
#   Each grid cell emits one impact every `period` seconds; each impact
#   spawns 3 concentric rings that expand and fade.
#   u_density controls grid resolution (cell count).  u_speed scales both
#   expansion speed and spawn rate.
# ---------------------------------------------------------------------------
FRAGMENT_SHADER_DROPLETS = _FRAG_COMMON + """
float hash12(vec2 p) {
    vec3 q = fract(vec3(p.xyx) * 0.1031);
    q += dot(q, q.yzx + 33.33);
    return fract((q.x + q.y) * q.z);
}

void main() {
    vec2 uv = v_texcoord;
    vec2 px  = uv * u_resolution;
    float W  = u_resolution.x;
    float H  = u_resolution.y;

    vec3 color = (u_has_wallpaper == 1) ? sample_wallpaper(uv) : vec3(0.02, 0.05, 0.08);

    float cell_size = W / max(4.0, u_density * 0.08);
    float n_cols    = ceil(W / cell_size);
    float n_rows    = ceil(H / cell_size);

    float period = 3.0 / max(0.1, u_speed);
    float expand = max(W, H) * 0.22 * u_speed;   // px / sec

    float ring_acc = 0.0;
    vec2  cell     = floor(px / cell_size);

    for (int dy = -2; dy <= 2; dy++) {
        for (int dx = -2; dx <= 2; dx++) {
            vec2  nc  = cell + vec2(float(dx), float(dy));
            float nx  = mod(nc.x, n_cols);
            float ny  = mod(nc.y, n_rows);
            float idx = nx * 7919.0 + ny * 3571.0;

            float ix  = (nx + 0.05 + 0.90 * hash12(vec2(idx, 1.0))) * cell_size;
            float iy  = (ny + 0.05 + 0.90 * hash12(vec2(idx, 2.0))) * cell_size;

            float t_off = hash12(vec2(idx, 3.0)) * period;
            float age   = mod(u_time - t_off, period);

            for (int ring = 0; ring < 3; ring++) {
                float delay    = float(ring) * 0.18;
                float ring_age = age - delay;
                if (ring_age <= 0.0 || ring_age >= period * 0.85) continue;

                float radius = expand * ring_age;
                float fade   = 1.0 - ring_age / (period * 0.85);
                float lw     = mix(1.8, 0.9, float(ring) / 2.0);

                float d = abs(length(px - vec2(ix, iy)) - radius);
                ring_acc = max(ring_acc, smoothstep(lw * 2.0, 0.0, d) * fade * 0.85);
            }
        }
    }

    color = mix(color, u_accent, ring_acc * u_opacity);
    frag_color = vec4(color, 1.0);
}
"""

SHADERS = {
    "rain":     FRAGMENT_SHADER_RAIN,
    "matrix":   FRAGMENT_SHADER_MATRIX,
    "aurora":   FRAGMENT_SHADER_AURORA,
    "warp":     FRAGMENT_SHADER_WARP,
    "snow":     FRAGMENT_SHADER_SNOW,
    "gradient": FRAGMENT_SHADER_GRADIENT,
    "stars":    FRAGMENT_SHADER_STARS,
    "waves":    FRAGMENT_SHADER_WAVES,
    "droplets": FRAGMENT_SHADER_DROPLETS,
}

_UNIFORM_NAMES = (
    "u_time", "u_resolution", "u_accent",
    "u_density", "u_speed", "u_opacity",
    "u_has_wallpaper", "u_wallpaper_tex", "u_wallpaper_size",
    "u_vertical_pos", "u_color2", "u_color3",
)
_MATRIX_EXTRA_UNIFORMS = ("u_glyph_atlas", "u_atlas_cols", "u_atlas_rows", "u_num_chars")


def _aurora_colors(cfg: AppConfig) -> tuple[tuple, tuple, tuple]:
    c1_hex = cfg.effect.color or cfg.theme_accent
    c2_hex = cfg.effect.color2 or darken_hex(c1_hex, 0.40)
    c3_hex = cfg.effect.color3 or darken_hex(c1_hex, 0.72)
    return hex_to_rgb(c1_hex), hex_to_rgb(c2_hex), hex_to_rgb(c3_hex)


class GLRenderer:
    def __init__(self) -> None:
        self._program: int = 0
        self._vbo: int = 0
        self._vao: int = 0
        self._texture: int = 0
        self._atlas_texture: int = 0
        self._atlas_ready: bool = False
        self._wallpaper_path: str = ""
        self._wallpaper_size: tuple[float, float] = (1.0, 1.0)
        self._start_time: float = time.monotonic()
        self._effect: str = "rain"
        self._needs_recompile: bool = False
        self._accent: list[float] = [0.5, 0.78, 0.88]
        self._color2: list[float] = [0.35, 0.55, 0.62]
        self._color3: list[float] = [0.18, 0.28, 0.32]
        self._density: float = 100.0
        self._speed: float = 1.0
        self._opacity: float = 0.55
        self._enabled: bool = True
        self._vertical_pos: float = 0.7
        self._has_wallpaper: bool = False
        self._uniforms: dict[str, int] = {}
        self._has_u_vertical_pos: bool = False
        self._has_u_color2: bool = False
        self._has_u_color3: bool = False
        self._pos_loc: int = -1
        self._tex_loc: int = -1
        self._gl = None

    @property
    def current_wallpaper_path(self) -> str:
        return self._wallpaper_path

    def initialize(self) -> bool:
        if gl is None:
            return False
        self._gl = gl
        self._texture = gl.glGenTextures(1)
        self._compile_shaders()
        self._setup_geometry()
        return bool(self._program)

    def _compile_shaders(self) -> None:
        g = self._gl
        vs = g.glCreateShader(g.GL_VERTEX_SHADER)
        g.glShaderSource(vs, VERTEX_SHADER)
        g.glCompileShader(vs)
        if g.glGetShaderiv(vs, g.GL_COMPILE_STATUS) != g.GL_TRUE:
            print("vsWallpaper-Effect GL VS error:", g.glGetShaderInfoLog(vs))

        fs = g.glCreateShader(g.GL_FRAGMENT_SHADER)
        g.glShaderSource(fs, SHADERS.get(self._effect, SHADERS["rain"]))
        g.glCompileShader(fs)
        if g.glGetShaderiv(fs, g.GL_COMPILE_STATUS) != g.GL_TRUE:
            print("vsWallpaper-Effect GL FS error:", g.glGetShaderInfoLog(fs))

        prog = g.glCreateProgram()
        g.glAttachShader(prog, vs)
        g.glAttachShader(prog, fs)
        g.glLinkProgram(prog)
        g.glDeleteShader(vs)
        g.glDeleteShader(fs)

        if g.glGetProgramiv(prog, g.GL_LINK_STATUS) != g.GL_TRUE:
            print("vsWallpaper-Effect GL link error:", g.glGetProgramInfoLog(prog))
            g.glDeleteProgram(prog)
            return

        if self._program:
            g.glDeleteProgram(self._program)
        self._program = prog

        self._pos_loc = g.glGetAttribLocation(prog, "position")
        self._tex_loc = g.glGetAttribLocation(prog, "texcoord")
        
        # Merge basic and matrix uniforms
        all_uniforms = list(_UNIFORM_NAMES)
        if self._effect == "matrix":
            all_uniforms.extend(_MATRIX_EXTRA_UNIFORMS)
            
        self._uniforms = {name: g.glGetUniformLocation(prog, name) for name in all_uniforms}
        self._has_u_vertical_pos = self._uniforms.get("u_vertical_pos", -1) >= 0
        self._has_u_color2 = self._uniforms.get("u_color2", -1) >= 0
        self._has_u_color3 = self._uniforms.get("u_color3", -1) >= 0

    def _setup_geometry(self) -> None:
        if not self._program:
            return
        g = self._gl
        g.glUseProgram(self._program)

        verts = [
            -1.0, -1.0, 0.0, 0.0,
             1.0, -1.0, 1.0, 0.0,
            -1.0,  1.0, 0.0, 1.0,
             1.0,  1.0, 1.0, 1.0,
        ]
        if not self._vbo:
            self._vbo = g.glGenBuffers(1)
        g.glBindBuffer(g.GL_ARRAY_BUFFER, self._vbo)
        g.glBufferData(g.GL_ARRAY_BUFFER, len(verts) * 4,
                       (g.GLfloat * len(verts))(*verts), g.GL_STATIC_DRAW)

        if not self._vao:
            self._vao = g.glGenVertexArrays(1)
        g.glBindVertexArray(self._vao)

        if self._pos_loc >= 0:
            g.glEnableVertexAttribArray(self._pos_loc)
            g.glVertexAttribPointer(self._pos_loc, 2, g.GL_FLOAT, g.GL_FALSE, 16, g.GLvoidp(0))
        if self._tex_loc >= 0:
            g.glEnableVertexAttribArray(self._tex_loc)
            g.glVertexAttribPointer(self._tex_loc, 2, g.GL_FLOAT, g.GL_FALSE, 16, g.GLvoidp(8))

    def _load_wallpaper_texture(self, path: str) -> None:
        self._wallpaper_path = path
        self._has_wallpaper = False
        if not path or not os.path.isfile(path):
            return
        g = self._gl
        if g is None:
            return
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
            if pixbuf is None:
                return
            width     = pixbuf.get_width()
            height    = pixbuf.get_height()
            has_alpha = pixbuf.get_has_alpha()
            channels  = 4 if has_alpha else 3
            fmt       = g.GL_RGBA if has_alpha else g.GL_RGB
            rowstride = pixbuf.get_rowstride()
            data      = pixbuf.get_pixels()

            g.glBindTexture(g.GL_TEXTURE_2D, self._texture)
            g.glTexParameteri(g.GL_TEXTURE_2D, g.GL_TEXTURE_WRAP_S, g.GL_CLAMP_TO_EDGE)
            g.glTexParameteri(g.GL_TEXTURE_2D, g.GL_TEXTURE_WRAP_T, g.GL_CLAMP_TO_EDGE)
            g.glTexParameteri(g.GL_TEXTURE_2D, g.GL_TEXTURE_MIN_FILTER, g.GL_LINEAR)
            g.glTexParameteri(g.GL_TEXTURE_2D, g.GL_TEXTURE_MAG_FILTER, g.GL_LINEAR)

            tight = (rowstride == width * channels)
            if not tight:
                g.glPixelStorei(g.GL_UNPACK_ROW_LENGTH, rowstride // channels)
            g.glTexImage2D(g.GL_TEXTURE_2D, 0, g.GL_RGBA, width, height,
                           0, fmt, g.GL_UNSIGNED_BYTE, data)
            if not tight:
                g.glPixelStorei(g.GL_UNPACK_ROW_LENGTH, 0)

            self._wallpaper_size = (float(width), float(height))
            self._has_wallpaper  = True
        except Exception as exc:
            print("vsWallpaper-Effect GL texture error:", exc)

    def _load_matrix_atlas(self) -> None:
        if self._atlas_ready or self._effect != "matrix" or not _HAS_PANGO:
            return
        g = self._gl
        if g is None:
            return
        
        atlas_data = _build_glyph_atlas()
        if not atlas_data:
            return
        raw_bytes, w, h, cols, rows = atlas_data

        if not self._atlas_texture:
            self._atlas_texture = g.glGenTextures(1)

        g.glBindTexture(g.GL_TEXTURE_2D, self._atlas_texture)
        g.glTexParameteri(g.GL_TEXTURE_2D, g.GL_TEXTURE_WRAP_S, g.GL_CLAMP_TO_EDGE)
        g.glTexParameteri(g.GL_TEXTURE_2D, g.GL_TEXTURE_WRAP_T, g.GL_CLAMP_TO_EDGE)
        g.glTexParameteri(g.GL_TEXTURE_2D, g.GL_TEXTURE_MIN_FILTER, g.GL_LINEAR)
        g.glTexParameteri(g.GL_TEXTURE_2D, g.GL_TEXTURE_MAG_FILTER, g.GL_LINEAR)
        g.glPixelStorei(g.GL_UNPACK_ALIGNMENT, 4)
        # Cairo ARGB32 is stored as BGRA bytes on little-endian; use GL_BGRA.
        g.glTexImage2D(g.GL_TEXTURE_2D, 0, g.GL_RGBA, w, h,
                       0, g.GL_BGRA, g.GL_UNSIGNED_BYTE, raw_bytes)

        self._atlas_cols = float(cols)
        self._atlas_rows = float(rows)
        self._num_chars = float(len(MATRIX_CHARS))
        self._atlas_ready = True

    def set_config(
        self,
        effect: str,
        accent: tuple,
        density: float,
        speed: float,
        opacity: float,
        enabled: bool,
        vertical_pos: float = 0.7,
        color2: tuple = (0.35, 0.55, 0.62),
        color3: tuple = (0.18, 0.28, 0.32),
    ) -> None:
        """Update parameters. Never calls GL — safe from any GTK callback."""
        self._accent       = list(accent)
        self._color2       = list(color2)
        self._color3       = list(color3)
        self._density      = density
        self._speed        = speed
        self._opacity      = opacity
        self._enabled      = enabled
        self._vertical_pos = vertical_pos
        if effect != self._effect:
            self._effect = effect
            self._needs_recompile = True

    def render(self, width: int, height: int) -> None:
        # Recompile if the effect changed — must run inside the GL context.
        if self._needs_recompile:
            self._needs_recompile = False
            self._compile_shaders()
            self._setup_geometry()
        # Load atlas whenever matrix is active and not yet ready (covers initial load too).
        if self._effect == "matrix" and not self._atlas_ready:
            self._load_matrix_atlas()
        if not self._program:
            return

        g = self._gl
        g.glViewport(0, 0, width, height)
        g.glClearColor(0.02, 0.05, 0.08, 1.0)
        g.glClear(g.GL_COLOR_BUFFER_BIT)
        g.glUseProgram(self._program)

        u       = self._uniforms
        elapsed = time.monotonic() - self._start_time

        g.glUniform1f(u["u_time"],         elapsed)
        g.glUniform2f(u["u_resolution"],   float(width), float(height))
        g.glUniform3f(u["u_accent"],       *self._accent)
        g.glUniform1f(u["u_density"],      self._density)
        g.glUniform1f(u["u_speed"],        self._speed)
        g.glUniform1f(u["u_opacity"],      self._opacity if self._enabled else 0.0)
        g.glUniform1i(u["u_has_wallpaper"], 1 if self._has_wallpaper else 0)
        if self._has_u_vertical_pos:
            g.glUniform1f(u["u_vertical_pos"], self._vertical_pos)
        if self._has_u_color2:
            g.glUniform3f(u["u_color2"], *self._color2)
        if self._has_u_color3:
            g.glUniform3f(u["u_color3"], *self._color3)

        if self._has_wallpaper:
            g.glActiveTexture(g.GL_TEXTURE0)
            g.glBindTexture(g.GL_TEXTURE_2D, self._texture)
            g.glUniform1i(u["u_wallpaper_tex"],  0)
            g.glUniform2f(u["u_wallpaper_size"], *self._wallpaper_size)

        if self._effect == "matrix":
            g.glActiveTexture(g.GL_TEXTURE1)
            if self._atlas_ready:
                g.glBindTexture(g.GL_TEXTURE_2D, self._atlas_texture)
            else:
                g.glBindTexture(g.GL_TEXTURE_2D, 0)
                
            if "u_glyph_atlas" in u and u["u_glyph_atlas"] >= 0:
                g.glUniform1i(u["u_glyph_atlas"], 1)
                g.glUniform1f(u["u_atlas_cols"], self._atlas_cols if self._atlas_ready else 8.0)
                g.glUniform1f(u["u_atlas_rows"], self._atlas_rows if self._atlas_ready else 8.0)
                g.glUniform1f(u["u_num_chars"], self._num_chars if self._atlas_ready else 62.0)

        g.glBindVertexArray(self._vao)
        g.glDrawArrays(g.GL_TRIANGLE_STRIP, 0, 4)

    def cleanup(self) -> None:
        if self._gl is None:
            return
        g = self._gl
        if self._texture:
            g.glDeleteTextures(1, [self._texture]); self._texture = 0
        if self._atlas_texture:
            g.glDeleteTextures(1, [self._atlas_texture]); self._atlas_texture = 0
        if self._vbo:
            g.glDeleteBuffers(1, [self._vbo]); self._vbo = 0
        if self._vao:
            g.glDeleteVertexArrays(1, [self._vao]); self._vao = 0
        if self._program:
            g.glDeleteProgram(self._program); self._program = 0


class GLRendererWidget(Gtk.GLArea):
    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self._config   = config
        self._renderer = GLRenderer()
        self._wallpaper = WallpaperManager(config)
        self._tick_id: int = 0

        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_auto_render(False)

        self.connect("realize",   self._on_realize)
        self.connect("unrealize", self._on_unrealize)
        self.connect("render",    self._on_render)

    @property
    def renderer(self) -> GLRenderer:
        return self._renderer

    @property
    def current_wallpaper_path(self) -> str:
        return self._wallpaper.current_path

    def set_config(self, config: AppConfig) -> None:
        self._config = config
        self._wallpaper.configure(config)
        eff = config.effect
        c1, c2, c3 = _aurora_colors(config)
        self._renderer.set_config(
            eff.type,
            c1,
            float(eff.density),
            eff.speed,
            eff.opacity,
            eff.enabled,
            vertical_pos=eff.vertical_pos / 100.0,
            color2=c2,
            color3=c3,
        )
        self._restart_loop()
        self.queue_render()

    def stop(self) -> None:
        if self._tick_id:
            GLib.source_remove(self._tick_id)
            self._tick_id = 0

    # ------------------------------------------------------------------

    def _restart_loop(self) -> None:
        if self._tick_id:
            GLib.source_remove(self._tick_id)
            self._tick_id = 0
        interval = 16 if self._config.effect.enabled else 1000
        self._tick_id = GLib.timeout_add(interval, self._on_tick)

    def _on_tick(self) -> bool:
        changed = self._wallpaper.advance_if_due()
        if self._config.effect.enabled or changed:
            self.queue_render()
        return True

    def _on_realize(self, area) -> None:
        area.make_current()
        if area.get_error() is not None:
            return
        # Prime the renderer with the correct effect before compiling shaders.
        eff = self._config.effect
        self._renderer._effect = eff.type
        if self._renderer.initialize():
            c1, c2, c3 = _aurora_colors(self._config)
            self._renderer.set_config(
                eff.type,
                c1,
                float(eff.density),
                eff.speed,
                eff.opacity,
                eff.enabled,
                vertical_pos=eff.vertical_pos / 100.0,
                color2=c2,
                color3=c3,
            )
            cur = self._wallpaper.current_path
            if cur:
                self._renderer._load_wallpaper_texture(cur)
            self._restart_loop()
        self.queue_render()

    def _on_unrealize(self, area) -> None:
        self.stop()
        area.make_current()
        self._renderer.cleanup()

    def _on_render(self, area, _ctx) -> bool:
        area.make_current()
        if area.get_error() is not None:
            return True
        width  = area.get_allocated_width()
        height = area.get_allocated_height()
        if width <= 0 or height <= 0:
            return True
        # Reload wallpaper texture inside the GL context if path changed.
        cur = self._wallpaper.current_path
        if cur != self._renderer.current_wallpaper_path:
            self._renderer._load_wallpaper_texture(cur)
        self._renderer.render(width, height)
        return True
