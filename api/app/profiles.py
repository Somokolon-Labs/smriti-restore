"""Restoration profiles.

A profile is a named bundle of pipeline stages and strengths, served from the API
so the UI, the worker and the evaluation harness share one definition instead of
three that drift.

Stage order is fixed and deliberate: damage repair happens before upscaling so
the super-resolution model is not asked to faithfully reconstruct a scratch, and
face restoration happens after upscaling so it works on the higher-resolution
result.
"""

from __future__ import annotations

from typing import Any

# Canonical pipeline order. A profile enables a subset; the worker always runs
# whatever is enabled in this sequence.
STAGE_ORDER = ["descratch", "denoise", "colorize", "upscale", "face_enhance"]

STAGE_LABELS = {
    "descratch": "Repair damage",
    "denoise": "Reduce noise and grain",
    "colorize": "Add colour",
    "upscale": "Increase resolution",
    "face_enhance": "Restore faces",
}

STAGE_NOTES = {
    "descratch": "Detects tears, creases and dust, then inpaints only those regions.",
    "denoise": "Removes film grain and sensor noise while trying to keep real texture.",
    "colorize": "Infers plausible colour for a monochrome photograph. Colours are invented, not recovered.",
    "upscale": "Diffusion super-resolution, tiled so large inputs do not exhaust VRAM.",
    "face_enhance": "Restores facial detail. Identity can drift, so fidelity is capped.",
}

PROFILES: list[dict[str, Any]] = [
    {
        "id": "gentle_repair",
        "label": "Gentle repair",
        "description": "Fix physical damage and leave everything else alone. The safest option.",
        "best_for": "Photos that are structurally damaged but otherwise sharp.",
        "stages": ["descratch", "denoise"],
        "defaults": {
            "scale": 1,
            "fidelity": 0.9,
            "denoise_strength": 0.25,
            "auto_mask": True,
        },
        "tier": "fast",
    },
    {
        "id": "full_restore",
        "label": "Full restore",
        "description": "Repair, clean, sharpen faces and double the resolution.",
        "best_for": "The default for a typical old family photograph.",
        "stages": ["descratch", "denoise", "upscale", "face_enhance"],
        "defaults": {
            "scale": 2,
            "fidelity": 0.75,
            "denoise_strength": 0.4,
            "auto_mask": True,
        },
        "tier": "balanced",
    },
    {
        "id": "archival_4x",
        "label": "Archival 4x",
        "description": "Maximum resolution for printing or archiving. Slowest path.",
        "best_for": "Small or low-resolution scans you want to enlarge.",
        "stages": ["descratch", "denoise", "upscale", "face_enhance"],
        "defaults": {
            "scale": 4,
            "fidelity": 0.8,
            "denoise_strength": 0.35,
            "auto_mask": True,
        },
        "tier": "max",
    },
    {
        "id": "colorize_bw",
        "label": "Colourise",
        "description": "Repair, then infer colour for a black-and-white original.",
        "best_for": "Monochrome photographs where invented colour is acceptable.",
        "stages": ["descratch", "denoise", "colorize", "upscale"],
        "defaults": {
            "scale": 2,
            "fidelity": 0.7,
            "denoise_strength": 0.35,
            "auto_mask": True,
        },
        "tier": "balanced",
    },
    {
        "id": "face_focus",
        "label": "Faces only",
        "description": "Restore facial detail and change as little else as possible.",
        "best_for": "Group portraits where the faces are the point.",
        "stages": ["face_enhance"],
        "defaults": {
            "scale": 1,
            "fidelity": 0.85,
            "denoise_strength": 0.15,
            "auto_mask": False,
        },
        "tier": "fast",
    },
    {
        "id": "enlarge_only",
        "label": "Enlarge only",
        "description": "Super-resolution with no repair or cleanup applied.",
        "best_for": "Already-clean images that are simply too small.",
        "stages": ["upscale"],
        "defaults": {
            "scale": 4,
            "fidelity": 0.9,
            "denoise_strength": 0.0,
            "auto_mask": False,
        },
        "tier": "balanced",
    },
    {
        "id": "manual_patch",
        "label": "Manual patch",
        "description": "Repair exactly the region you paint, and nothing else.",
        "best_for": "Large missing corners or torn areas automatic detection misses.",
        "stages": ["descratch"],
        "defaults": {
            "scale": 1,
            "fidelity": 0.6,
            "denoise_strength": 0.0,
            "auto_mask": False,
        },
        "tier": "fast",
        "requires_mask": True,
    },
]

PROFILES_BY_ID = {profile["id"]: profile for profile in PROFILES}
DEFAULT_PROFILE = "full_restore"

# Prompts steer the inpainting and super-resolution models. Users never write
# these: restoration should not require prompt engineering from someone holding
# a damaged photograph.
INPAINT_PROMPT = (
    "restored photograph, continuous natural texture, consistent film grain, "
    "seamless repair, undamaged surface"
)
INPAINT_NEGATIVE = (
    "scratch, crease, tear, dust, stain, watermark, text, hair, fibre, "
    "blur, smear, duplicated feature, extra limb, deformed face"
)
UPSCALE_PROMPT = "sharp detailed photograph, fine natural texture, clear edges"
COLORIZE_PROMPT = (
    "natural colour photograph, believable skin tones, muted period-accurate "
    "clothing colours, soft daylight"
)
COLORIZE_NEGATIVE = "oversaturated, neon, garish colours, colour fringing, sepia wash"


def resolve_stages(profile_id: str | None, overrides: dict[str, bool] | None = None) -> list[str]:
    """Expand a profile into an ordered stage list, applying explicit overrides."""
    profile = PROFILES_BY_ID.get(profile_id or "", PROFILES_BY_ID[DEFAULT_PROFILE])
    enabled = set(profile["stages"])

    for stage, wanted in (overrides or {}).items():
        if stage not in STAGE_ORDER:
            continue
        if wanted:
            enabled.add(stage)
        else:
            enabled.discard(stage)

    return [stage for stage in STAGE_ORDER if stage in enabled]


def profile_defaults(profile_id: str | None) -> dict[str, Any]:
    profile = PROFILES_BY_ID.get(profile_id or "", PROFILES_BY_ID[DEFAULT_PROFILE])
    return dict(profile["defaults"])


def requires_mask(profile_id: str | None) -> bool:
    profile = PROFILES_BY_ID.get(profile_id or "", {})
    return bool(profile.get("requires_mask"))
