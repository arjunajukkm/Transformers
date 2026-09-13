"""
ui_components.py
────────────────
Reusable UI building blocks for the Transformers desktop app.
Provides factory functions for cards, upload rows, buttons, status
badges, and navigation items — all styled to the enterprise design system.
"""

import customtkinter as ctk
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

# ════════════════════════════════════════════════════════════════
#  Icon constants (Unicode)
# ════════════════════════════════════════════════════════════════

ICON_HOME       = "⬢"
ICON_KRA        = "◈"
ICON_ABSENT     = "◉"
ICON_ATTENDANCE = "◧"
ICON_SETTINGS   = "⚙"
ICON_UPLOAD     = "⬆"
ICON_CHECK      = "✓"
ICON_CROSS      = "✕"
ICON_DOT        = "●"
ICON_FILE       = "📄"


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
    """Create a dashboard module card with icon, title, desc, badge, button."""
    card = ctk.CTkFrame(
        parent, corner_radius=12, fg_color=COLOR_CARD,
        border_width=1, border_color=COLOR_BORDER,
    )
    card.grid(row=row, column=col, sticky="nsew", padx=8, pady=8)
    card.grid_columnconfigure(0, weight=1)

    # Icon + Title row
    top = ctk.CTkFrame(card, fg_color="transparent")
    top.grid(row=0, column=0, sticky="ew", padx=24, pady=(24, 0))

    ctk.CTkLabel(
        top, text=icon,
        font=ctk.CTkFont(size=22), text_color=COLOR_ACCENT,
    ).pack(side="left", padx=(0, 10))

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
        frame, text=btn_text, width=90, height=32, corner_radius=6,
        font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
        fg_color=COLOR_BTN_SEC, hover_color=COLOR_BTN_SEC_HOV,
        text_color=COLOR_TEXT,
        command=lambda: _browse_file(string_var),
    )
    btn.grid(row=1, column=1)
    return frame, entry, btn


def create_primary_button(parent, text: str, command, width=110, height=32):
    """Return a styled primary action button."""
    return ctk.CTkButton(
        parent, text=text, width=width, height=height,
        corner_radius=6,
        font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
        fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
        text_color=COLOR_TEXT, command=command,
    )


def create_secondary_button(parent, text: str, command, width=100, height=32):
    """Return a styled secondary / outline button."""
    return ctk.CTkButton(
        parent, text=text, width=width, height=height,
        corner_radius=6,
        font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
        fg_color="transparent", hover_color=COLOR_BTN_SEC_HOV,
        border_width=1, border_color=COLOR_BORDER,
        text_color=COLOR_TEXT_SEC, command=command,
    )


def create_status_badge(parent, text="Ready", row=0):
    """Create a dot + label status indicator."""
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.grid(row=row, column=0, sticky="w", padx=16, pady=(0, 8))

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
        filetypes=[("Excel files", "*.xlsx *.xls")]
    )
    if path:
        string_var.set(path)
