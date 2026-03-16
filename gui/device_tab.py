"""Device tab: mode detection, switching, and probe."""

import tkinter as tk
from tkinter import ttk, messagebox
import threading

from . import styles
from core import device, diag


class DeviceTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._status_var = None
        self.current_mode = device.DeviceMode.DISCONNECTED
        self.device_model = "device"
        self._build_ui()

    def set_status_var(self, var: tk.StringVar):
        self._status_var = var

    def _set_status(self, msg: str):
        if self._status_var:
            self._status_var.set(msg)

    def _build_ui(self):
        # -- Info banner --
        info_frame = ttk.LabelFrame(self, text=" Getting Started ", padding=12)
        info_frame.pack(fill="x", padx=16, pady=(16, 8))

        info_text = (
            "1. Enable USB Debugging on the device (Settings > Developer Options > USB Debugging)\n"
            "2. Connect device via USB and authorize the debugging prompt\n"
            "3. Click 'Detect Device' to identify the current mode\n"
            "4. Use 'Switch to Diag Mode' to transition: ADB -> CDROM -> Diag"
        )
        ttk.Label(info_frame, text=info_text, foreground=styles.FG_SECONDARY,
                  wraplength=700, justify="left").pack(anchor="w")

        ttk.Label(info_frame,
                  text="Note: Diag switching has only been tested on E4610 and E4810 devices.",
                  foreground=styles.WARNING, justify="left").pack(anchor="w", pady=(8, 0))

        # -- Device status --
        status_frame = ttk.LabelFrame(self, text=" Device Status ", padding=16)
        status_frame.pack(fill="x", padx=16, pady=8)

        row = ttk.Frame(status_frame)
        row.pack(fill="x", pady=(0, 8))

        ttk.Label(row, text="Current Mode:", style="Heading.TLabel").pack(side="left")
        self.mode_label = ttk.Label(row, text="Unknown", font=styles.FONT_HEADING)
        self.mode_label.pack(side="left", padx=(12, 0))

        self.mode_detail = ttk.Label(status_frame, text="", style="Dim.TLabel")
        self.mode_detail.pack(anchor="w")

        # Buttons
        btn_frame = ttk.Frame(status_frame)
        btn_frame.pack(fill="x", pady=(12, 0))

        self.detect_btn = ttk.Button(btn_frame, text="Detect Device",
                                     style="Accent.TButton", command=self.refresh_status)
        self.detect_btn.pack(side="left", padx=(0, 8))

        self.switch_btn = ttk.Button(btn_frame, text="Switch to Diag Mode",
                                     command=self._switch_to_diag)
        self.switch_btn.pack(side="left", padx=(0, 8))

        self.adb_btn = ttk.Button(btn_frame, text="Switch to ADB Mode (Regular)",
                                  command=self._switch_to_adb)
        self.adb_btn.pack(side="left", padx=(0, 8))

        self.reboot_btn = ttk.Button(btn_frame, text="Reboot Device",
                                     style="Success.TButton", command=self._reboot_device)
        self.reboot_btn.pack(side="left", padx=(0, 8))

        # -- Probe section --
        probe_frame = ttk.LabelFrame(self, text=" Diag Status", padding=16)
        probe_frame.pack(fill="both", expand=True, padx=16, pady=8)

        self.probe_btn = ttk.Button(probe_frame, text="Refresh",
                                    style="Accent.TButton", command=self._run_probe)
        self.probe_btn.pack(anchor="w", pady=(0, 8))

        text_frame = ttk.Frame(probe_frame)
        text_frame.pack(fill="both", expand=True)

        self.probe_text = styles.make_text_widget(text_frame, state="disabled", height=10)
        self.probe_text.pack(side="left", fill="both", expand=True)

        sb = styles.make_scrollbar(text_frame, self.probe_text)
        sb.pack(side="right", fill="y")

    def refresh_status(self):
        """Detect device mode in background thread."""
        self.detect_btn.configure(state="disabled")
        self._set_status("Detecting device...")

        def _detect():
            mode = device.detect_mode()
            model = "device"
            if mode == device.DeviceMode.ADB:
                model = device.get_device_model_adb()
            elif mode == device.DeviceMode.DIAG:
                model = device.get_device_model_diag()
            self.after(0, lambda: self._update_mode(mode, model))

        threading.Thread(target=_detect, daemon=True).start()

    def _update_mode(self, mode: device.DeviceMode, model: str = "device"):
        self.current_mode = mode
        self.device_model = model
        self.detect_btn.configure(state="normal")

        mode_info = {
            device.DeviceMode.DISCONNECTED: ("Disconnected", styles.ERROR,
                                              "No Kyocera device detected. Check USB connection."),
            device.DeviceMode.ADB: ("ADB Mode", styles.SUCCESS,
                                     f"Model: {model} | VID:PID 0482:0A9B | ADB authorized"),
            device.DeviceMode.ADB_UNAUTHORIZED: ("ADB Unauthorized", styles.ERROR,
                                                  "Device connected but ADB not authorized. "
                                                  "Accept the USB debugging prompt on the device."),
            device.DeviceMode.CDROM: ("CDROM Mode", styles.WARNING,
                                       "VID:PID 0482:0A8F | Ready for diag init SCSI command"),
            device.DeviceMode.DIAG: ("Diag Mode", styles.ACCENT,
                                      f"Model: {model} | VID:PID 0482:0A9D | Full diag access | ADB unavailable in this mode"),
        }

        label, color, detail = mode_info[mode]
        self.mode_label.configure(text=label, foreground=color)
        self.mode_detail.configure(text=detail)

        # Enable/disable switch buttons
        can_switch_diag = mode in (device.DeviceMode.ADB, device.DeviceMode.CDROM)
        self.switch_btn.configure(state="normal" if can_switch_diag else "disabled")

        can_switch_adb = mode in (device.DeviceMode.CDROM, device.DeviceMode.DIAG)
        self.adb_btn.configure(state="normal" if can_switch_adb else "disabled")

        # Reboot available in any connected mode
        can_reboot = mode != device.DeviceMode.DISCONNECTED
        self.reboot_btn.configure(state="normal" if can_reboot else "disabled")

        # Enable/disable probe button, auto-probe if entering diag mode
        self.probe_btn.configure(state="normal" if mode == device.DeviceMode.DIAG else "disabled")
        if mode == device.DeviceMode.DIAG:
            self.after(100, self._run_probe)

        self._set_status(f"Device: {label}")

    def _switch_to_diag(self):
        self.switch_btn.configure(state="disabled")
        self.detect_btn.configure(state="disabled")
        self._set_status("Switching to diag mode...")

        def _do_switch():
            ok, msg = device.switch_to_diag()
            mode = device.detect_mode()
            model = self.device_model
            self.after(0, lambda: self._on_switch_done(ok, msg, mode, model))

        threading.Thread(target=_do_switch, daemon=True).start()

    def _switch_to_adb(self):
        self.adb_btn.configure(state="disabled")
        self.detect_btn.configure(state="disabled")
        self._set_status("Switching to ADB mode...")

        def _do_switch():
            ok, msg = device.switch_to_adb(self.current_mode)
            mode = device.detect_mode()
            model = "device"
            if mode == device.DeviceMode.ADB:
                model = device.get_device_model_adb()
            self.after(0, lambda: self._on_switch_done(ok, msg, mode, model))

        threading.Thread(target=_do_switch, daemon=True).start()

    def _reboot_device(self):
        if not messagebox.askyesno("Confirm", "Reboot the device?"):
            return
        self.reboot_btn.configure(state="disabled")
        self._set_status("Rebooting device...")

        def _do_reboot():
            import subprocess
            try:
                subprocess.run(["adb", "reboot"], timeout=10,
                               capture_output=True)
                self.after(0, lambda: self._set_status("Reboot command sent"))
            except Exception as e:
                self.after(0, lambda: self._set_status(f"Reboot failed: {e}"))
            self.after(0, lambda: self.reboot_btn.configure(state="normal"))

        threading.Thread(target=_do_reboot, daemon=True).start()

    def _on_switch_done(self, ok, msg, mode, model):
        self._update_mode(mode, model)
        color = styles.SUCCESS if ok else styles.ERROR
        self._set_status(msg)
        # Flash the detail label with result
        self.mode_detail.configure(text=msg, foreground=color)

    def _run_probe(self):
        self.probe_btn.configure(state="disabled")
        self._set_status("Running probe...")

        def _do_probe():
            try:
                results = diag.probe()
                self.after(0, lambda: self._show_probe(results))
            except ConnectionError as e:
                self.after(0, lambda: self._show_probe_error(str(e)))

        threading.Thread(target=_do_probe, daemon=True).start()

    def _show_probe(self, results: dict):
        self.probe_btn.configure(state="normal")
        self.probe_text.configure(state="normal")
        self.probe_text.delete("1.0", "end")

        # Build label->value rows, then pad labels to align values
        rows = []

        r = results["build_id"]
        trunc = " [TRUNCATED]" if r.get("truncated") else ""
        rows.append(("Build ID", r["value"] + trunc if r["ok"] else "FAILED"))

        r = results["product"]
        trunc = " [TRUNCATED]" if r.get("truncated") else ""
        rows.append(("Product Model", r["value"] + trunc if r["ok"] else "FAILED"))

        r = results["reset_status"]
        if r["ok"]:
            rows.append(("DNAND Reset", f"status={r['dnand_status']}  data={r['reset_data']:#010x}"))
        else:
            rows.append(("DNAND Reset", "FAILED"))

        r = results["factory_cmdline"]
        if r["ok"]:
            val = (f"kcfactory={'Y' if r['kcfactory'] else 'N'}  "
                   f"kcmount={'Y' if r['kcmount'] else 'N'}  "
                   f"kcpermissive={'Y' if r['kcpermissive'] else 'N'}  "
                   f"(raw={r['flags']:#010x})")
            rows.append(("Factory Cmdline", val))
        else:
            rows.append(("Factory Cmdline", "FAILED"))

        # Use tab to align values; set tab stop wide enough for longest label
        import tkinter.font as tkfont
        font_obj = tkfont.Font(font=self.probe_text.cget("font"))
        longest = max(font_obj.measure(label + ":  ") for label, _ in rows)
        self.probe_text.configure(tabs=(longest,))

        for label, value in rows:
            self.probe_text.insert("end", f"{label}:\t{value}\n")

        self.probe_text.insert("end", "\n")
        if results["all_ok"]:
            self.probe_text.insert("end", "All reads OK\n")
        else:
            self.probe_text.insert("end", "[!] One or more reads failed - do not attempt DNAND write\n")

        self.probe_text.configure(state="disabled")
        self._set_status("Probe complete")

    def _show_probe_error(self, msg: str):
        self.probe_btn.configure(state="normal")
        self.probe_text.configure(state="normal")
        self.probe_text.delete("1.0", "end")
        self.probe_text.insert("end", f"[-] Error: {msg}\n")
        self.probe_text.configure(state="disabled")
        self._set_status("Probe failed")
