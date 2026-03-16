"""File pull tab: download files from device via diag shell."""

import os
import tkinter as tk
from tkinter import ttk, filedialog
import threading

from . import styles
from core import device, diag


class FileTab(ttk.Frame):
    def __init__(self, parent, device_tab):
        super().__init__(parent)
        self.device_tab = device_tab
        self._status_var = None
        self._build_ui()

    def set_status_var(self, var: tk.StringVar):
        self._status_var = var

    def _set_status(self, msg: str):
        if self._status_var:
            self._status_var.set(msg)

    def _build_ui(self):
        # Header
        header = ttk.Frame(self, padding=(16, 16, 16, 8))
        header.pack(fill="x")

        ttk.Label(header, text="File Pull", style="Heading.TLabel").pack(anchor="w")
        file_desc = ttk.Label(
            header,
            text="Download files from the device using chunked base64 over the diag shell. "
            'Requires diag mode. Large files may take a while. Access level is same as "Shell" user.',
            foreground=styles.FG_DIM,
            justify="left",
        )
        file_desc.pack(anchor="w", fill="x", pady=(4, 0))

        # Path inputs
        paths_frame = ttk.LabelFrame(self, text=" Paths ", padding=16)
        paths_frame.pack(fill="x", padx=16, pady=8)

        # Remote path
        ttk.Label(paths_frame, text="Remote path (on device):").pack(anchor="w")
        self.remote_entry = tk.Entry(
            paths_frame,
            font=styles.FONT_TERMINAL,
            bg=styles.BG_ENTRY,
            fg=styles.FG_PRIMARY,
            insertbackground=styles.FG_PRIMARY,
            relief="flat",
        )
        self.remote_entry.pack(fill="x", ipady=6, pady=(4, 12))
        self.remote_entry.insert(0, "/vendor/bin/kdiag_common")

        # Local path
        ttk.Label(paths_frame, text="Save to local:").pack(anchor="w")
        local_row = ttk.Frame(paths_frame)
        local_row.pack(fill="x", pady=(4, 0))

        self.local_entry = tk.Entry(
            local_row,
            font=styles.FONT_TERMINAL,
            bg=styles.BG_ENTRY,
            fg=styles.FG_PRIMARY,
            insertbackground=styles.FG_PRIMARY,
            relief="flat",
        )
        self.local_entry.pack(side="left", fill="x", expand=True, ipady=6)
        # self.local_entry.insert(0, "")

        browse_btn = ttk.Button(local_row, text="Browse...", command=self._browse)
        browse_btn.pack(side="right", padx=(8, 0))

        # Progress
        progress_frame = ttk.Frame(self, padding=(16, 8))
        progress_frame.pack(fill="x")

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            progress_frame, variable=self.progress_var, maximum=100, mode="determinate"
        )
        self.progress_bar.pack(fill="x")

        self.progress_label = ttk.Label(progress_frame, text="", style="Dim.TLabel")
        self.progress_label.pack(anchor="w", pady=(4, 0))

        # Buttons
        btn_frame = ttk.Frame(self, padding=(16, 8))
        btn_frame.pack(fill="x")

        self.pull_btn = ttk.Button(
            btn_frame, text="Pull File", style="Accent.TButton", command=self._pull
        )
        self.pull_btn.pack(side="left")

        # Log
        log_frame = ttk.LabelFrame(self, text=" Log ", padding=8)
        log_frame.pack(fill="both", expand=True, padx=16, pady=8)

        text_container = ttk.Frame(log_frame)
        text_container.pack(fill="both", expand=True)

        self.log_text = styles.make_text_widget(
            text_container, state="disabled", height=6
        )
        self.log_text.pack(side="left", fill="both", expand=True)

        self.log_text.tag_configure("ok", foreground=styles.SUCCESS)
        self.log_text.tag_configure("err", foreground=styles.ERROR)

        sb = styles.make_scrollbar(text_container, self.log_text)
        sb.pack(side="right", fill="y")

    def _log(self, msg: str, tag: str = None):
        self.log_text.configure(state="normal")
        if tag:
            self.log_text.insert("end", msg + "\n", tag)
        else:
            self.log_text.insert("end", msg + "\n")
        self.log_text.configure(state="disabled")
        self.log_text.see("end")

    def _browse(self):
        path = filedialog.asksaveasfilename(title="Save file as")
        if path:
            self.local_entry.delete(0, "end")
            self.local_entry.insert(0, path)

    def _pull(self):
        if self.device_tab.current_mode != device.DeviceMode.DIAG:
            self._log("Device must be in Diag mode to pull files", "err")
            self._set_status("File pull: Diag mode required")
            return

        remote = self.remote_entry.get().strip()
        local = self.local_entry.get().strip()
        if not remote or not local:
            self._log("Both remote and local paths are required", "err")
            return

        self.pull_btn.configure(state="disabled")
        self.progress_var.set(0)
        self._log(f"Pulling {remote} -> {local}")
        self._set_status(f"Pulling {remote}...")

        def _progress_cb(offset, total):
            pct = (offset / total * 100) if total > 0 else 0
            self.after(0, lambda: self._update_progress(offset, total, pct))

        def _do_pull():
            try:
                ok = diag.pull_file(remote, local, progress_cb=_progress_cb)
                self.after(0, lambda: self._on_done(ok, remote, local))
            except Exception as e:
                msg = str(e)
                self.after(0, lambda: self._on_error(msg))

        threading.Thread(target=_do_pull, daemon=True).start()

    def _update_progress(self, offset: int, total: int, pct: float):
        self.progress_var.set(pct)
        self.progress_label.configure(text=f"{offset:,} / {total:,} bytes ({pct:.1f}%)")

    def _on_done(self, ok: bool, remote: str, local: str):
        self.pull_btn.configure(state="normal")
        if ok:
            self.progress_var.set(100)
            self._log(f"Successfully saved to {local}", "ok")
            self._set_status(f"File pull complete: {local}")
        else:
            self._log("File pull failed", "err")
            self._set_status("File pull failed")

    def _on_error(self, msg: str):
        self.pull_btn.configure(state="normal")
        self._log(f"Error: {msg}", "err")
        self._set_status("File pull failed")
