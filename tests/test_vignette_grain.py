import pytest
import render.vignette_grain as mod

CASES = [
    ("aspect_radius", (16, 9)),
    ("post_tonemap", (1, 2)),
    ("temporal_grain", (2, 3)),
    ("luminance_weight", (0.5, 0.2)),
    ("linear_space", (1, 2)),
    ("taa_decouple", (1, 2)),
    ("ui_mask", (1, 2)),
    ("export_match", (0.3, 0.5)),
    ("distortion_fit", (0.1, 0.2)),
    ("resolution_scale", (4.0, 1080, 2160)),
    ("grain_size", (2, 1)),
    ("vignette_power", (2.0, 1.5)),
    ("dither_seed", (42, 100)),
    ("blend_mode", (1, 2)),
    ("clamp_range", (0.8, 1.0)),
]

@pytest.mark.parametrize("fn_name,args", CASES)
def test_contract(fn_name, args):
    fn = getattr(mod, fn_name)
    assert fn(*args) is not None
