"""SELinux status probing and modification tab."""

import tkinter as tk
from tkinter import ttk, messagebox
import threading

from . import styles
from core import device, diag


class SELinuxTab(ttk.Frame):
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

        ttk.Label(header, text="SELinux Control", style="Heading.TLabel").pack(
            anchor="w"
        )
        se_desc = ttk.Label(
            header,
            text="Probe and modify the SELinux enforcement state via factory cmdline flags. "
            "Requires diag mode. Changes take effect after reboot.",
            foreground=styles.FG_DIM,
            justify="left",
        )
        se_desc.pack(anchor="w", fill="x", pady=(4, 0))

        # Current status card
        status_card = ttk.LabelFrame(self, text=" Current Status ", padding=16)
        status_card.pack(fill="x", padx=16, pady=8)

        self.selinux_status = ttk.Label(
            status_card, text="Unknown", font=styles.FONT_HEADING
        )
        self.selinux_status.pack(anchor="w")

        self.selinux_detail = ttk.Label(status_card, text="", foreground=styles.FG_DIM)
        self.selinux_detail.pack(anchor="w", pady=(4, 0))

        self.probe_btn = ttk.Button(
            status_card,
            text="Check Status",
            style="Accent.TButton",
            command=self._probe_selinux,
        )
        self.probe_btn.pack(anchor="w", pady=(12, 0))

        # Actions card
        action_card = ttk.LabelFrame(self, text=" Actions", padding=16)
        action_card.pack(fill="x", padx=16, pady=8)

        btn_row = ttk.Frame(action_card)
        btn_row.pack(fill="x")

        self.permissive_btn = ttk.Button(
            btn_row,
            text="Set Permissive",
            style="Accent.TButton",
            command=self._set_permissive,
        )
        self.permissive_btn.pack(side="left", padx=(0, 8))

        self.restore_btn = ttk.Button(
            btn_row, text="Restore Enforcing", command=self._restore_enforcing
        )
        self.restore_btn.pack(side="left", padx=(0, 8))

        # Log output
        log_frame = ttk.LabelFrame(self, text=" Log ", padding=8)
        log_frame.pack(fill="both", expand=True, padx=16, pady=8)

        text_container = ttk.Frame(log_frame)
        text_container.pack(fill="both", expand=True)

        self.log_text = styles.make_text_widget(
            text_container, state="disabled", height=8
        )
        self.log_text.pack(side="left", fill="both", expand=True)

        self.log_text.tag_configure("ok", foreground=styles.SUCCESS)
        self.log_text.tag_configure("err", foreground=styles.ERROR)
        self.log_text.tag_configure("warn", foreground=styles.WARNING)

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
            self._log("Device must be in Diag mode for SELinux operations", "err")
            self._set_status("SELinux: Diag mode required")
            return False
        return True

    def _probe_selinux(self):
        if not self._require_diag():
            return

        self.probe_btn.configure(state="disabled")

        def _do_probe():
            try:
                results = diag.probe()
                # Also get runtime getenforce
                getenforce = ""
                try:
                    getenforce = diag.exec_command("getenforce 2>&1")
                except Exception:
                    pass
                self.after(0, lambda: self._show_probe(results, getenforce))
            except ConnectionError as e:
                msg = str(e)
                self.after(0, lambda: self._probe_error(msg))

        threading.Thread(target=_do_probe, daemon=True).start()

    def _show_probe(self, results: dict, getenforce: str):
        self.probe_btn.configure(state="normal")

        fc = results.get("factory_cmdline", {})
        if not fc.get("ok"):
            self.selinux_status.configure(text="Error", foreground=styles.ERROR)
            self.selinux_detail.configure(text="Failed to read factory cmdline")
            self._log("Failed to read factory cmdline from DNAND", "err")
            return

        is_permissive = fc.get("kcpermissive", False)
        getenforce = getenforce.strip() if getenforce else ""

        if is_permissive:
            self.selinux_status.configure(text="Permissive", foreground=styles.SUCCESS)
            self._log(f"kcpermissive flag: SET", "ok")
        else:
            self.selinux_status.configure(
                text="Enforcing (default)", foreground=styles.WARNING
            )
            self._log(f"kcpermissive flag: NOT set", "warn")

        detail_parts = []
        if getenforce:
            detail_parts.append(f"Runtime: {getenforce}")
            self._log(f"Runtime: {getenforce}")
        detail_parts.append(f"kcfactory={'Y' if fc.get('kcfactory') else 'N'}")
        detail_parts.append(f"kcmount={'Y' if fc.get('kcmount') else 'N'}")
        detail_parts.append(f"raw flags={fc.get('flags', 0):#010x}")

        self.selinux_detail.configure(text=" | ".join(detail_parts))

    def _probe_error(self, msg: str):
        self.probe_btn.configure(state="normal")
        self.selinux_status.configure(text="Error", foreground=styles.ERROR)
        self.selinux_detail.configure(text=msg)
        self._log(f"Error: {msg}", "err")

    def _set_permissive(self):
        if not self._require_diag():
            return

        if not messagebox.askyesno(
            "Confirm",
            'SELinux will be set to "permissive" on next reboot.\n\n' "Continue?",
            icon="warning",
        ):
            return

        self._do_flag_write("permissive", diag.FACTORY_PERMISSIVE)

    def _restore_enforcing(self):
        if not self._require_diag():
            return

        if not messagebox.askyesno(
            "Confirm",
            'SELinux will be restored to "enforcing" on next reboot.\n\n' "Continue?",
        ):
            return

        self._do_flag_write("enforcing", diag.FACTORY_CLEAR)

    def _do_flag_write(self, label: str, flags: int):
        self.permissive_btn.configure(state="disabled")
        self.restore_btn.configure(state="disabled")
        self._set_status(f"Writing SELinux {label} flag...")
        self._log(f"Writing {label} flag ({flags:#04x}) to DNAND ID 9...")

        def _write():
            try:
                ok = diag.set_factory_flag(flags)
                self.after(0, lambda: self._on_write_done(ok, label))
            except ConnectionError as e:
                msg = str(e)
                self.after(0, lambda: self._on_write_error(msg))

        threading.Thread(target=_write, daemon=True).start()

    def _on_write_done(self, ok: bool, label: str):
        self.permissive_btn.configure(state="normal")
        self.restore_btn.configure(state="normal")

        if ok:
            self._log(f"Successfully wrote {label} flag.", "ok")
            self._log("Reboot the device for changes to take effect.", "warn")
            self._set_status(f"SELinux {label} flag written - reboot required")
        else:
            self._log(f"Failed to write {label} flag to DNAND", "err")
            self._set_status(f"SELinux write failed")

    def _on_write_error(self, msg: str):
        self.permissive_btn.configure(state="normal")
        self.restore_btn.configure(state="normal")
        self._log(f"Error: {msg}", "err")
        self._set_status("SELinux write failed")

