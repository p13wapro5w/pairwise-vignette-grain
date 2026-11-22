"""Aspect-correct vignette and temporally stable film grain.

The helpers in this module encode the rules that keep a vignette/grain
post-process looking the same from preview to export:

* :func:`aspect_radius`   -- radius in aspect-corrected, resolution-independent
                            units instead of a fixed pixel value.
* :func:`post_tonemap`    -- vignette is applied to display-referred colour,
                            after tone mapping, so shadow detail survives.
* :func:`temporal_grain`  -- grain pattern is deterministic and held for a few
                            frames, so a static shot does not "boil".
* :func:`luminance_weight`-- grain fades out of highlights.
* :func:`linear_space`    -- grain is combined in linear light, not sRGB.
* :func:`taa_decouple`    -- grain is removed before TAA history resolves and
                            re-added afterwards, so it cannot accumulate.
* :func:`ui_mask`         -- grain is suppressed where UI alpha is present.
* :func:`export_match`    -- gain that pre-compensates codec attenuation so
                            the encoded result matches the preview.
* :func:`distortion_fit`  -- radial lens-distortion polynomial used when
                            sampling the vignette radius (wide-angle edges).
* :func:`resolution_scale`/:func:`grain_size` -- resolution-independent size.
* :func:`dither_seed`     -- stable dither seed for export.
* :func:`vignette_power`  -- falloff exponent expressed in display space.
* :func:`blend_mode`      -- validated, zero-mean grain blend description.
* :func:`clamp_range`     -- normalised-range clamp used throughout.

The module is dependency-free (pure Python scalars) so it can be shared by the
renderer, the preview and the offline export.
"""

from __future__ import annotations

import hashlib
import math


def _clamp(value, low=0.0, high=1.0):
    """Clamp *value* into ``[low, high]`` (bounds are swapped if reversed)."""
    value = float(value)
    low = float(low)
    high = float(high)
    if high < low:
        low, high = high, low
    return min(max(value, low), high)


def _positive(name, value):
    value = float(value)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be a positive finite number, got {value!r}")
    return value


def _hash_unit(*parts):
    """Deterministic hash of *parts* mapped to ``[0, 1)``."""
    digest = hashlib.blake2b(digest_size=8)
    for part in parts:
        digest.update(repr(part).encode("utf-8"))
        digest.update(b"\x1f")
    return int.from_bytes(digest.digest(), "big") / float(1 << 64)


def aspect_radius(width, height, radius_fraction=1.0):
    """Vignette radius in aspect-corrected, height-normalised units.

    Coordinates are measured with the frame height as the unit, so a point at
    the frame edge is ``0.5 * width / height`` away horizontally and ``0.5``
    away vertically.  The returned value is the distance from the centre to
    the corner (optionally scaled by *radius_fraction*), which is therefore
    different for every aspect ratio.

    Callers express the vignette radius as a fraction of this value rather
    than as a fixed number of pixels.  ``radius_fraction=1.0`` always reaches
    exactly the corners: a 21:9 frame gets a larger radius than a 16:9 frame
    and the corners are never crushed solid black.
    """
    width = _positive("width", width)
    height = _positive("height", height)
    fraction = float(radius_fraction)
    if not math.isfinite(fraction) or fraction < 0.0:
        raise ValueError(
            f"radius_fraction must be a non-negative finite number, got {fraction!r}"
        )
    aspect = width / height
    corner_distance = 0.5 * math.hypot(aspect, 1.0)
    return corner_distance * fraction


def post_tonemap(tonemapped, vignette=1.0):
    """Apply the vignette factor to already tone-mapped display colour.

    Multiplying *after* the tone mapper keeps the shadow detail that a
    pre-tonemap multiply would crush, and the operation is exposure-neutral
    because it happens in display-referred space.
    """
    return float(tonemapped) * float(vignette)


def temporal_grain(frame, seed=0, hold_frames=3):
    """Deterministic grain key for *frame*, held across *hold_frames* frames.

    Regenerating the grain every frame makes static images boil.  Holding a
    pattern for a small number of frames (or using a fixed ``seed`` with
    ``hold_frames`` large enough to cover a shot) keeps it stable, while the
    result is still a pure function of ``(seed, held frame)`` so TAA and the
    export path can reproduce the exact same pattern.
    """
    frame = int(frame)
    seed = int(seed)
    hold = max(1, int(hold_frames))
    held_frame = frame // hold
    return _hash_unit("grain", seed, held_frame)


def luminance_weight(luminance, strength=1.0):
    """Grain amount for a given luminance: full in shadows, gone at white.

    Highlights are where grain reads as dirt on the lens, so the weight
    decays as luminance approaches 1.0.  *strength* is the shadow weight.
    """
    luma = _clamp(luminance)
    weight = max(0.0, float(strength))
    return weight * (1.0 - luma)


def linear_space(value, gamma=2.2):
    """Decode an sRGB-encoded value to linear light.

    Grain is added here, before the display encode, so dark areas receive the
    same perceptual amount of noise as mid-tones instead of the exaggerated
    sRGB-space noise the old path produced.  ``gamma=2.2`` is a cheap
    approximation; pass ``2.4`` for closer sRGB behaviour.
    """
    value = max(0.0, float(value))
    gamma = _positive("gamma", gamma)
    return value ** gamma


def taa_decouple(shaded, grain):
    """Remove the grain layer before TAA history is resolved.

    The history should only contain stable scene colour.  Subtracting the
    grain first prevents it from being accumulated into a fixed pattern that
    smears when the camera moves; the grain is re-added after TAA resolves.
    """
    return max(0.0, float(shaded) - float(grain))


def ui_mask(ui_alpha, grain):
    """Reduce grain by the UI coverage at this pixel.

    ``ui_alpha`` is 0 over the 3D scene and 1 over opaque UI (subtitles,
    HUD), so UI edges stay clean instead of picking up a sandy fringe.
    """
    return float(grain) * (1.0 - _clamp(ui_alpha))


def export_match(preview_grain, encoded_grain):
    """Gain that pre-compensates codec attenuation of the grain.

    Compares the grain amplitude measured in the preview with the amplitude
    that survives in the encoded export and returns the multiplier to apply
    before encoding so the two match.  Returns ``1.0`` when the encoded
    amplitude is too small to calibrate against.
    """
    preview = max(0.0, float(preview_grain))
    encoded = max(0.0, float(encoded_grain))
    if encoded <= 1e-6:
        return 1.0
    return preview / encoded


def distortion_fit(k1, k2, radius=1.0):
    """Radial lens-distortion scale for the vignette lookup.

    Applies the Brown-Conrady radial terms ``1 + k1*r^2 + k2*r^4`` so the
    vignette follows the distorted image circle.  On wide-angle lenses this
    removes the hard edge that appears when the vignette is sampled from
    undistorted UVs.
    """
    r = max(0.0, float(radius))
    k1 = float(k1)
    k2 = float(k2)
    return r * (1.0 + k1 * r * r + k2 * r ** 4)


def resolution_scale(base_value, base_height, target_height):
    """Scale a value authored at *base_height* to *target_height*.

    Parameters written for 1080p (vignette pixel radius, grain size, blur
    radii) are multiplied by the height ratio so 4K renders show the same
    framing instead of a tiny circle in the middle.
    """
    base_height = _positive("base_height", base_height)
    target_height = _positive("target_height", target_height)
    return float(base_value) * (target_height / base_height)


def grain_size(base_size_px, resolution_scale_factor=1.0):
    """Grain cell size in pixels at the current render resolution."""
    size = float(base_size_px) * float(resolution_scale_factor)
    return max(size, 1e-6)


def vignette_power(power, display_gamma=1.0):
    """Convert a falloff exponent into display-referred space.

    Because the vignette is applied after tone mapping, a falloff authored
    against linear light must be divided by the display transfer exponent to
    keep the same visual shape.
    """
    gamma = _positive("display_gamma", display_gamma)
    return float(power) / gamma


def dither_seed(seed, frame):
    """Stable 64-bit dither seed for a given export *seed* and *frame*.

    A fixed per-frame seed makes the dither reproducible across export runs
    and machines, which is required for preview/export parity.
    """
    digest = hashlib.blake2b(
        f"{int(seed)}:{int(frame)}".encode("utf-8"), digest_size=8
    )
    return int.from_bytes(digest.digest(), "big")


_BLEND_MODES = ("multiply", "soft_light", "overlay", "screen")


def blend_mode(mode, opacity=1.0):
    """Resolve and validate the grain blend mode.

    Grain is zero-mean in linear light, so ``"multiply"`` (``1 + grain``) is
    the recommended mode.  Numeric modes index into a stable table for data
    driven effect graphs.  Returns a description ready for the compositor.
    """
    if isinstance(mode, str):
        name = mode.strip().lower()
        if name not in _BLEND_MODES:
            raise ValueError(
                f"unknown blend mode {mode!r}; expected one of {_BLEND_MODES}"
            )
    else:
        name = _BLEND_MODES[int(mode) % len(_BLEND_MODES)]
    return {"mode": name, "opacity": _clamp(opacity)}


def clamp_range(value, high=1.0, low=0.0):
    """Clamp a normalised value into ``[low, high]``.

    Used to keep the combined vignette*frame exposure inside the display
    range on every resolution and aspect ratio.
    """
    return _clamp(value, low, high)
