"""Launcher used by PyInstaller (it needs a plain script, not a package entry point)."""

from ship_radar.__main__ import main

if __name__ == "__main__":
    main()
