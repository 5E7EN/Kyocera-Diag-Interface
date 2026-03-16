#!/usr/bin/env python3
"""
Kyocera Diag Interface - GUI entry point.
Must be run as root for USB access.

Usage:
    sudo python3 main.py
"""

import os
import sys


def _is_admin() -> bool:
    """Check for elevated privileges on both Linux and Windows."""
    if sys.platform == "win32":
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    return os.geteuid() == 0
    return True


def main():
    if not _is_admin():
        if sys.platform == "win32":
            print("Error: This tool must be run as Administrator.")
            print("  Right-click your terminal and select 'Run as administrator'.")
        else:
            print("Error: This tool must be run as root.")
            print("  Usage: sudo python3 main.py")
        sys.exit(1)

    # Ensure project root is in sys.path
    project_root = os.path.dirname(os.path.abspath(__file__))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from gui.app import App

    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
