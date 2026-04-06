THEME_DARK = {
    "bg": "#08131a",
    "hdr": "#10212d",
    "card": "#132634",
    "btn_bg": "#163141",
    "brd": "#275165",
    "txt": "#eef7fb",
    "dim": "#8aa6b4",
    "mid": "#48b6d8",
    "acc": "#80c8e0",
    "acc_rgb": "128,200,224",
    "save_fg": "#061018",
    "danger": "#d35d5d",
}

THEME_LIGHT = {
    "bg": "#eef5f7",
    "hdr": "#dde9ed",
    "card": "#ffffff",
    "btn_bg": "#f8fbfc",
    "brd": "#bfd1d8",
    "txt": "#16303c",
    "dim": "#607985",
    "mid": "#0a7a9a",
    "acc": "#0f94b8",
    "acc_rgb": "15,148,184",
    "save_fg": "#f7fcfd",
    "danger": "#b54444",
}


def build_css(theme: dict) -> bytes:
    return f"""
* {{ font-family: "JetBrainsMono Nerd Font", monospace; }}
window {{ background-color: {theme["bg"]}; }}

.app-header {{
    background-color: {theme["hdr"]};
    border-bottom: 1px solid {theme["brd"]};
    padding: 16px 20px;
}}
.app-title {{ color: {theme["txt"]}; font-size: 18px; font-weight: bold; }}
.app-path {{ color: {theme["dim"]}; font-size: 12px; }}

notebook {{ background-color: {theme["bg"]}; margin: 0; }}
notebook > header.left {{
    background-color: {theme["hdr"]};
    border-right: 1px solid {theme["brd"]};
    padding: 10px 0;
}}
notebook > header > tabs > tab {{
    background-color: transparent;
    color: {theme["dim"]};
    padding: 12px 20px 12px 16px;
    border: none;
    border-left: 3px solid transparent;
    border-radius: 0;
    min-width: 134px;
}}
notebook > header > tabs > tab:checked {{
    background-color: {theme["bg"]};
    color: {theme["acc"]};
    border-left-color: {theme["acc"]};
}}
notebook > header > tabs > tab:hover:not(:checked) {{
    color: {theme["txt"]};
    background-color: rgba({theme["acc_rgb"]}, 0.08);
}}

.page-scroll,
viewport.page-scroll {{
    background-color: {theme["bg"]};
}}

.section-title {{
    color: {theme["acc"]};
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 1px;
    margin-top: 18px;
    margin-bottom: 6px;
}}
.field-label {{ color: {theme["dim"]}; font-size: 13px; }}
.hint-label {{ color: {theme["dim"]}; font-size: 12px; font-style: italic; }}
.module-title {{ color: {theme["txt"]}; font-size: 15px; font-weight: bold; }}

label {{ color: {theme["txt"]}; }}
button label {{ color: inherit; }}

entry, spinbutton, spinbutton entry, spinbutton text {{
    background-color: {theme["card"]};
    background-image: none;
    color: {theme["txt"]};
    border: 1px solid {theme["brd"]};
    border-radius: 5px;
    padding: 5px 10px;
    caret-color: {theme["acc"]};
    box-shadow: none;
}}
entry:focus, spinbutton:focus {{
    border-color: {theme["acc"]};
}}
spinbutton button {{
    background-color: {theme["btn_bg"]};
    background-image: none;
    color: {theme["txt"]};
    border: none;
    box-shadow: none;
}}

combobox, combobox button {{
    background-color: {theme["btn_bg"]};
    background-image: none;
    color: {theme["txt"]};
    border: 1px solid {theme["brd"]};
    border-radius: 5px;
    padding: 5px 8px;
    box-shadow: none;
}}

button {{
    background-color: {theme["btn_bg"]};
    background-image: none;
    color: {theme["txt"]};
    border: 1px solid {theme["brd"]};
    border-radius: 6px;
    padding: 6px 14px;
    box-shadow: none;
}}
button:hover {{
    border-color: {theme["acc"]};
    color: {theme["acc"]};
}}

.save-btn {{
    background-color: {theme["acc"]};
    background-image: none;
    color: {theme["save_fg"]};
    border: none;
    font-weight: bold;
}}
.save-btn:hover {{
    background-color: rgba({theme["acc_rgb"]}, 0.82);
    color: {theme["save_fg"]};
}}

.danger-btn {{
    color: {theme["danger"]};
}}
.danger-btn:hover {{
    border-color: {theme["danger"]};
    color: {theme["danger"]};
}}

.open-btn {{
    color: {theme["mid"]};
}}
.open-btn:hover {{
    border-color: {theme["mid"]};
    color: {theme["mid"]};
}}

.theme-btn {{
    min-width: 44px;
}}

switch {{
    background-color: {theme["brd"]};
    border-radius: 12px;
    min-width: 42px;
}}
switch slider {{
    background-color: {theme["dim"]};
    border-radius: 10px;
}}
switch:checked {{
    background-color: {theme["acc"]};
}}
switch:checked slider {{
    background-color: {theme["save_fg"]};
}}

.preview-strip {{
    background-color: {theme["hdr"]};
    border-bottom: 1px solid {theme["brd"]};
    padding: 8px 12px 10px;
}}
.preview-strip .section-title {{
    margin-top: 2px;
}}
.preview-frame {{
    background-color: {theme["card"]};
    border: 1px solid {theme["brd"]};
    border-radius: 10px;
    padding: 8px;
}}

.status-bar {{
    background-color: {theme["hdr"]};
    border-top: 1px solid {theme["brd"]};
    padding: 7px 20px;
}}
.status-ok {{ color: {theme["acc"]}; font-size: 13px; }}
.status-hint {{ color: {theme["dim"]}; font-size: 12px; }}

.plugin-card {{
    background-color: {theme["hdr"]};
    border: 1px solid {theme["brd"]};
    border-radius: 6px;
    padding: 10px 12px;
}}
.plugin-card-active {{
    background-color: {theme["hdr"]};
    border: 1px solid {theme["acc"]};
    border-radius: 6px;
    padding: 10px 12px;
}}

scrollbar {{
    background-color: transparent;
}}
scrollbar trough {{
    background-color: {theme["hdr"]};
}}
scrollbar slider {{
    background-color: {theme["brd"]};
    border-radius: 3px;
}}
""".encode()
