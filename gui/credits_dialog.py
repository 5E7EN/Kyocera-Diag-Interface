"""Info/credits dialog."""

import tkinter as tk
from tkinter import ttk

from . import styles
from version import __version__


def show_credits(parent: tk.Tk):
    """Show the info/credits dialog."""
    dialog = tk.Toplevel(parent)
    dialog.title("Info / Credits")
    dialog.geometry("520x420")
    dialog.resizable(False, False)
    dialog.configure(bg=styles.BG_DARK)
    dialog.transient(parent)
    dialog.grab_set()

    # Center on parent
    dialog.update_idletasks()
    x = parent.winfo_x() + (parent.winfo_width() - 520) // 2
    y = parent.winfo_y() + (parent.winfo_height() - 420) // 2
    dialog.geometry(f"+{x}+{y}")

    frame = ttk.Frame(dialog, padding=24)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="Kyocera Diag Interface", style="Title.TLabel").pack(
        anchor="w"
    )
    ttk.Label(frame, text=f"v{__version__}", foreground=styles.FG_DIM).pack(anchor="w")
    ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=(8, 16))

    credits_text = (
        "GUI: @ClaudeAI and @5E7EN\n\n"
        "Scripts & tooling: @5E7EN and @LeoBuskin\n\n"
        "Special thanks to @LeoBuskin for findings that helped\n"
        "identify the mechanisms implemented in this project.\n\n---\n\n"
        "Methods adapted from official, publicly-available\n"
        "Kyocera/Qualcomm tooling and device analysis.\n"
        "More features coming soon™"
    )

    text_label = ttk.Label(
        frame,
        text=credits_text,
        foreground=styles.FG_SECONDARY,
        justify="left",
        wraplength=470,
    )
    text_label.pack(anchor="w", fill="x")

    link_url = "https://forums.jtechforums.org/t/can-you-unlock-and-root-kyocera-e4810/4227/114"
    link = ttk.Label(
        frame, text="JTechForums", foreground=styles.ACCENT, cursor="hand2"
    )
    link.pack(anchor="w", pady=(12, 0))
    link.bind("<Button-1>", lambda e: __import__("webbrowser").open(link_url))

    ttk.Button(
        frame, text="Close", style="Accent.TButton", command=dialog.destroy
    ).pack(anchor="e", pady=(20, 0))
