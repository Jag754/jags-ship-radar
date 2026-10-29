"""Find Star Citizen's Game.log without the user having to point at it."""

import logging
import os
import string
from pathlib import Path

log = logging.getLogger(__name__)

CHANNELS = ("LIVE", "PTU", "EPTU", "TECH-PREVIEW", "HOTFIX")
SKIP_DIRS = {"windows", "$recycle.bin", "system volume information", "programdata", "users", "perflogs", "recovery"}


def _drives():
    return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]


def _logs_in_install(sc_dir):
    """sc_dir is a StarCitizen folder; returns Game.log files under its channel folders."""
    out = []
    for ch in CHANNELS:
        p = Path(sc_dir) / ch / "Game.log"
        if p.is_file():
            out.append(p)
    return out


def _subdirs(path):
    try:
        with os.scandir(path) as it:
            return [e.path for e in it if e.is_dir(follow_symlinks=False) and e.name.lower() not in SKIP_DIRS]
    except OSError:
        return []


def find_all():
    """Every Game.log in a StarCitizen folder up to three levels below a drive root."""
    found = []
    for drive in _drives():
        level = [drive]
        for _ in range(4):
            nxt = []
            for d in level:
                if os.path.basename(d.rstrip("\\")).lower() == "starcitizen":
                    found.extend(_logs_in_install(d))
                else:
                    nxt.extend(_subdirs(d))
            level = nxt
    return found


def resolve(configured=""):
    """The Game.log to watch: the configured one if valid, else the most recently written one found."""
    if configured:
        p = Path(configured)
        if p.is_dir():
            p = p / "Game.log"
        if p.is_file():
            return p
        log.warning("Configured log_path %s does not exist, searching instead", configured)
    logs = find_all()
    if not logs:
        return None
    return max(logs, key=lambda p: p.stat().st_mtime)
