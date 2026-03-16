"""Interactive shell tab supporting both ADB and Diag modes."""

import tkinter as tk
from tkinter import ttk
import threading

from . import styles
from core import device, diag


class ShellTab(ttk.Frame):
    def __init__(self, parent, device_tab):
        super().__init__(parent)
        self.device_tab = device_tab
        self._status_var = None
        self._history = []
        self._history_idx = -1
        self._busy = False
        self._diag_user = "system"  # Updated on first command in diag mode
        self._diag_user_probed = False
        self._build_ui()

    def set_status_var(self, var: tk.StringVar):
        self._status_var = var

    def _set_status(self, msg: str):
        if self._status_var:
            self._status_var.set(msg)

    def _build_ui(self):
        # Info banner
        info_frame = ttk.Frame(self, padding=(16, 8))
        info_frame.pack(fill="x")

        ttk.Label(info_frame, text="Interactive Shell", style="Heading.TLabel").pack(anchor="w")
        desc_label = ttk.Label(info_frame,
                  text="Commands execute via ADB (in ADB mode) or Diag protocol (in Diag mode). "
                       "Each command runs independently - cd and other stateful commands do not persist between executions.",
                  foreground=styles.FG_DIM, justify="left")
        desc_label.pack(anchor="w", fill="x", pady=(4, 0))

        # Warning banner
        warn_frame = ttk.Frame(self)
        warn_frame.pack(fill="x", padx=16, pady=(4, 0))
        warn_frame.configure(style="TFrame")

        warn_label = ttk.Label(
            warn_frame,
            text=("DISCLAIMER: Unless your bootloader is unlocked, any edits to /system or other "
                  "verified partitions WILL BRICK YOUR DEVICE. "
                  "We take no responsibility for anything that happens to your device."),
            foreground=styles.ERROR, background="#2a0a0f",
            justify="left", padding=(10, 8),
        )
        warn_label.pack(fill="x")

        # Terminal output area
        term_frame = ttk.Frame(self)
        term_frame.pack(fill="both", expand=True, padx=16, pady=(4, 8))

        self.terminal = styles.make_text_widget(
            term_frame, state="disabled", wrap="word",
            bg="#0d1117", fg="#c9d1d9", font=styles.FONT_TERMINAL,
        )
        self.terminal.pack(side="left", fill="both", expand=True)

        # Configure text tags for coloring
        self.terminal.tag_configure("prompt", foreground=styles.ACCENT)
        self.terminal.tag_configure("error", foreground=styles.ERROR)
        self.terminal.tag_configure("info", foreground=styles.FG_DIM)
        self.terminal.tag_configure("success", foreground=styles.SUCCESS)

        sb = styles.make_scrollbar(term_frame, self.terminal)
        sb.pack(side="right", fill="y")

        # Input area
        input_frame = ttk.Frame(self, padding=(16, 0, 16, 12))
        input_frame.pack(fill="x")

        self.prompt_label = ttk.Label(input_frame, text="$ ", font=styles.FONT_TERMINAL,
                                       foreground=styles.ACCENT)
        self.prompt_label.pack(side="left")

        self.cmd_entry = tk.Entry(
            input_frame, font=styles.FONT_TERMINAL,
            bg="#0d1117", fg="#c9d1d9", insertbackground="#c9d1d9",
            relief="flat", borderwidth=0,
        )
        self.cmd_entry.pack(side="left", fill="x", expand=True, ipady=6)
        self.cmd_entry.bind("<Return>", self._on_enter)
        self.cmd_entry.bind("<Up>", self._history_up)
        self.cmd_entry.bind("<Down>", self._history_down)
        self.cmd_entry.focus_set()

        send_btn = ttk.Button(input_frame, text="Execute", style="Accent.TButton",
                              command=self._on_enter)
        send_btn.pack(side="right", padx=(8, 0))

        # Write initial message
        self._append_text("Type commands below. Use Up/Down arrows for history.\n\n", "info")

    def _get_prompt_string(self) -> str:
        """Build prompt based on current mode and access level."""
        mode = self.device_tab.current_mode
        model = self.device_tab.device_model or "device"

        if mode == device.DeviceMode.ADB:
            return f"{model}:/ $ "
        elif mode == device.DeviceMode.DIAG:
            user = self._diag_user
            suffix = "# " if user == "root" else "$ "
            return f"{user}@{model}:/ {suffix}"
        else:
            return "$ "

    def _update_prompt(self):
        self.prompt_label.configure(text=self._get_prompt_string())

    def _append_text(self, text: str, tag: str = None):
        self.terminal.configure(state="normal")
        if tag:
            self.terminal.insert("end", text, tag)
        else:
            self.terminal.insert("end", text)
        self.terminal.configure(state="disabled")
        self.terminal.see("end")

    def _on_enter(self, event=None):
        if self._busy:
            return

        cmd = self.cmd_entry.get().strip()
        if not cmd:
            return

        self.cmd_entry.delete(0, "end")
        self._history.append(cmd)
        self._history_idx = -1

        mode = self.device_tab.current_mode
        if mode == device.DeviceMode.DISCONNECTED:
            self._append_text(self._get_prompt_string(), "prompt")
            self._append_text(cmd + "\n")
            self._append_text("Error: No device connected. Detect device first.\n\n", "error")
            return

        if mode == device.DeviceMode.ADB_UNAUTHORIZED:
            self._append_text(self._get_prompt_string(), "prompt")
            self._append_text(cmd + "\n")
            self._append_text("Error: ADB not authorized. Accept the USB debugging prompt on the device.\n\n", "error")
            return

        if mode == device.DeviceMode.CDROM:
            self._append_text(self._get_prompt_string(), "prompt")
            self._append_text(cmd + "\n")
            self._append_text("Error: Device is in CDROM mode. Switch to Diag or ADB first.\n\n", "error")
            return

        self._busy = True
        self._set_status(f"Executing: {cmd}")
        self.cmd_entry.configure(state="disabled")

        # Append 2>&1 to capture stderr
        full_cmd = f"{cmd} 2>&1"

        def _exec():
            try:
                # Probe diag user on first use (before printing prompt)
                if mode == device.DeviceMode.DIAG and not self._diag_user_probed:
                    self._diag_user_probed = True
                    try:
                        id_out = diag.exec_command("id 2>&1")
                        if "uid=0(root)" in id_out:
                            self._diag_user = "root"
                        elif "uid=" in id_out:
                            start = id_out.index("(") + 1
                            end = id_out.index(")")
                            self._diag_user = id_out[start:end]
                    except Exception:
                        pass

                # Now print the prompt (with correct user after probe)
                self.after(0, lambda: self._print_prompt_and_cmd(cmd))

                if mode == device.DeviceMode.ADB:
                    output = device.adb_shell(full_cmd)
                else:  # DIAG
                    output = diag.exec_command(full_cmd)
                self.after(0, lambda: self._show_output(output))
            except Exception as e:
                self.after(0, lambda: self._show_output(f"Error: {e}", is_error=True))

        threading.Thread(target=_exec, daemon=True).start()

    def _print_prompt_and_cmd(self, cmd: str):
        self._update_prompt()
        self._append_text(self._get_prompt_string(), "prompt")
        self._append_text(cmd + "\n")

    def _show_output(self, output: str, is_error: bool = False):
        self._busy = False
        self.cmd_entry.configure(state="normal")
        self.cmd_entry.focus_set()

        if output:
            # Ensure trailing newline
            if not output.endswith("\n"):
                output += "\n"
            tag = "error" if is_error else None
            self._append_text(output, tag)
        self._append_text("\n")
        self._set_status("Ready")

    def _history_up(self, event=None):
        if not self._history:
            return "break"
        if self._history_idx == -1:
            self._history_idx = len(self._history) - 1
        elif self._history_idx > 0:
            self._history_idx -= 1
        self.cmd_entry.delete(0, "end")
        self.cmd_entry.insert(0, self._history[self._history_idx])
        return "break"

    def _history_down(self, event=None):
        if not self._history or self._history_idx == -1:
            return "break"
        if self._history_idx < len(self._history) - 1:
            self._history_idx += 1
            self.cmd_entry.delete(0, "end")
            self.cmd_entry.insert(0, self._history[self._history_idx])
        else:
            self._history_idx = -1
            self.cmd_entry.delete(0, "end")
        return "break"
