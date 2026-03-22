"""Main application window with tabbed interface."""

import tkinter as tk
from tkinter import ttk

from . import styles
from core import device
from .device_tab import DeviceTab
from .shell_tab import ShellTab
from .selinux_tab import SELinuxTab
from .file_tab import FileTab
from .credits_dialog import show_credits


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Kyocera Diag Interface")
        self.minsize(750, 550)
        import sys

        if sys.platform == "win32":
            self.state("zoomed")
        else:
            self.attributes("-zoomed", True)

        styles.apply_theme(self)
        self._build_ui()

    def _build_ui(self):
        # Top bar: title + credits button
        top = ttk.Frame(self)
        top.pack(fill="x", padx=16, pady=(12, 0))

        ttk.Label(top, text="Kyocera Diag Interface", style="Title.TLabel").pack(
            side="left"
        )

        credits_btn = ttk.Button(
            top, text="Info / Credits", command=lambda: show_credits(self)
        )
        credits_btn.pack(side="right")

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=16, pady=(10, 0))

        # Status bar - pack first so it claims bottom space before notebook expands
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(
            self,
            textvariable=self.status_var,
            style="Status.TLabel",
            anchor="w",
            padding=(16, 6),
        )
        status_bar.pack(fill="x", side="bottom")

        # Tabbed notebook
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=8)

        # Create tabs - device tab is shared state
        self.device_tab = DeviceTab(self.notebook)
        self.shell_tab = ShellTab(self.notebook, self.device_tab)
        self.selinux_tab = SELinuxTab(self.notebook, self.device_tab)
        self.file_tab = FileTab(self.notebook, self.device_tab)

        self.notebook.add(self.device_tab, text="  Device  ")
        self.notebook.add(self.shell_tab, text="  Shell  ")
        self.notebook.add(self.selinux_tab, text="  SELinux  ")
        self.notebook.add(self.file_tab, text="  File Pull  ")

        # Share status bar with tabs
        self.device_tab.set_status_var(self.status_var)
        self.shell_tab.set_status_var(self.status_var)
        self.selinux_tab.set_status_var(self.status_var)
        self.file_tab.set_status_var(self.status_var)

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # Initial device detection
        self.after(200, self.device_tab.refresh_status)

    def _on_tab_changed(self, event=None):
        selected = self.notebook.select()
        if selected == str(self.selinux_tab):
            if self.device_tab.current_mode == device.DeviceMode.DIAG:
                self.selinux_tab._probe_selinux()
