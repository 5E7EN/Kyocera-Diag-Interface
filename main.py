#!/usr/bin/env python3
"""
Kyocera Diag Interface - GUI entry point.
Must be run as root for USB access.

Usage:
    sudo python3 main.py
"""

import os
import sys


def main():
    if os.geteuid() != 0:
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
