"""
Vega Launcher — Theme & Accent Palette Manager (theme_manager.py)
Provides 5 distinct Minecraft accent themes and procedural banner presets.
Allows instant dynamic stylesheet & particle palette updates without app restart.
"""

from typing import Dict, Any, List
from PySide6.QtGui import QColor

# Base template tokens present in style.qss (Electric Amethyst defaults)
BASE_PRIMARY = "#8B5CF6"
BASE_PRIMARY_LIGHT = "#A855F7"
BASE_GLOW = "#C084FC"
BASE_GRAD_START = "#7C3AED"
BASE_PRESSED = "#6D28D9"
BASE_SECONDARY = "#06B6D4"
BASE_SECONDARY_LIGHT = "#22D3EE"
BASE_TEXT_TINT = "#E9D5FF"
BASE_BEVEL_TOP = "#A78BFA"
BASE_BEVEL_BOTTOM = "#4C1D95"

BASE_RGBA_PREFIX = "rgba(139, 92, 246,"
BASE_GRAD_RGBA_PREFIX = "rgba(124, 58, 237,"
BASE_GLOW_RGBA_PREFIX = "rgba(192, 132, 252,"
BASE_SECONDARY_RGBA_PREFIX = "rgba(6, 182, 212,"

THEMES: Dict[str, Dict[str, Any]] = {
    "electric_amethyst": {
        "name_tr": "Elektrik Ametist (Mor)",
        "name_en": "Electric Amethyst (Purple)",
        "primary": "#8B5CF6",
        "primary_light": "#A855F7",
        "glow": "#C084FC",
        "gradient_start": "#7C3AED",
        "pressed": "#6D28D9",
        "secondary": "#06B6D4",
        "secondary_light": "#22D3EE",
        "text_tint": "#E9D5FF",
        "bevel_top": "#A78BFA",
        "bevel_bottom": "#4C1D95",
        "rgb": (139, 92, 246),
        "grad_start_rgb": (124, 58, 237),
        "glow_rgb": (192, 132, 252),
        "secondary_rgb": (6, 182, 212),
        "particles": [
            QColor(168, 85, 247),
            QColor(192, 132, 252),
            QColor(139, 92, 246),
            QColor(34, 211, 238),
        ],
    },
    "ender_pearl": {
        "name_tr": "Ender İncisi (Turkuaz)",
        "name_en": "Ender Pearl (Cyan)",
        "primary": "#06B6D4",
        "primary_light": "#22D3EE",
        "glow": "#67E8F9",
        "gradient_start": "#0891B2",
        "pressed": "#0E7490",
        "secondary": "#8B5CF6",
        "secondary_light": "#A855F7",
        "text_tint": "#CFFAFE",
        "bevel_top": "#67E8F9",
        "bevel_bottom": "#0E7490",
        "rgb": (6, 182, 212),
        "grad_start_rgb": (8, 145, 178),
        "glow_rgb": (103, 232, 249),
        "secondary_rgb": (139, 92, 246),
        "particles": [
            QColor(6, 182, 212),
            QColor(34, 211, 238),
            QColor(103, 232, 249),
            QColor(168, 85, 247),
        ],
    },
    "nether_crimson": {
        "name_tr": "Nether Kızılı (Kırmızı)",
        "name_en": "Nether Crimson (Red)",
        "primary": "#EF4444",
        "primary_light": "#F87171",
        "glow": "#FCA5A5",
        "gradient_start": "#DC2626",
        "pressed": "#B91C1C",
        "secondary": "#F59E0B",
        "secondary_light": "#FBBF24",
        "text_tint": "#FEE2E2",
        "bevel_top": "#F87171",
        "bevel_bottom": "#7F1D1D",
        "rgb": (239, 68, 68),
        "grad_start_rgb": (220, 38, 38),
        "glow_rgb": (252, 165, 165),
        "secondary_rgb": (245, 158, 11),
        "particles": [
            QColor(239, 68, 68),
            QColor(248, 113, 113),
            QColor(245, 158, 11),
            QColor(252, 165, 165),
        ],
    },
    "emerald_lush": {
        "name_tr": "Zümrüt Yeşili (Yeşil)",
        "name_en": "Emerald Lush (Green)",
        "primary": "#10B981",
        "primary_light": "#34D399",
        "glow": "#6EE7B7",
        "gradient_start": "#059669",
        "pressed": "#047857",
        "secondary": "#0EA5E9",
        "secondary_light": "#38BDF8",
        "text_tint": "#D1FAE5",
        "bevel_top": "#6EE7B7",
        "bevel_bottom": "#065F46",
        "rgb": (16, 185, 129),
        "grad_start_rgb": (5, 150, 105),
        "glow_rgb": (110, 231, 183),
        "secondary_rgb": (14, 165, 233),
        "particles": [
            QColor(16, 185, 129),
            QColor(52, 211, 153),
            QColor(110, 231, 183),
            QColor(59, 130, 246),
        ],
    },
    "sculk_dark": {
        "name_tr": "Derin Karanlık (Sculk Mavisi)",
        "name_en": "Deep Dark (Sculk Blue)",
        "primary": "#0EA5E9",
        "primary_light": "#38BDF8",
        "glow": "#7DD3FC",
        "gradient_start": "#0284C7",
        "pressed": "#0369A1",
        "secondary": "#6366F1",
        "secondary_light": "#818CF8",
        "text_tint": "#E0F2FE",
        "bevel_top": "#7DD3FC",
        "bevel_bottom": "#075985",
        "rgb": (14, 165, 233),
        "grad_start_rgb": (2, 132, 199),
        "glow_rgb": (125, 211, 252),
        "secondary_rgb": (99, 102, 241),
        "particles": [
            QColor(14, 165, 233),
            QColor(56, 189, 248),
            QColor(125, 211, 252),
            QColor(99, 102, 241),
        ],
    },
}

BANNER_PRESETS: Dict[str, Dict[str, str]] = {
    "end_void": {
        "name_tr": "End Boşluğu",
        "name_en": "End Void",
        "gradient": "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1E0B38, stop:0.55 #11071F, stop:1 #06030D)",
        "accent": "#C084FC",
    },
    "nether_fortress": {
        "name_tr": "Nether Kalesi",
        "name_en": "Nether Fortress",
        "gradient": "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3D080D, stop:0.55 #220407, stop:1 #0F0203)",
        "accent": "#F87171",
    },
    "lush_caves": {
        "name_tr": "Bereketli Mağaralar",
        "name_en": "Lush Caves",
        "gradient": "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #083320, stop:0.55 #041C11, stop:1 #020B07)",
        "accent": "#34D399",
    },
    "deep_dark": {
        "name_tr": "Derin Karanlık",
        "name_en": "Deep Dark",
        "gradient": "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #062238, stop:0.55 #03121F, stop:1 #01060B)",
        "accent": "#38BDF8",
    },
    "cyber_void": {
        "name_tr": "Siber Boşluk",
        "name_en": "Cyber Void",
        "gradient": "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #22133D, stop:0.55 #140D24, stop:1 #0A0A12)",
        "accent": "#A855F7",
    },
}


def get_theme(theme_key: str) -> Dict[str, Any]:
    return THEMES.get(theme_key, THEMES["electric_amethyst"])


def get_theme_names(lang: str = "tr") -> List[tuple]:
    """Returns list of (key, display_name)."""
    is_en = lang == "en"
    result = []
    for k, t in THEMES.items():
        name = t["name_en"] if is_en else t["name_tr"]
        result.append((k, name))
    return result


def generate_theme_qss(base_qss: str, theme_key: str) -> str:
    """Dynamically transforms base stylesheet with selected accent palette."""
    if not base_qss:
        return ""
    if theme_key not in THEMES or theme_key == "electric_amethyst":
        return base_qss

    t = THEMES[theme_key]
    r, g, b = t["rgb"]
    target_rgba = f"rgba({r}, {g}, {b},"

    gr_r, gr_g, gr_b = t.get("grad_start_rgb", (r, g, b))
    target_grad_rgba = f"rgba({gr_r}, {gr_g}, {gr_b},"

    gw_r, gw_g, gw_b = t.get("glow_rgb", (r, g, b))
    target_glow_rgba = f"rgba({gw_r}, {gw_g}, {gw_b},"

    sec_r, sec_g, sec_b = t.get("secondary_rgb", (6, 182, 212))
    target_sec_rgba = f"rgba({sec_r}, {sec_g}, {sec_b},"

    # Step 1: Replace base tokens with collision-safe unique placeholders
    qss = base_qss.replace(BASE_RGBA_PREFIX, "___TK_RGBA_PRIM___")
    qss = qss.replace(BASE_GRAD_RGBA_PREFIX, "___TK_RGBA_GRAD___")
    qss = qss.replace(BASE_GLOW_RGBA_PREFIX, "___TK_RGBA_GLOW___")
    qss = qss.replace(BASE_SECONDARY_RGBA_PREFIX, "___TK_RGBA_SEC___")

    qss = qss.replace(BASE_PRIMARY, "___TK_PRIMARY___")
    qss = qss.replace(BASE_PRIMARY_LIGHT, "___TK_PRIM_LIGHT___")
    qss = qss.replace(BASE_GLOW, "___TK_GLOW___")
    qss = qss.replace(BASE_GRAD_START, "___TK_GRAD_START___")
    qss = qss.replace(BASE_PRESSED, "___TK_PRESSED___")
    qss = qss.replace(BASE_SECONDARY, "___TK_SECONDARY___")
    qss = qss.replace(BASE_SECONDARY_LIGHT, "___TK_SEC_LIGHT___")
    qss = qss.replace(BASE_TEXT_TINT, "___TK_TEXT_TINT___")
    qss = qss.replace(BASE_BEVEL_TOP, "___TK_BEVEL_TOP___")
    qss = qss.replace(BASE_BEVEL_BOTTOM, "___TK_BEVEL_BTM___")

    # Step 2: Replace placeholders with target theme values
    qss = qss.replace("___TK_RGBA_PRIM___", target_rgba)
    qss = qss.replace("___TK_RGBA_GRAD___", target_grad_rgba)
    qss = qss.replace("___TK_RGBA_GLOW___", target_glow_rgba)
    qss = qss.replace("___TK_RGBA_SEC___", target_sec_rgba)

    qss = qss.replace("___TK_PRIMARY___", t["primary"])
    qss = qss.replace("___TK_PRIM_LIGHT___", t["primary_light"])
    qss = qss.replace("___TK_GLOW___", t["glow"])
    qss = qss.replace("___TK_GRAD_START___", t["gradient_start"])
    qss = qss.replace("___TK_PRESSED___", t["pressed"])
    qss = qss.replace("___TK_SECONDARY___", t.get("secondary", BASE_SECONDARY))
    qss = qss.replace("___TK_SEC_LIGHT___", t.get("secondary_light", BASE_SECONDARY_LIGHT))
    qss = qss.replace("___TK_TEXT_TINT___", t.get("text_tint", "#FFFFFF"))
    qss = qss.replace("___TK_BEVEL_TOP___", t.get("bevel_top", BASE_BEVEL_TOP))
    qss = qss.replace("___TK_BEVEL_BTM___", t.get("bevel_bottom", BASE_BEVEL_BOTTOM))

    return qss


def get_banner_preset(preset_key: str) -> Dict[str, str]:
    return BANNER_PRESETS.get(preset_key, BANNER_PRESETS["end_void"])


def get_banner_preset_names(lang: str = "tr") -> List[tuple]:
    is_en = lang == "en"
    result = []
    for k, b in BANNER_PRESETS.items():
        name = b["name_en"] if is_en else b["name_tr"]
        result.append((k, name))
    return result
