"""
ui_components.py
────────────────
Reusable UI building blocks for the Transformers desktop app.
Provides factory functions for cards, upload rows, buttons, status
badges, and navigation items — all styled to the enterprise design system.
"""

import customtkinter as ctk
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

# ════════════════════════════════════════════════════════════════
#  Design Tokens
# ════════════════════════════════════════════════════════════════

COLOR_BG           = "#0B1020"
COLOR_SIDEBAR      = "#0E1529"
COLOR_SIDEBAR_SEP  = "#1A2340"
COLOR_CARD         = "#111827"
COLOR_CARD_HOVER   = "#151B2D"
COLOR_ACCENT       = "#194CFF"
COLOR_ACCENT_HOVER = "#2D5FFF"
COLOR_SUCCESS      = "#22C55E"
COLOR_WARNING      = "#F59E0B"
COLOR_ERROR        = "#EF4444"
COLOR_TEXT          = "#FFFFFF"
COLOR_TEXT_SEC      = "#AAB2C8"
COLOR_TEXT_DIM      = "#6B7394"
COLOR_BORDER       = "#1E293B"
COLOR_INPUT_BG     = "#0F1A2E"
COLOR_BTN_SEC      = "#1A2340"
COLOR_BTN_SEC_HOV  = "#243052"
COLOR_NAV_HOVER    = "#152040"
COLOR_NAV_ACTIVE   = "#0D1B3F"

FONT_FAMILY = "Segoe UI"

import math
from PIL import Image, ImageDraw

# ════════════════════════════════════════════════════════════════
#  High-DPI Graphic Icon Engine (PIL Vector / Canvas Renderer)
# ════════════════════════════════════════════════════════════════

_PIL_ICON_CACHE = {}

def get_icon(name: str, size=(20, 20), color=None) -> ctk.CTkImage:
    """
    Returns a crisp, anti-aliased CTkImage icon rendered dynamically.
    Caches the underlying PIL.Image to ensure 100% compatibility across
    multiple Tkinter root window lifecycles and tests without TclError.
    """
    if color is None:
        color = COLOR_ACCENT
        
    key = (str(name).lower().strip(), size[0], size[1], str(color))
    if key in _PIL_ICON_CACHE:
        pil_img = _PIL_ICON_CACHE[key]
        return ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=size)
        
    CANVAS = 96
    img = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    
    n = key[0]
    
    # Mapping aliases
    if n in ("home", "dashboard", "transform_overview", "overview", "⬢", "⊞"):
        d.line([(18, 46), (48, 18), (78, 46)], fill=color, width=6)
        d.line([(26, 44), (26, 80), (70, 80), (70, 44)], fill=color, width=6)
        d.line([(40, 80), (40, 56), (56, 56), (56, 80)], fill=color, width=6)
        
    elif n in ("kra", "transform", "kra_management", "◈"):
        d.polygon([(48, 14), (82, 48), (48, 82), (14, 48)], outline=color, width=6)
        d.line([(48, 28), (48, 68)], fill=color, width=5)
        d.line([(28, 48), (68, 48)], fill=color, width=5)
        d.ellipse([43, 43, 53, 53], fill=color)
        
    elif n in ("time_leave", "calendar", "date", "time_and_leave", "◫"):
        d.rounded_rectangle([16, 22, 80, 82], radius=12, outline=color, width=6)
        d.line([(16, 40), (80, 40)], fill=color, width=6)
        d.line([(32, 12), (32, 26)], fill=color, width=6)
        d.line([(64, 12), (64, 26)], fill=color, width=6)
        for x in (32, 48, 64):
            for y in (54, 68):
                d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=color)
                
    elif n in ("attendance", "attendance_summary", "clipboard", "check_list", "◧"):
        d.rounded_rectangle([18, 22, 78, 84], radius=10, outline=color, width=6)
        d.rounded_rectangle([34, 12, 62, 26], radius=5, outline=color, width=5)
        d.line([(32, 54), (44, 66), (66, 42)], fill=color, width=6)
        
    elif n in ("absent", "absent_management", "user_x", "◉"):
        d.ellipse([34, 14, 62, 42], outline=color, width=6)
        d.arc([16, 46, 80, 96], start=180, end=0, fill=color, width=6)
        d.ellipse([56, 56, 84, 84], fill=COLOR_CARD, outline=color, width=4)
        d.line([(64, 70), (76, 70)], fill=color, width=4)
        
    elif n in ("id_card", "idcard", "badge", "🪪"):
        d.rounded_rectangle([16, 18, 80, 82], radius=12, outline=color, width=6)
        d.rounded_rectangle([38, 10, 58, 20], radius=4, outline=color, width=4)
        d.rounded_rectangle([26, 32, 48, 54], radius=4, outline=color, width=4)
        d.line([(54, 38), (70, 38)], fill=color, width=4)
        d.line([(54, 48), (66, 48)], fill=color, width=4)
        d.line([(26, 66), (70, 66)], fill=color, width=4)
        
    elif n in ("analyse", "analytics", "chart", "barchart", "workforce_intelligence", "⬡"):
        d.rounded_rectangle([18, 56, 32, 80], radius=4, fill=color)
        d.rounded_rectangle([41, 36, 55, 80], radius=4, fill=color)
        d.rounded_rectangle([64, 18, 78, 80], radius=4, fill=color)
        
    elif n in ("time_series", "trend", "analyse_time_series", "timeseries"):
        d.line([(18, 18), (18, 80), (82, 80)], fill=color, width=5)
        pts = [(24, 62), (42, 38), (60, 52), (78, 24)]
        d.line(pts, fill=color, width=5)
        for px, py in pts:
            d.ellipse([px - 4, py - 4, px + 4, py + 4], fill=color)
            
    elif n in ("settings", "gear", "⚙", "settings_connectors"):
        cx, cy, r_out, r_in = 48, 48, 34, 18
        for i in range(8):
            ang = i * (math.pi / 4)
            tx = cx + 38 * math.cos(ang)
            ty = cy + 38 * math.sin(ang)
            d.ellipse([tx - 6, ty - 6, tx + 6, ty + 6], fill=color)
        d.ellipse([cx - r_out, cy - r_out, cx + r_out, cy + r_out], outline=color, width=7)
        d.ellipse([cx - r_in, cy - r_in, cx + r_in, cy + r_in], outline=color, width=6)
        
    elif n in ("connectors", "link", "plugin", "🔌"):
        d.rounded_rectangle([16, 36, 50, 60], radius=8, outline=color, width=6)
        d.rounded_rectangle([46, 36, 80, 60], radius=8, outline=color, width=6)
        
    elif n in ("upload", "analyse_upload", "⬆"):
        d.line([(18, 64), (18, 80), (78, 80), (78, 64)], fill=color, width=6)
        d.line([(48, 20), (48, 62)], fill=color, width=6)
        d.line([(30, 38), (48, 18), (66, 38)], fill=color, width=6)
        
    elif n in ("download", "export"):
        d.line([(18, 64), (18, 80), (78, 80), (78, 64)], fill=color, width=6)
        d.line([(48, 18), (48, 60)], fill=color, width=6)
        d.line([(30, 42), (48, 62), (66, 42)], fill=color, width=6)
        
    elif n in ("refresh", "sync"):
        d.arc([18, 18, 78, 78], start=30, end=190, fill=color, width=6)
        d.polygon([(78, 54), (88, 38), (68, 42)], fill=color)
        d.arc([18, 18, 78, 78], start=210, end=10, fill=color, width=6)
        d.polygon([(18, 42), (8, 58), (28, 54)], fill=color)
        
    elif n in ("search",):
        d.ellipse([18, 18, 60, 60], outline=color, width=6)
        d.line([(52, 52), (80, 80)], fill=color, width=7)
        
    elif n in ("check", "success", "✓"):
        d.ellipse([14, 14, 82, 82], outline=color, width=6)
        d.line([(28, 48), (42, 62), (68, 34)], fill=color, width=6)
        
    elif n in ("cross", "error", "close", "✕"):
        d.ellipse([14, 14, 82, 82], outline=color, width=6)
        d.line([(32, 32), (64, 64)], fill=color, width=6)
        d.line([(64, 32), (32, 64)], fill=color, width=6)
        
    elif n in ("alert", "warning", "!"):
        d.polygon([(48, 14), (84, 80), (12, 80)], outline=color, width=6)
        d.line([(48, 38), (48, 58)], fill=color, width=6)
        d.ellipse([45, 66, 51, 72], fill=color)
        
    elif n in ("folder", "browse"):
        d.polygon([(16, 26), (42, 26), (50, 36), (80, 36), (80, 78), (16, 78)], outline=color, width=6)
        d.line([(16, 38), (80, 38)], fill=color, width=5)
        
    elif n in ("file", "document", "excel", "📄"):
        d.polygon([(22, 14), (60, 14), (74, 28), (74, 82), (22, 82)], outline=color, width=6)
        d.line([(60, 14), (60, 30), (74, 30)], fill=color, width=5)
        d.line([(32, 46), (64, 46)], fill=color, width=5)
        d.line([(32, 58), (64, 58)], fill=color, width=5)
        d.line([(32, 70), (54, 70)], fill=color, width=5)
        
    elif n in ("eye", "preview"):
        d.arc([16, 20, 80, 76], start=30, end=150, fill=color, width=6)
        d.arc([16, 20, 80, 76], start=210, end=330, fill=color, width=6)
        d.ellipse([38, 38, 58, 58], fill=color)
        
    elif n in ("mail", "email"):
        d.rounded_rectangle([16, 24, 80, 74], radius=8, outline=color, width=6)
        d.line([(18, 28), (48, 52), (78, 28)], fill=color, width=6)
        
    elif n in ("zap", "bolt", "flash", "⚡"):
        d.polygon([(52, 12), (26, 48), (48, 48), (44, 84), (72, 44), (50, 44)], fill=color)
        
    elif n in ("user", "person"):
        d.ellipse([34, 14, 62, 42], outline=color, width=6)
        d.arc([18, 48, 78, 96], start=180, end=0, fill=color, width=6)
        
    elif n in ("users", "team"):
        d.ellipse([44, 16, 68, 40], outline=color, width=5)
        d.arc([30, 46, 84, 90], start=180, end=0, fill=color, width=5)
        d.ellipse([26, 24, 46, 44], outline=color, width=5)
        d.arc([14, 50, 60, 90], start=180, end=0, fill=color, width=5)
        
    elif n in ("lock",):
        d.arc([30, 14, 66, 50], start=180, end=0, fill=color, width=6)
        d.rounded_rectangle([22, 42, 74, 82], radius=8, fill=color)
        d.ellipse([44, 56, 52, 64], fill=COLOR_CARD)
        d.line([(48, 64), (48, 72)], fill=COLOR_CARD, width=4)
        
    elif n in ("filter",):
        d.polygon([(16, 20), (80, 20), (56, 48), (56, 78), (40, 78), (40, 48)], outline=color, width=6)
        
    elif n in ("arrow_right", "next", "→"):
        d.line([(20, 48), (74, 48)], fill=color, width=6)
        d.line([(52, 26), (74, 48), (52, 70)], fill=color, width=6)
        
    elif n in ("arrow_left", "back", "←"):
        d.line([(76, 48), (22, 48)], fill=color, width=6)
        d.line([(44, 26), (22, 48), (44, 70)], fill=color, width=6)
        
    elif n in ("chevron_right", "›", "▸"):
        d.line([(34, 22), (62, 48), (34, 74)], fill=color, width=7)
        
    elif n in ("chevron_down", "⌄", "▾"):
        d.line([(22, 34), (48, 62), (74, 34)], fill=color, width=7)
        
    elif n in ("chevron_left", "‹", "◂"):
        d.line([(62, 22), (34, 48), (62, 74)], fill=color, width=7)
        
    elif n in ("play", "launch"):
        d.polygon([(34, 22), (74, 48), (34, 74)], fill=color)
        
    elif n in ("save", "disk", "floppy"):
        d.rounded_rectangle([18, 16, 78, 80], radius=8, outline=color, width=6)
        d.rounded_rectangle([28, 16, 68, 38], radius=4, fill=color)
        d.rounded_rectangle([32, 52, 64, 76], radius=4, outline=color, width=5)
    elif n in ("copy",):
        d.rounded_rectangle([18, 30, 60, 80], radius=6, outline=color, width=5)
        d.rounded_rectangle([36, 16, 78, 66], radius=6, outline=color, width=5)
        
    elif n in ("slack",):
        d.rounded_rectangle([20, 36, 44, 48], radius=6, fill=color)
        d.rounded_rectangle([52, 48, 76, 60], radius=6, fill=color)
        d.rounded_rectangle([36, 52, 48, 76], radius=6, fill=color)
        d.rounded_rectangle([48, 20, 60, 44], radius=6, fill=color)
        
    else:
        d.ellipse([24, 24, 72, 72], outline=color, width=6)
        d.ellipse([40, 40, 56, 56], fill=color)
        
    resized = img.resize(size, Image.Resampling.LANCZOS)
    _PIL_ICON_CACHE[key] = resized
    return ctk.CTkImage(light_image=resized, dark_image=resized, size=size)

# ════════════════════════════════════════════════════════════════
#  Icon constants (Unicode)
# ════════════════════════════════════════════════════════════════

ICON_HOME       = "⬢"
ICON_KRA        = "◈"
ICON_ABSENT     = "◉"
ICON_ATTENDANCE = "◧"
ICON_TIME_LEAVE = "◫"
ICON_ANALYSE    = "⬡"
ICON_DASHBOARD  = "⊞"
ICON_SETTINGS   = "⚙"
ICON_UPLOAD     = "⬆"
ICON_CHECK      = "✓"
ICON_CROSS      = "✕"
ICON_DOT        = "●"
ICON_FILE       = "📄"
ICON_IDCARD     = "🪪"


# ════════════════════════════════════════════════════════════════
#  Factory helpers
# ════════════════════════════════════════════════════════════════

def create_page_header(parent, title: str, subtitle: str = ""):
    """Create a page title + optional subtitle block."""
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.grid_columnconfigure(0, weight=1)

    lbl_title = ctk.CTkLabel(
        frame, text=title,
        font=ctk.CTkFont(family=FONT_FAMILY, size=28, weight="bold"),
        text_color=COLOR_TEXT, anchor="w",
    )
    lbl_title.grid(row=0, column=0, sticky="w")

    if subtitle:
        lbl_sub = ctk.CTkLabel(
            frame, text=subtitle,
            font=ctk.CTkFont(family=FONT_FAMILY, size=14),
            text_color=COLOR_TEXT_SEC, anchor="w",
        )
        lbl_sub.grid(row=1, column=0, sticky="w", pady=(4, 0))

    return frame


def create_card(parent, **grid_kw):
    """Return a styled card frame with rounded corners and border."""
    card = ctk.CTkFrame(
        parent, corner_radius=12, fg_color=COLOR_CARD,
        border_width=1, border_color=COLOR_BORDER,
    )
    if grid_kw:
        card.grid(**grid_kw)
    card.grid_columnconfigure(0, weight=1)
    return card


def create_dashboard_card(parent, icon: str, title: str, description: str,
                          status: str, command, row: int, col: int):
    """Create a dashboard module card with crisp graphic icon, title, desc, badge, button."""
    card = ctk.CTkFrame(
        parent, corner_radius=12, fg_color=COLOR_CARD,
        border_width=1, border_color=COLOR_BORDER,
    )
    card.grid(row=row, column=col, sticky="nsew", padx=8, pady=8)
    card.grid_columnconfigure(0, weight=1)

    # Icon + Title row
    top = ctk.CTkFrame(card, fg_color="transparent")
    top.grid(row=0, column=0, sticky="ew", padx=24, pady=(24, 0))

    # Render high-DPI graphic icon
    icon_img = get_icon(icon, size=(28, 28), color=COLOR_ACCENT)
    lbl_ic = ctk.CTkLabel(top, text="", image=icon_img)
    lbl_ic.pack(side="left", padx=(0, 12))

    ctk.CTkLabel(
        top, text=title,
        font=ctk.CTkFont(family=FONT_FAMILY, size=18, weight="bold"),
        text_color=COLOR_TEXT,
    ).pack(side="left")

    # Description
    ctk.CTkLabel(
        card, text=description,
        font=ctk.CTkFont(family=FONT_FAMILY, size=13),
        text_color=COLOR_TEXT_SEC, anchor="w", justify="left",
    ).grid(row=1, column=0, sticky="w", padx=24, pady=(8, 0))

    # Bottom row: badge + button
    bottom = ctk.CTkFrame(card, fg_color="transparent")
    bottom.grid(row=2, column=0, sticky="ew", padx=24, pady=(16, 24))

    badge_color = COLOR_SUCCESS if status == "Active" else COLOR_TEXT_DIM
    ctk.CTkLabel(
        bottom, text=f"●  {status}",
        font=ctk.CTkFont(family=FONT_FAMILY, size=12),
        text_color=badge_color,
    ).pack(side="left")

    create_primary_button(bottom, "Launch →", command).pack(side="right")

    return card


def create_upload_row(parent, string_var, placeholder: str,
                      btn_text: str = "Browse", row: int = 0):
    """Create a file-path entry + browse button row."""
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.grid(row=row, column=0, sticky="ew", padx=16, pady=(0, 12))
    frame.grid_columnconfigure(0, weight=1)

    lbl = ctk.CTkLabel(
        frame, text=placeholder,
        font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
        text_color=COLOR_TEXT_DIM
    )
    lbl.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))

    entry = ctk.CTkEntry(
        frame, textvariable=string_var,
        placeholder_text="No file selected...", height=32,
        font=ctk.CTkFont(family=FONT_FAMILY, size=12),
        fg_color=COLOR_INPUT_BG, border_color=COLOR_BORDER,
        border_width=1, corner_radius=6,
        text_color=COLOR_TEXT,
        placeholder_text_color=COLOR_TEXT_DIM,
    )
    entry.grid(row=1, column=0, sticky="ew", padx=(0, 8))

    btn = ctk.CTkButton(
        frame, text=f" {btn_text}", width=90, height=32, corner_radius=6,
        font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
        fg_color=COLOR_BTN_SEC, hover_color=COLOR_BTN_SEC_HOV,
        text_color=COLOR_TEXT,
        image=get_icon("folder", size=(16, 16), color=COLOR_TEXT),
        compound="left",
        command=lambda: _browse_file(string_var),
    )
    btn.grid(row=1, column=1)
    return frame, entry, btn


def create_primary_button(parent, text: str, command, width=110, height=32, icon: str = None):
    """Return a styled primary action button with optional graphic icon."""
    kwargs = {
        "text": text,
        "width": width,
        "height": height,
        "corner_radius": 6,
        "font": ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
        "fg_color": COLOR_ACCENT,
        "hover_color": COLOR_ACCENT_HOVER,
        "text_color": COLOR_TEXT,
        "command": command,
    }
    if icon:
        kwargs["image"] = get_icon(icon, size=(16, 16), color=COLOR_TEXT)
        if text:
            kwargs["compound"] = "left"
    return ctk.CTkButton(parent, **kwargs)


def create_secondary_button(parent, text: str, command, width=100, height=32, icon: str = None):
    """Return a styled secondary / outline button with optional graphic icon."""
    kwargs = {
        "text": text,
        "width": width,
        "height": height,
        "corner_radius": 6,
        "font": ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
        "fg_color": "transparent",
        "hover_color": COLOR_BTN_SEC_HOV,
        "border_width": 1,
        "border_color": COLOR_BORDER,
        "text_color": COLOR_TEXT_SEC,
        "command": command,
    }
    if icon:
        kwargs["image"] = get_icon(icon, size=(16, 16), color=COLOR_TEXT_SEC)
        if text:
            kwargs["compound"] = "left"
    return ctk.CTkButton(parent, **kwargs)


def create_status_badge(parent, text="Ready", row=0, pack_side=None, padx=None, pady=None):
    """Create a dot + label status indicator."""
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    if pack_side is not None:
        px = padx if padx is not None else 0
        py = pady if pady is not None else 0
        frame.pack(side=pack_side, padx=px, pady=py)
    else:
        px = padx if padx is not None else 16
        py = pady if pady is not None else (0, 8)
        frame.grid(row=row, column=0, sticky="w", padx=px, pady=py)

    dot = ctk.CTkLabel(
        frame, text=ICON_DOT,
        font=ctk.CTkFont(size=10), text_color=COLOR_TEXT_DIM,
    )
    dot.pack(side="left", padx=(0, 6))

    label = ctk.CTkLabel(
        frame, text=text,
        font=ctk.CTkFont(family=FONT_FAMILY, size=12),
        text_color=COLOR_TEXT_DIM,
    )
    label.pack(side="left")

    return frame, dot, label


def update_status(dot_label, text_label, text: str, state: str = "ready"):
    """Update a status badge. state: ready | processing | success | warning | error"""
    colors = {
        "ready":      COLOR_TEXT_DIM,
        "processing": COLOR_ACCENT,
        "success":    COLOR_SUCCESS,
        "warning":    COLOR_WARNING,
        "error":      COLOR_ERROR,
    }
    c = colors.get(state, COLOR_TEXT_DIM)
    dot_label.configure(text_color=c)
    text_label.configure(text=text, text_color=c)


def create_nav_button(parent, text: str, icon: str, command, row: int):
    """Create a sidebar navigation button."""
    btn = ctk.CTkButton(
        parent, text=f"  {icon}   {text}", height=42, corner_radius=8,
        anchor="w", fg_color="transparent",
        hover_color=COLOR_NAV_HOVER,
        text_color=COLOR_TEXT_SEC,
        font=ctk.CTkFont(family=FONT_FAMILY, size=14),
        command=command,
    )
    btn.grid(row=row, column=0, sticky="ew", padx=14, pady=2)
    return btn


def set_nav_active(btn, is_active: bool):
    """Highlight or un-highlight a nav button."""
    if is_active:
        btn.configure(
            fg_color=COLOR_NAV_ACTIVE,
            text_color=COLOR_TEXT,
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
        )
    else:
        btn.configure(
            fg_color="transparent",
            text_color=COLOR_TEXT_SEC,
            font=ctk.CTkFont(family=FONT_FAMILY, size=14),
        )


def create_collapsible_nav_item(parent, text: str, icon: str, on_select, on_toggle, row: int):
    """
    Creates a top-level nav item with an integrated expand/collapse chevron button.
    Returns: (frame, main_button, chevron_button)
    """
    frame = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=8)
    frame.grid(row=row, column=0, sticky="ew", padx=14, pady=2)
    frame.grid_columnconfigure(0, weight=1)

    btn = ctk.CTkButton(
        frame, text=f"  {icon}   {text}", height=42, corner_radius=8,
        anchor="w", fg_color="transparent",
        hover_color=COLOR_NAV_HOVER,
        text_color=COLOR_TEXT_SEC,
        font=ctk.CTkFont(family=FONT_FAMILY, size=14),
        command=on_select,
    )
    btn.grid(row=0, column=0, sticky="ew")

    chevron = ctk.CTkButton(
        frame, text="▾", width=34, height=42, corner_radius=8,
        fg_color="transparent", hover_color=COLOR_NAV_HOVER,
        text_color=COLOR_TEXT_DIM,
        font=ctk.CTkFont(family=FONT_FAMILY, size=13),
        command=on_toggle,
    )
    chevron.grid(row=0, column=1, sticky="e", padx=(2, 0))

    return frame, btn, chevron


def create_sub_nav_button(parent, text: str, icon: str, command, row: int):
    """
    Creates an indented sub-navigation button for child items.
    """
    btn = ctk.CTkButton(
        parent, text=f"   {icon}   {text}", height=36, corner_radius=6,
        anchor="w", fg_color="transparent",
        hover_color=COLOR_NAV_HOVER,
        text_color=COLOR_TEXT_SEC,
        font=ctk.CTkFont(family=FONT_FAMILY, size=13),
        command=command,
    )
    btn.grid(row=row, column=0, sticky="ew", padx=(28, 10), pady=1)
    return btn


def set_sub_nav_active(btn, is_active: bool):
    """Highlight or un-highlight a sub-nav button."""
    if is_active:
        btn.configure(
            fg_color=COLOR_NAV_ACTIVE,
            text_color=COLOR_TEXT,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
        )
    else:
        btn.configure(
            fg_color="transparent",
            text_color=COLOR_TEXT_SEC,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
        )



def create_step_card(parent, step_num: int, title: str, helper: str,
                     string_var, row: int, extra_buttons=None):
    """Compact step card to prevent scrolling."""
    card = ctk.CTkFrame(
        parent, corner_radius=8, fg_color=COLOR_CARD,
        border_width=1, border_color=COLOR_BORDER,
    )
    card.grid(row=row, column=0, sticky="ew", pady=(0, 6))
    card.grid_columnconfigure(0, weight=1)

    # Top Row: Badge, Title, Helper Text
    top_frame = ctk.CTkFrame(card, fg_color="transparent")
    top_frame.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 4))
    
    step_badge = ctk.CTkFrame(top_frame, width=24, height=24, corner_radius=12, fg_color=COLOR_ACCENT)
    step_badge.pack(side="left", padx=(0, 10))
    step_badge.pack_propagate(False)
    ctk.CTkLabel(
        step_badge, text=str(step_num),
        font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"), text_color=COLOR_TEXT,
    ).place(relx=0.5, rely=0.5, anchor="center")

    ctk.CTkLabel(
        top_frame, text=title,
        font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"), text_color=COLOR_TEXT,
    ).pack(side="left", padx=(0, 8))

    ctk.CTkLabel(
        top_frame, text=f"— {helper}",
        font=ctk.CTkFont(family=FONT_FAMILY, size=12), text_color=COLOR_TEXT_DIM,
    ).pack(side="left")

    # Bottom Row: Entry, Browse, Action Buttons
    bot_frame = ctk.CTkFrame(card, fg_color="transparent")
    bot_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
    bot_frame.grid_columnconfigure(0, weight=1)

    entry = ctk.CTkEntry(
        bot_frame, textvariable=string_var,
        placeholder_text="No file selected...",
        height=32, font=ctk.CTkFont(family=FONT_FAMILY, size=12),
        fg_color=COLOR_INPUT_BG, border_color=COLOR_BORDER, border_width=1, corner_radius=6,
        text_color=COLOR_TEXT, placeholder_text_color=COLOR_TEXT_DIM,
    )
    entry.grid(row=0, column=0, sticky="ew", padx=(34, 8)) # indent 34 to align with title

    col_idx = 1
    browse_btn = ctk.CTkButton(
        bot_frame, text="Browse", width=80, height=32, corner_radius=6,
        font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
        fg_color=COLOR_BTN_SEC, hover_color=COLOR_BTN_SEC_HOV, text_color=COLOR_TEXT,
        command=lambda: _browse_file(string_var),
    )
    browse_btn.grid(row=0, column=col_idx, padx=(0, 4))
    col_idx += 1

    if extra_buttons:
        for btn_text, btn_cmd, btn_style in extra_buttons:
            fg = COLOR_ACCENT if btn_style == "primary" else "transparent"
            hv = COLOR_ACCENT_HOVER if btn_style == "primary" else COLOR_BTN_SEC_HOV
            bw = 0 if btn_style == "primary" else 1
            tc = COLOR_TEXT if btn_style == "primary" else COLOR_TEXT_SEC
            
            b = ctk.CTkButton(
                bot_frame, text=btn_text, width=80, height=32,
                corner_radius=6, border_width=bw, border_color=COLOR_BORDER,
                font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
                fg_color=fg, hover_color=hv, text_color=tc,
                command=btn_cmd,
            )
            b.grid(row=0, column=col_idx, padx=(4, 0))
            col_idx += 1

    return card, entry


def _browse_file(string_var):
    """Open a file dialog and set the StringVar."""
    path = filedialog.askopenfilename(
        filetypes=[("Supported files (*.xlsx, *.xls, *.csv)", "*.xlsx *.xls *.csv"),
                   ("Excel files", "*.xlsx *.xls"),
                   ("CSV files", "*.csv"),
                   ("All files", "*.*")]
    )
    if path:
        string_var.set(path)


def create_multi_upload_row(parent, file_list: list, title: str,
                            placeholder: str = "No files selected...",
                            row: int = 0, on_change=None):
    """
    Create a multi-file upload row allowing single or multiple file selection.
    Displays file count and names, with Add/Browse and Clear buttons.
    """
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.grid(row=row, column=0, sticky="ew", padx=16, pady=(0, 12))
    frame.grid_columnconfigure(0, weight=1)

    lbl_title = ctk.CTkLabel(
        frame, text=title,
        font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
        text_color=COLOR_TEXT_DIM
    )
    lbl_title.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))

    info_var = ctk.StringVar(value=placeholder)

    entry = ctk.CTkEntry(
        frame, textvariable=info_var, state="readonly",
        height=32, font=ctk.CTkFont(family=FONT_FAMILY, size=12),
        fg_color=COLOR_INPUT_BG, border_color=COLOR_BORDER,
        border_width=1, corner_radius=6,
        text_color=COLOR_TEXT,
    )
    entry.grid(row=1, column=0, sticky="ew", padx=(0, 8))

    def _refresh():
        if not file_list:
            info_var.set(placeholder)
        elif len(file_list) == 1:
            info_var.set(Path(file_list[0]).name)
        else:
            names = ", ".join(Path(f).name for f in file_list[:2])
            suffix = f" (+{len(file_list)-2} more)" if len(file_list) > 2 else ""
            info_var.set(f"{len(file_list)} files: {names}{suffix}")
        if on_change:
            on_change()

    def _browse():
        paths = filedialog.askopenfilenames(
            filetypes=[("Supported files (*.xlsx, *.xls, *.csv)", "*.xlsx *.xls *.csv"),
                       ("Excel files", "*.xlsx *.xls"),
                       ("CSV files", "*.csv"),
                       ("All files", "*.*")]
        )
        if paths:
            for p in paths:
                if p not in file_list:
                    file_list.append(p)
            _refresh()

    def _clear():
        file_list.clear()
        _refresh()

    btn_browse = ctk.CTkButton(
        frame, text="Browse...", width=90, height=32, corner_radius=6,
        font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
        fg_color=COLOR_BTN_SEC, hover_color=COLOR_BTN_SEC_HOV,
        text_color=COLOR_TEXT,
        command=_browse,
    )
    btn_browse.grid(row=1, column=1, padx=(0, 6))

    btn_clear = ctk.CTkButton(
        frame, text="Clear", width=60, height=32, corner_radius=6,
        font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
        fg_color="transparent", hover_color=COLOR_BTN_SEC_HOV,
        border_width=1, border_color=COLOR_BORDER,
        text_color=COLOR_TEXT_SEC,
        command=_clear,
    )
    btn_clear.grid(row=1, column=2)

    return frame, entry, btn_browse, btn_clear, _refresh


def create_kpi_metric_card(parent, title: str, accent_color: str = COLOR_ACCENT):
    """Create a modern KPI display card with title, large value, and secondary subtitle."""
    card = ctk.CTkFrame(
        parent, corner_radius=10, fg_color=COLOR_CARD,
        border_width=1, border_color=COLOR_BORDER
    )
    card.grid_columnconfigure(0, weight=1)

    lbl_title = ctk.CTkLabel(
        card, text=title,
        font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
        text_color=COLOR_TEXT_SEC, anchor="w"
    )
    lbl_title.grid(row=0, column=0, sticky="w", padx=16, pady=(14, 4))

    lbl_val = ctk.CTkLabel(
        card, text="--",
        font=ctk.CTkFont(family=FONT_FAMILY, size=22, weight="bold"),
        text_color=COLOR_TEXT, anchor="w"
    )
    lbl_val.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 2))

    lbl_sub = ctk.CTkLabel(
        card, text="--",
        font=ctk.CTkFont(family=FONT_FAMILY, size=11),
        text_color=COLOR_TEXT_DIM, anchor="w"
    )
    lbl_sub.grid(row=2, column=0, sticky="w", padx=16, pady=(0, 14))

    return card, lbl_val, lbl_sub


def create_tooltip(widget, text: str, delay_ms: int = 300):
    """
    Attach an accessible hover tooltip to any Tkinter / CustomTkinter widget.
    Shows after delay_ms and hides on leave or click.
    """
    import tkinter as tk
    tooltip_window = None
    timer_id = None

    def show_tip():
        nonlocal tooltip_window
        if tooltip_window or not widget.winfo_exists():
            return
        try:
            x = widget.winfo_rootx() + widget.winfo_width() + 6
            y = widget.winfo_rooty() + max(0, (widget.winfo_height() - 24) // 2)
            tip = tk.Toplevel(widget)
            tip.wm_overrideredirect(True)
            tip.wm_geometry(f"+{x}+{y}")
            tip.attributes("-topmost", True)
            lbl = tk.Label(
                tip,
                text=text,
                justify="left",
                background="#1E293B",
                foreground="#F8FAFC",
                relief="solid",
                borderwidth=1,
                font=(FONT_FAMILY, 9),
                padx=8,
                pady=4,
            )
            lbl.pack()
            tooltip_window = tip
        except Exception:
            tooltip_window = None

    def on_enter(event=None):
        nonlocal timer_id
        cancel_timer()
        timer_id = widget.after(delay_ms, show_tip)

    def cancel_timer():
        nonlocal timer_id
        if timer_id:
            try:
                widget.after_cancel(timer_id)
            except Exception:
                pass
            timer_id = None

    def on_leave(event=None):
        nonlocal tooltip_window
        cancel_timer()
        if tooltip_window:
            try:
                tooltip_window.destroy()
            except Exception:
                pass
            tooltip_window = None

    widget.bind("<Enter>", on_enter, add="+")
    widget.bind("<Leave>", on_leave, add="+")
    widget.bind("<ButtonPress>", on_leave, add="+")
    return on_leave


# ════════════════════════════════════════════════════════════════
#  Searchable Filter Dropdown Component
# ════════════════════════════════════════════════════════════════

class SearchableDropdown(ctk.CTkFrame):
    """
    Searchable, vertically-scrollable floating dropdown selection panel.
    Replaces CTkComboBox with an accessible, keyboard-friendly search panel
    anchored to a compact filter button.
    """
    _active_dropdown = None

    def __init__(
        self,
        master,
        values=None,
        command=None,
        width=150,
        height=28,
        placeholder="Select...",
        initial_value=None,
        max_visible_rows=7,
        **kwargs
    ):
        super().__init__(master, fg_color="transparent", width=width, height=height, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._values = list(values) if values else []
        self._command = command
        self._placeholder = placeholder
        self._current_value = initial_value if initial_value is not None else (self._values[0] if self._values else placeholder)
        self._max_visible_rows = max_visible_rows
        self._state = "normal"
        self._popup = None
        self._filtered_values = []
        self._outside_bind_id = None

        # Anchor button matching single-row filter bar style
        display_text = self._format_display_text(self._current_value)
        self._btn = ctk.CTkButton(
            self,
            text=display_text,
            height=height,
            fg_color=COLOR_INPUT_BG,
            hover_color=COLOR_NAV_HOVER,
            border_color=COLOR_BORDER,
            border_width=1,
            corner_radius=6,
            text_color=COLOR_TEXT,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            anchor="w",
            command=self.toggle_dropdown,
        )
        self._btn.grid(row=0, column=0, sticky="nsew")

    def _format_display_text(self, val: str) -> str:
        s = str(val) if val else self._placeholder
        if len(s) > 28:
            return s[:25] + "… ▾"
        return f"{s} ▾"

    def get(self) -> str:
        return self._current_value

    def set(self, value: str):
        self._current_value = str(value)
        if hasattr(self, "_btn"):
            self._btn.configure(text=self._format_display_text(self._current_value))

    def configure(self, require_redraw=False, **kwargs):
        if "values" in kwargs:
            self._values = list(kwargs.pop("values"))
        if "command" in kwargs:
            self._command = kwargs.pop("command")
        if "state" in kwargs:
            self._state = kwargs.pop("state")
            if self._state == "disabled":
                self._btn.configure(state="disabled", text_color=COLOR_TEXT_DIM)
                self.close_dropdown()
            else:
                self._btn.configure(state="normal", text_color=COLOR_TEXT)
        if "placeholder" in kwargs:
            self._placeholder = kwargs.pop("placeholder")
        super().configure(**kwargs)

    def cget(self, attribute_name: str):
        if attribute_name == "values":
            return self._values
        if attribute_name == "state":
            return self._state
        return super().cget(attribute_name)

    def toggle_dropdown(self):
        if self._state == "disabled":
            return
        if self._popup and self._popup.winfo_exists():
            self.close_dropdown()
        else:
            self.open_dropdown()

    def open_dropdown(self):
        if SearchableDropdown._active_dropdown and SearchableDropdown._active_dropdown != self:
            try:
                SearchableDropdown._active_dropdown.close_dropdown()
            except Exception:
                pass
        SearchableDropdown._active_dropdown = self

        top_win = self.winfo_toplevel()
        if hasattr(top_win, "close_floating_nav"):
            try:
                top_win.close_floating_nav()
            except Exception:
                pass

        self.update_idletasks()
        rx = self._btn.winfo_rootx()
        ry = self._btn.winfo_rooty()
        bw = self._btn.winfo_width()
        bh = self._btn.winfo_height()

        scale = 1.0
        if hasattr(self, "_get_widget_scaling"):
            try:
                scale = self._get_widget_scaling()
            except Exception:
                scale = 1.0

        popup_w = max(bw, int(220 * scale))
        n_items = len(self._values)
        row_h = int(24 * scale)
        header_h = int(44 * scale)
        content_h = min(max(n_items, 1), self._max_visible_rows) * row_h + header_h
        popup_h = min(max(content_h, int(80 * scale)), int(250 * scale))

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()

        if ry + bh + popup_h + 10 > sh:
            popup_y = max(10, ry - popup_h - 2)
        else:
            popup_y = ry + bh + 2

        if rx + popup_w > sw - 10:
            popup_x = max(10, sw - popup_w - 10)
        else:
            popup_x = rx

        top = tk.Toplevel(self)
        top.overrideredirect(True)
        top.geometry(f"{popup_w}x{popup_h}+{popup_x}+{popup_y}")
        top.attributes("-topmost", True)
        self._popup = top

        outer = ctk.CTkFrame(top, fg_color=COLOR_CARD, border_width=1, border_color=COLOR_BORDER, corner_radius=8)
        outer.pack(fill="both", expand=True)
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(1, weight=1)

        self._search_var = tk.StringVar()
        self._entry = ctk.CTkEntry(
            outer,
            textvariable=self._search_var,
            placeholder_text="Search...",
            height=28,
            fg_color=COLOR_INPUT_BG,
            border_color=COLOR_BORDER,
            text_color=COLOR_TEXT,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
        )
        self._entry.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 4))
        self._entry.focus_set()

        body_frame = ctk.CTkFrame(outer, fg_color="transparent")
        body_frame.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
        body_frame.grid_columnconfigure(0, weight=1)
        body_frame.grid_rowconfigure(0, weight=1)

        self._scrollbar = ctk.CTkScrollbar(body_frame, width=12)
        self._listbox = tk.Listbox(
            body_frame,
            bg=COLOR_CARD,
            fg=COLOR_TEXT,
            selectbackground=COLOR_NAV_ACTIVE,
            selectforeground=COLOR_TEXT,
            relief="flat",
            highlightthickness=0,
            borderwidth=0,
            font=(FONT_FAMILY, 10),
            activestyle="none",
            yscrollcommand=self._scrollbar.set,
        )
        self._scrollbar.configure(command=self._listbox.yview)
        self._listbox.grid(row=0, column=0, sticky="nsew")

        self._empty_lbl = ctk.CTkLabel(
            body_frame,
            text="No matching options",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=COLOR_TEXT_DIM,
        )

        def _on_mousewheel(e):
            self._listbox.yview_scroll(int(-1 * (e.delta / 120)), "units")
            return "break"

        self._listbox.bind("<MouseWheel>", _on_mousewheel)

        self._filter_options()
        self._search_var.trace_add("write", lambda *args: self._filter_options())

        self._entry.bind("<Down>", self._on_entry_down)
        self._entry.bind("<Up>", self._on_entry_up)
        self._entry.bind("<Return>", self._on_entry_return)
        self._entry.bind("<Escape>", lambda e: self.close_dropdown())
        self._listbox.bind("<Return>", self._on_entry_return)
        self._listbox.bind("<Escape>", lambda e: self.close_dropdown())
        self._listbox.bind("<ButtonRelease-1>", self._on_listbox_click)

        self._outside_bind_id = top_win.bind("<ButtonPress-1>", self._on_outside_click, add="+")

    def _filter_options(self):
        if not self._popup or not self._popup.winfo_exists():
            return
        query = self._search_var.get().strip().lower()
        if query:
            self._filtered_values = [v for v in self._values if query in v.lower()]
        else:
            self._filtered_values = list(self._values)

        self._listbox.delete(0, tk.END)

        if not self._filtered_values:
            self._listbox.grid_remove()
            self._scrollbar.grid_remove()
            self._empty_lbl.grid(row=0, column=0, sticky="nsew", pady=10)
        else:
            self._empty_lbl.grid_remove()
            self._listbox.grid(row=0, column=0, sticky="nsew")
            if len(self._filtered_values) > self._max_visible_rows:
                self._scrollbar.grid(row=0, column=1, sticky="ns", padx=(2, 0))
            else:
                self._scrollbar.grid_remove()

            display_items = []
            sel_idx = None
            for idx, val in enumerate(self._filtered_values):
                is_selected = (val == self._current_value)
                marker = "✓  " if is_selected else "   "
                display_items.append(f"{marker}{val}")
                if is_selected:
                    sel_idx = idx

            if display_items:
                self._listbox.insert(tk.END, *display_items)

            if sel_idx is not None:
                self._listbox.selection_set(sel_idx)
                self._listbox.see(sel_idx)
            elif self._filtered_values:
                self._listbox.selection_set(0)

    def _on_entry_down(self, event):
        if not self._filtered_values:
            return "break"
        cur = self._listbox.curselection()
        nxt = (cur[0] + 1) if cur else 0
        if nxt < len(self._filtered_values):
            self._listbox.selection_clear(0, tk.END)
            self._listbox.selection_set(nxt)
            self._listbox.see(nxt)
        return "break"

    def _on_entry_up(self, event):
        if not self._filtered_values:
            return "break"
        cur = self._listbox.curselection()
        prev = (cur[0] - 1) if cur else 0
        if prev >= 0:
            self._listbox.selection_clear(0, tk.END)
            self._listbox.selection_set(prev)
            self._listbox.see(prev)
        return "break"

    def _on_entry_return(self, event):
        if not self._filtered_values:
            return "break"
        cur = self._listbox.curselection()
        idx = cur[0] if cur else 0
        if 0 <= idx < len(self._filtered_values):
            selected_val = self._filtered_values[idx]
            self.set(selected_val)
            self.close_dropdown()
            if self._command:
                self._command(selected_val)
        return "break"

    def _on_listbox_click(self, event):
        cur = self._listbox.curselection()
        if cur:
            idx = cur[0]
            if 0 <= idx < len(self._filtered_values):
                selected_val = self._filtered_values[idx]
                self.set(selected_val)
                self.close_dropdown()
                if self._command:
                    self._command(selected_val)

    def _on_outside_click(self, event):
        if not self._popup or not self._popup.winfo_exists():
            return
        px = self._popup.winfo_rootx()
        py = self._popup.winfo_rooty()
        pw = self._popup.winfo_width()
        ph = self._popup.winfo_height()

        bx = self._btn.winfo_rootx()
        by = self._btn.winfo_rooty()
        bw = self._btn.winfo_width()
        bh = self._btn.winfo_height()

        click_x = event.x_root
        click_y = event.y_root

        inside_popup = (px <= click_x <= px + pw) and (py <= click_y <= py + ph)
        inside_btn = (bx <= click_x <= bx + bw) and (by <= click_y <= by + bh)

        if not inside_popup and not inside_btn:
            self.close_dropdown()

    def close_dropdown(self):
        if SearchableDropdown._active_dropdown == self:
            SearchableDropdown._active_dropdown = None
        if self._outside_bind_id:
            try:
                top_win = self.winfo_toplevel()
                top_win.unbind("<ButtonPress-1>", self._outside_bind_id)
            except Exception:
                pass
            self._outside_bind_id = None
        if self._popup:
            try:
                if self._popup.winfo_exists():
                    self._popup.destroy()
            except Exception:
                pass
            self._popup = None

    def destroy(self):
        self.close_dropdown()
        super().destroy()


# ════════════════════════════════════════════════════════════════
#  Best-In-Class Animated Canvas Loading Components
# ════════════════════════════════════════════════════════════════

class GlowingModernSpinner(ctk.CTkFrame):
    """
    High-performance, 60fps orbital neon glow spinner rendered on Tkinter Canvas.
    Features:
    - Outer rotating multi-color gradient arc with harmonic breathing extent
    - Fading ghost trails creating cinematic motion blur
    - Inner counter-rotating dashed planetary orbit
    - Pulsing breathing core with dynamic halo glow
    - Zero CPU usage when stopped/hidden
    """

    def __init__(
        self,
        parent,
        size: int = 60,
        bg_color: str = COLOR_CARD,
        accent_color: str = "#06B6D4",
        secondary_color: str = "#3B82F6",
        tertiary_color: str = "#8B5CF6",
        **kwargs,
    ):
        super().__init__(parent, fg_color="transparent", corner_radius=0, **kwargs)
        self._size = size
        self._bg_color = bg_color
        self._accent = accent_color
        self._secondary = secondary_color
        self._tertiary = tertiary_color

        self._angle = 0.0
        self._phase = 0.0
        self._is_animating = False
        self._timer_id = None

        self._canvas = tk.Canvas(
            self,
            width=size,
            height=size,
            bg=bg_color,
            highlightthickness=0,
            bd=0,
        )
        self._canvas.pack(expand=True, fill="both")
        self._draw_frame()

    def set_bg_color(self, bg: str):
        self._bg_color = bg
        self._canvas.configure(bg=bg)
        if not self._is_animating:
            self._draw_frame()

    def start(self):
        if not self._is_animating:
            self._is_animating = True
            self._tick()

    def stop(self):
        self._is_animating = False
        if self._timer_id:
            try:
                self.after_cancel(self._timer_id)
            except Exception:
                pass
            self._timer_id = None
        self._draw_frame()

    def _tick(self):
        if not self._is_animating:
            return
        if not self.winfo_exists():
            return

        self._angle = (self._angle + 5.5) % 360.0
        self._phase = (self._phase + 0.08) % (2.0 * math.pi)

        self._draw_frame()

        try:
            self._timer_id = self.after(16, self._tick)
        except Exception:
            self._is_animating = False

    def _draw_frame(self):
        try:
            if not self._canvas.winfo_exists():
                return
            self._canvas.delete("all")
            w = self._size
            h = self._size
            cx = w / 2.0
            cy = h / 2.0

            # 1. Outer Track (Deep Slate)
            r_outer = (w / 2.0) - 6.0
            if r_outer > 4:
                self._canvas.create_oval(
                    cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer,
                    outline="#1E293B", width=3,
                )

                # 2. Outer Gradient Arc Trail
                # Main dynamic sweep arc
                sweep = 120.0 + 40.0 * math.sin(self._phase)
                self._canvas.create_arc(
                    cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer,
                    start=self._angle, extent=sweep,
                    outline=self._accent, width=3, style="arc",
                )
                # Trailing ghost arcs for glow depth
                self._canvas.create_arc(
                    cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer,
                    start=(self._angle + sweep - 35), extent=35,
                    outline=self._secondary, width=4, style="arc",
                )
                self._canvas.create_arc(
                    cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer,
                    start=(self._angle + sweep - 15), extent=15,
                    outline="#FFFFFF", width=4, style="arc",
                )

            # 3. Inner Counter-Rotating Dashed Orbit
            r_inner = r_outer * 0.65
            if r_inner > 3:
                inner_angle = (-self._angle * 1.6) % 360.0
                self._canvas.create_arc(
                    cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner,
                    start=inner_angle, extent=80,
                    outline=self._tertiary, width=2, style="arc",
                )
                self._canvas.create_arc(
                    cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner,
                    start=inner_angle + 180, extent=60,
                    outline=self._secondary, width=2, style="arc",
                )

            # 4. Central Breathing Pulsing Core
            base_r = max(2.0, r_outer * 0.22)
            pulse_r = base_r + 1.8 * math.sin(self._phase * 1.5)
            # Outer halo
            self._canvas.create_oval(
                cx - (pulse_r + 2.5), cy - (pulse_r + 2.5),
                cx + (pulse_r + 2.5), cy + (pulse_r + 2.5),
                outline=self._accent, width=1,
            )
            # Glowing core
            self._canvas.create_oval(
                cx - pulse_r, cy - pulse_r, cx + pulse_r, cy + pulse_r,
                fill=self._accent, outline="#FFFFFF", width=1,
            )
        except Exception:
            pass

    def destroy(self):
        self.stop()
        super().destroy()


class GlowingLaserBeam(ctk.CTkFrame):
    """
    Sleek horizontal glowing laser beam that sweeps smoothly across the width.
    Ideal for top-of-card or under-toolbar active calculation feedback.
    """

    def __init__(
        self,
        parent,
        height: int = 3,
        bg_color: str = COLOR_CARD,
        beam_color: str = "#06B6D4",
        head_color: str = "#FFFFFF",
        **kwargs,
    ):
        super().__init__(parent, fg_color="transparent", height=height, corner_radius=0, **kwargs)
        self._h = height
        self._bg = bg_color
        self._beam_col = beam_color
        self._head_col = head_color
        self._is_animating = False
        self._pos = 0.0
        self._dir = 1.0
        self._timer_id = None

        self._canvas = tk.Canvas(
            self,
            height=height,
            bg=bg_color,
            highlightthickness=0,
            bd=0,
        )
        self._canvas.pack(expand=True, fill="both")
        self.bind("<Configure>", lambda e: self._draw_beam())

    def start(self):
        if not self._is_animating:
            self._is_animating = True
            self._tick()

    def stop(self):
        self._is_animating = False
        if self._timer_id:
            try:
                self.after_cancel(self._timer_id)
            except Exception:
                pass
            self._timer_id = None
        self._draw_beam(clear=True)

    def _tick(self):
        if not self._is_animating or not self.winfo_exists():
            return

        speed = 0.022
        self._pos += speed * self._dir
        if self._pos >= 1.0:
            self._pos = 1.0
            self._dir = -1.0
        elif self._pos <= 0.0:
            self._pos = 0.0
            self._dir = 1.0

        self._draw_beam()

        try:
            self._timer_id = self.after(16, self._tick)
        except Exception:
            self._is_animating = False

    def _draw_beam(self, clear: bool = False):
        try:
            if not self._canvas.winfo_exists():
                return
            self._canvas.delete("all")
            if clear:
                return

            w = self.winfo_width()
            if w <= 10:
                w = self._canvas.winfo_width()
            if w <= 10:
                w = 400

            h = self._h
            # Background track
            self._canvas.create_rectangle(0, 0, w, h, fill="#131B2E", outline="")

            # Beam position
            beam_w = max(60.0, w * 0.32)
            cx = self._pos * w
            x0 = max(0.0, cx - (beam_w / 2.0))
            x1 = min(float(w), cx + (beam_w / 2.0))

            # Outer glow
            self._canvas.create_rectangle(x0, 0, x1, h, fill=self._beam_col, outline="")
            # Hot core center
            core_w = beam_w * 0.4
            cx0 = max(0.0, cx - (core_w / 2.0))
            cx1 = min(float(w), cx + (core_w / 2.0))
            self._canvas.create_rectangle(cx0, 0, cx1, h, fill=self._head_col, outline="")
        except Exception:
            pass

    def destroy(self):
        self.stop()
        super().destroy()


class ModernLoadingOverlay(ctk.CTkFrame):
    """
    Modern glassmorphic loading card container.
    Features the GlowingModernSpinner, animated pulse title, and scope detail.
    """

    def __init__(
        self,
        parent,
        title: str = "Crunching Workforce Intelligence...",
        subtitle: str = "Recalculating 10 KPIs, additive composition & daily trends across active scope",
        spinner_size: int = 56,
        **kwargs,
    ):
        super().__init__(
            parent,
            fg_color=COLOR_CARD,
            border_width=1,
            border_color="#222F43",
            corner_radius=10,
            **kwargs,
        )
        self.grid_columnconfigure(0, weight=1)

        self._inner = ctk.CTkFrame(self, fg_color="transparent")
        self._inner.grid(row=0, column=0, padx=24, pady=28)
        self._inner.grid_columnconfigure(0, weight=1)

        self.spinner = GlowingModernSpinner(
            self._inner,
            size=spinner_size,
            bg_color=COLOR_CARD,
            accent_color="#06B6D4",
            secondary_color="#3B82F6",
        )
        self.spinner.pack(pady=(0, 14))

        self.lbl_title = ctk.CTkLabel(
            self._inner,
            text=f"⚡ {title}",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=COLOR_TEXT,
        )
        self.lbl_title.pack(pady=(0, 4))

        self.lbl_subtitle = ctk.CTkLabel(
            self._inner,
            text=subtitle,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=COLOR_TEXT_SEC,
            wraplength=520,
        )
        self.lbl_subtitle.pack(pady=(0, 6))

        self._dots_count = 0
        self._base_title = title
        self._pulse_timer = None

    def set_status(self, title: str, subtitle: Optional[str] = None):
        self._base_title = title
        self.lbl_title.configure(text=f"⚡ {title}")
        if subtitle:
            self.lbl_subtitle.configure(text=subtitle)

    def start(self):
        self.spinner.start()
        self._pulse_dots()

    def stop(self):
        self.spinner.stop()
        if self._pulse_timer:
            try:
                self.after_cancel(self._pulse_timer)
            except Exception:
                pass
            self._pulse_timer = None

    def _pulse_dots(self):
        if not self.winfo_exists():
            return
        self._dots_count = (self._dots_count + 1) % 4
        dots = "." * self._dots_count
        self.lbl_title.configure(text=f"⚡ {self._base_title}{dots}")
        try:
            self._pulse_timer = self.after(350, self._pulse_dots)
        except Exception:
            pass

    def destroy(self):
        self.stop()
        super().destroy()



