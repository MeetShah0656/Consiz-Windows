"""Consiz Design System — Cream & Maroon Theme Tokens (Win32).

Centralizes color tokens, typography, and widget styling rules according to
consiz-cream-maroon-ui-redesign.md.
"""
from __future__ import annotations

# Core Tokens
CREAM_50 = "#FFFCF6"   # lightest canvas / inputs / inset panels
CREAM_100 = "#F8F1E3"  # main app background
CREAM_200 = "#EFE3D0"  # elevated surface / selected neutral / cards
CREAM_300 = "#DDCBB0"  # border

MAROON_900 = "#43151B" # main text / deepest contrast
MAROON_800 = "#611E29" # headers / secondary interactive text
MAROON_700 = "#7A2835" # primary interactive
MAROON_600 = "#943846" # hover / active

INK_MUTED = "#765A56"  # secondary copy / metadata
SUCCESS = "#4E6A45"    # restrained confirmation state
WARNING = "#A55D24"    # restrained warning state
FOCUS_RING = "#A84D59" # visible accessibility focus

SELECT_BG = CREAM_300      # selected text in the answer window
SELECT_FG = MAROON_900
RECORDING_RED = "#B3261E"  # the microphone button while listening

# A Windows high-contrast theme (T-17): use ITS colours, whatever the person chose. Read once, when Consiz starts.
from . import a11y  # noqa: E402

if a11y.high_contrast():
    CREAM_50 = CREAM_100 = "SystemWindow"
    CREAM_200 = "SystemButtonFace"
    CREAM_300 = "SystemWindowText"
    MAROON_900 = MAROON_800 = INK_MUTED = SUCCESS = WARNING = "SystemWindowText"
    MAROON_700 = MAROON_600 = FOCUS_RING = RECORDING_RED = "SystemHighlight"
    SELECT_BG, SELECT_FG = "SystemHighlight", "SystemHighlightText"

# Fonts
FONT_DISPLAY = "Segoe UI"
FONT_TEXT = "Segoe UI"
