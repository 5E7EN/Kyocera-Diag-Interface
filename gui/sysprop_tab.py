"""System properties tab: read/write Android properties and predtm keys."""

import tkinter as tk
from tkinter import ttk, messagebox
import threading

from . import styles
from core import device, diag


class SysPropTab(ttk.Frame):
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

        ttk.Label(header, text="System Properties", style="Heading.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            header,
            text="Read and write Android system properties or predtm keys via diag. Requires diag mode.",
            foreground=styles.FG_DIM,
            justify="left",
        ).pack(anchor="w", fill="x", pady=(4, 0))

        # Read card
        read_card = ttk.LabelFrame(self, text=" Read Property ", padding=16)
        read_card.pack(fill="x", padx=16, pady=8)

        read_row = ttk.Frame(read_card)
        read_row.pack(fill="x")

        ttk.Label(read_row, text="Key:").pack(side="left", padx=(0, 8))
        self.read_key_entry = ttk.Entry(read_row, width=40)
        self.read_key_entry.pack(side="left", padx=(0, 8), fill="x", expand=True)
        self.read_key_entry.bind("<Return>", lambda _: self._do_read())

        self.read_btn = ttk.Button(
            read_row, text="Read", style="Accent.TButton", command=self._do_read
        )
        self.read_btn.pack(side="left")

        self.read_result = ttk.Label(read_card, text="", font=styles.FONT_MONO)
        self.read_result.pack(anchor="w", pady=(8, 0))

        # Write card
        write_card = ttk.LabelFrame(self, text=" Write Property ", padding=16)
        write_card.pack(fill="x", padx=16, pady=8)

        wkey_row = ttk.Frame(write_card)
        wkey_row.pack(fill="x", pady=(0, 4))

        ttk.Label(wkey_row, text="Key:").pack(side="left", padx=(0, 8))
        self.write_key_entry = ttk.Entry(wkey_row, width=40)
        self.write_key_entry.pack(side="left", padx=(0, 8), fill="x", expand=True)

        wval_row = ttk.Frame(write_card)
        wval_row.pack(fill="x", pady=(0, 8))

        ttk.Label(wval_row, text="Value:").pack(side="left", padx=(0, 8))
        self.write_val_entry = ttk.Entry(wval_row, width=40)
        self.write_val_entry.pack(side="left", padx=(0, 8), fill="x", expand=True)

        wbtn_row = ttk.Frame(write_card)
        wbtn_row.pack(fill="x")

        self.write_btn = ttk.Button(
            wbtn_row, text="Write", style="Accent.TButton", command=self._do_write
        )
        self.write_btn.pack(side="left")

        # Predtm reset card
        predtm_card = ttk.LabelFrame(self, text=" Predtm Store ", padding=16)
        predtm_card.pack(fill="x", padx=16, pady=8)

        ttk.Label(
            predtm_card,
            text="Stops lkspad, wipes /mnt/vendor/pstore, and restarts lkspad.",
            foreground=styles.FG_DIM,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        self.reset_predtm_btn = ttk.Button(
            predtm_card, text="Reset Predtm Store", command=self._do_reset_predtm
        )
        self.reset_predtm_btn.pack(anchor="w")

        # Log output
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

    def _require_diag(self) -> bool:
        if self.device_tab.current_mode != device.DeviceMode.DIAG:
            self._log("Device must be in Diag mode", "err")
            self._set_status("SysProp: Diag mode required")
            return False
        return True

    def _do_read(self):
        if not self._require_diag():
            return
        key = self.read_key_entry.get().strip()
        if not key:
            self._log("Enter a property key to read", "err")
            return

        self.read_btn.configure(state="disabled")
        self.read_result.configure(text="Reading...", foreground=styles.FG_DIM)
        self._set_status(f"Reading property: {key}")

        def _run():
            try:
                result = diag.get_sysprop(key)
                self.after(0, lambda: self._show_read(key, result))
            except ConnectionError as e:
                msg = str(e)
                self.after(0, lambda: self._read_error(msg))

        threading.Thread(target=_run, daemon=True).start()

    def _show_read(self, key: str, result: dict):
        self.read_btn.configure(state="normal")
        if result["ok"]:
            self.read_result.configure(text=result["value"], foreground=styles.FG)
            self._log(f"{key} = {result['value']}", "ok")
            self._set_status(f"Read property: {key}")
        else:
            self.read_result.configure(
                text="(not found or error)", foreground=styles.ERROR
            )
            self._log(
                f"Failed to read {key} (status={result.get('status', '?')})", "err"
            )
            self._set_status("Property read failed")

    def _read_error(self, msg: str):
        self.read_btn.configure(state="normal")
        self.read_result.configure(text="Error", foreground=styles.ERROR)
        self._log(f"Error: {msg}", "err")
        self._set_status("Property read failed")

    def _do_write(self):
        if not self._require_diag():
            return
        key = self.write_key_entry.get().strip()
        value = self.write_val_entry.get().strip()
        if not key:
            self._log("Enter a property key to write", "err")
            return

        if not messagebox.askyesno(
            "Confirm",
            f"Write property?\n\n  {key} = {value}\n\nContinue?",
            icon="warning",
        ):
            return

        self.write_btn.configure(state="disabled")
        self._set_status(f"Writing property: {key}")

        def _run():
            try:
                result = diag.set_sysprop(key, value)
                self.after(0, lambda: self._show_write(key, value, result))
            except ConnectionError as e:
                msg = str(e)
                self.after(0, lambda: self._write_error(msg))

        threading.Thread(target=_run, daemon=True).start()

    def _show_write(self, key: str, value: str, result: dict):
        self.write_btn.configure(state="normal")
        if result["ok"]:
            self._log(f"Wrote {key} = {value}", "ok")
            self._set_status(f"Wrote property: {key}")
        else:
            self._log(
                f"Failed to write {key} (status={result.get('status', '?')})", "err"
            )
            self._set_status("Property write failed")

    def _write_error(self, msg: str):
        self.write_btn.configure(state="normal")
        self._log(f"Error: {msg}", "err")
        self._set_status("Property write failed")

    def _do_reset_predtm(self):
        if not self._require_diag():
            return

        if not messagebox.askyesno(
            "Confirm",
            "This will stop lkspad, wipe /mnt/vendor/pstore, and restart lkspad.\n\nContinue?",
            icon="warning",
        ):
            return

        self.reset_predtm_btn.configure(state="disabled")
        self._set_status("Resetting predtm store...")

        def _run():
            try:
                result = diag.reset_predtm()
                self.after(0, lambda: self._show_reset(result))
            except ConnectionError as e:
                msg = str(e)
                self.after(0, lambda: self._reset_error(msg))

        threading.Thread(target=_run, daemon=True).start()

    def _show_reset(self, result: dict):
        self.reset_predtm_btn.configure(state="normal")
        if result["ok"]:
            self._log("Predtm store reset successfully", "ok")
            self._set_status("Predtm store reset")
        else:
            self._log(
                f"Predtm reset failed (status={result.get('status', '?')})", "err"
            )
            self._set_status("Predtm reset failed")

    def _reset_error(self, msg: str):
        self.reset_predtm_btn.configure(state="normal")
        self._log(f"Error: {msg}", "err")
        self._set_status("Predtm reset failed")
