from .aurora import AuroraEffect
from .droplets import DropletsEffect
from .gradient import GradientFlowEffect
from .matrix import MatrixEffect
from .rain import RainEffect
from .snow import SnowEffect
from .stars import StarsEffect
from .waves import WavesEffect
from .warp import WarpEffect


EFFECTS = {
    "rain":     RainEffect,
    "matrix":   MatrixEffect,
    "aurora":   AuroraEffect,
    "warp":     WarpEffect,
    "snow":     SnowEffect,
    "gradient": GradientFlowEffect,
    "stars":    StarsEffect,
    "waves":    WavesEffect,
    "droplets": DropletsEffect,
}


def create_effect(config, accent_color):
    effect_cls = EFFECTS.get(config.type, RainEffect)
    return effect_cls(config, accent_color)
