from __future__ import annotations

from typing import Literal


UIAltVariant = Literal[
    "device",
    "stacked_forward_over_wide",
    "stacked_wide_over_forward",
]

UI_ALT_VARIANTS: tuple[UIAltVariant, ...] = (
    "device",
    "stacked_forward_over_wide",
    "stacked_wide_over_forward",
)

DEFAULT_UI_ALT_VARIANT: UIAltVariant = "stacked_forward_over_wide"
STACKED_UI_ALT_VARIANTS: tuple[UIAltVariant, ...] = (
    "stacked_forward_over_wide",
    "stacked_wide_over_forward",
)


def resolve_ui_alt_variant(ui_alt_variant: UIAltVariant | None) -> UIAltVariant:
    return DEFAULT_UI_ALT_VARIANT if ui_alt_variant is None else ui_alt_variant


def is_stacked_ui_alt_variant(ui_alt_variant: UIAltVariant) -> bool:
    return ui_alt_variant in STACKED_UI_ALT_VARIANTS
