"""Dark theme styling for the application."""

import tkinter as tk
from tkinter import ttk

# Color palette
BG_DARK = "#1a1a2e"
BG_MID = "#16213e"
BG_LIGHT = "#0f3460"
BG_ENTRY = "#1c2541"
FG_PRIMARY = "#e0e0e0"
FG_SECONDARY = "#a0a0b8"
FG_DIM = "#6c6c80"
ACCENT = "#00b4d8"
ACCENT_HOVER = "#48cae4"
SUCCESS = "#06d6a0"
WARNING = "#ffd166"
ERROR = "#ef476f"
BORDER = "#2a2a4a"

# Font definitions
FONT_FAMILY = "Segoe UI"
FONT_MONO = "Consolas"
FONT_FALLBACK = "TkDefaultFont"
FONT_MONO_FALLBACK = "TkFixedFont"

FONT_NORMAL = (FONT_FAMILY, 10)
FONT_SMALL = (FONT_FAMILY, 9)
FONT_HEADING = (FONT_FAMILY, 12, "bold")
FONT_TITLE = (FONT_FAMILY, 16, "bold")
FONT_TERMINAL = (FONT_MONO, 10)
FONT_TERMINAL_SMALL = (FONT_MONO, 9)


def _check_font(root, preferred, fallback):
    """Return preferred font family if available, else fallback."""
    import tkinter.font as tkfont

    available = tkfont.families()
    return preferred if preferred in available else fallback


def apply_theme(root: tk.Tk):
    """Apply dark theme to the root window and all ttk widgets."""
    # Check font availability
    family = _check_font(root, FONT_FAMILY, FONT_FALLBACK)
    mono = _check_font(root, FONT_MONO, FONT_MONO_FALLBACK)

    # Update module-level font tuples
    global FONT_NORMAL, FONT_SMALL, FONT_HEADING, FONT_TITLE, FONT_TERMINAL, FONT_TERMINAL_SMALL
    FONT_NORMAL = (family, 10)
    FONT_SMALL = (family, 9)
    FONT_HEADING = (family, 12, "bold")
    FONT_TITLE = (family, 16, "bold")
    FONT_TERMINAL = (mono, 10)
    FONT_TERMINAL_SMALL = (mono, 9)

    root.configure(bg=BG_DARK)

    style = ttk.Style(root)
    style.theme_use("clam")

    # General
    style.configure(
        ".",
        background=BG_DARK,
        foreground=FG_PRIMARY,
        font=FONT_NORMAL,
        borderwidth=0,
        relief="flat",
    )

    # Frame
    style.configure("TFrame", background=BG_DARK)
    style.configure("Card.TFrame", background=BG_MID, relief="solid", borderwidth=1)

    # Label
    style.configure(
        "TLabel", background=BG_DARK, foreground=FG_PRIMARY, font=FONT_NORMAL
    )
    style.configure("Heading.TLabel", font=FONT_HEADING, foreground=ACCENT)
    style.configure("Title.TLabel", font=FONT_TITLE, foreground=FG_PRIMARY)
    style.configure("Dim.TLabel", foreground=FG_DIM, font=FONT_SMALL)
    style.configure("Success.TLabel", foreground=SUCCESS)
    style.configure("Warning.TLabel", foreground=WARNING)
    style.configure("Error.TLabel", foreground=ERROR)
    style.configure(
        "Status.TLabel", background=BG_MID, foreground=FG_SECONDARY, font=FONT_SMALL
    )

    # Button
    style.configure(
        "TButton",
        background=BG_LIGHT,
        foreground=FG_PRIMARY,
        font=FONT_NORMAL,
        padding=(16, 8),
        relief="flat",
    )
    style.map(
        "TButton",
        background=[("active", ACCENT), ("disabled", BG_MID)],
        foreground=[("disabled", FG_DIM)],
    )

    style.configure(
        "Accent.TButton",
        background=ACCENT,
        foreground="#ffffff",
        font=FONT_NORMAL,
        padding=(16, 8),
    )
    style.map(
        "Accent.TButton",
        background=[("active", ACCENT_HOVER), ("disabled", BG_MID)],
        foreground=[("disabled", FG_DIM)],
    )

    style.configure(
        "Danger.TButton",
        background=ERROR,
        foreground="#ffffff",
        font=FONT_NORMAL,
        padding=(16, 8),
    )
    style.map(
        "Danger.TButton", background=[("active", "#ff6b8a"), ("disabled", BG_MID)]
    )

    style.configure(
        "Success.TButton",
        background=SUCCESS,
        foreground="#1a1a2e",
        font=FONT_NORMAL,
        padding=(16, 8),
    )
    style.map(
        "Success.TButton",
        background=[("active", "#2ee8b7"), ("disabled", BG_MID)],
        foreground=[("disabled", FG_DIM)],
    )

    # Notebook (tabs)
    style.configure("TNotebook", background=BG_DARK, borderwidth=0)
    style.configure(
        "TNotebook.Tab",
        background=BG_MID,
        foreground=FG_SECONDARY,
        font=FONT_NORMAL,
        padding=(20, 10),
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", BG_LIGHT)],
        foreground=[("selected", ACCENT)],
        padding=[("selected", (20, 10))],
    )

    # Entry
    style.configure(
        "TEntry",
        fieldbackground=BG_ENTRY,
        foreground=FG_PRIMARY,
        insertcolor=FG_PRIMARY,
        borderwidth=1,
        relief="solid",
        padding=(8, 6),
    )

    # Separator
    style.configure("TSeparator", background=BORDER)

    # Progressbar
    style.configure(
        "TProgressbar",
        background=ACCENT,
        troughcolor=BG_MID,
        borderwidth=0,
        thickness=6,
    )

    # LabelFrame
    style.configure(
        "TLabelframe",
        background=BG_DARK,
        foreground=ACCENT,
        borderwidth=1,
        relief="solid",
    )
    style.configure(
        "TLabelframe.Label", background=BG_DARK, foreground=ACCENT, font=FONT_NORMAL
    )


class Tooltip:
    """Show a tooltip popup when hovering over a widget."""

    def __init__(self, widget: tk.Widget, text: str):
        self._widget = widget
        self._text = text
        self._tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, event=None):
        if self._tip:
            return
        x = self._widget.winfo_rootx() + self._widget.winfo_width() // 2
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4

        self._tip = tk.Toplevel(self._widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")

        lbl = tk.Label(
            self._tip,
            text=self._text,
            bg="#2a2a4a",
            fg=FG_PRIMARY,
            font=FONT_SMALL,
            relief="flat",
            padx=10,
            pady=6,
            wraplength=320,
            justify="left",
        )
        lbl.pack()

    def _hide(self, event=None):
        if self._tip:
            self._tip.destroy()
            self._tip = None


def make_text_widget(parent, **kwargs) -> tk.Text:
    """Create a styled Text widget matching the dark theme."""
    defaults = dict(
        bg=BG_ENTRY,
        fg=FG_PRIMARY,
        insertbackground=FG_PRIMARY,
        selectbackground=ACCENT,
        selectforeground="#ffffff",
        font=FONT_TERMINAL,
        relief="flat",
        borderwidth=0,
        padx=8,
        pady=8,
        wrap="word",
    )
    defaults.update(kwargs)
    return tk.Text(parent, **defaults)


def make_scrollbar(parent, target, orient="vertical") -> ttk.Scrollbar:
    """Create and link a scrollbar to a text/canvas widget."""
    sb = ttk.Scrollbar(parent, orient=orient)
    if orient == "vertical":
        sb.configure(command=target.yview)
        target.configure(yscrollcommand=sb.set)
    else:
        sb.configure(command=target.xview)
        target.configure(xscrollcommand=sb.set)
    return sb
