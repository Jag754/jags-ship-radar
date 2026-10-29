"""Settings, stored as JSON in %APPDATA%\\JagsShipRadar\\config.json."""

import copy
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

APP_NAME = "Jag's Ship Radar"
CONFIG_DIR = Path(os.environ.get("APPDATA") or Path.home()) / "JagsShipRadar"
CONFIG_PATH = CONFIG_DIR / "config.json"

# The one line most likely to need changing if a game patch renames the log line.
# It must keep the named groups `code` (e.g. AEGS_Idris) and `id` (the ship's entity id).
DEFAULT_SHIP_REGEX = r"ATC '(?P<code>[A-Za-z0-9_\-]+?)_ShipATCDataManager_(?P<id>\d+)'"

DEFAULTS = {
    "log_path": "",
    "hotkey": "ctrl+shift+f8",
    "enabled_on_start": True,
    "position": "top-right",
    "offset_x": 24,
    "offset_y": 120,
    "scale": 1.0,
    "opacity": 0.93,
    "toast_seconds": 7,
    "max_toasts": 5,
    "sound": True,
    "volume": 0.6,
    "sound_file": "",
    "priority_sound_file": "",
    "speech": "all",
    "voice": "",
    "show_repings": True,
    "nearby_list": False,
    "nearby_hotkey": "ctrl+shift+f9",
    "nearby_minutes": 10,
    "nearby_position": "top-left",
    "nearby_offset_x": 24,
    "nearby_offset_y": 120,
    "nearby_scale": 1.0,
    "batch_window_seconds": 1.5,
    "batch_max_wait_seconds": 6,
    "burst_threshold": 4,
    "catch_up_existing_log": True,
    "check_for_updates": True,
    "ignore": [],
    "priority": [
        "Idris", "Javelin", "Polaris", "Perseus", "Hammerhead", "Kraken",
        "Ironclad", "Carrack", "Reclaimer", "890", "Retaliator", "Redeemer",
    ],
    "name_overrides": {},
    "ship_line_regex": DEFAULT_SHIP_REGEX,
    "_help": {
        "log_path": "Full path to Game.log, or blank to find it automatically.",
        "hotkey": "Turns alerts on/off. Modifiers ctrl/shift/alt/win plus a key, e.g. ctrl+shift+f8. Easier: tray → Change hotkey.",
        "position": "top-right, top-left, bottom-right or bottom-left. Easier: tray → Move / resize alerts.",
        "offset_x / offset_y": "Pixels in from the chosen corner.",
        "scale": "Size of the alerts. 1.0 is normal, 1.3 is bigger.",
        "sound / volume": "Ping sounds (and speech) on or off, and how loud (0.0 to 1.0). Easier: tray → Sound.",
        "sound_file / priority_sound_file": "Your own .wav files instead of the built-in pings, or blank.",
        "speech": "Say ship names out loud: off, priority (priority ships and busy areas with one) or all (every new ship). Easier: tray → Sound → Speak ship names.",
        "voice": "Part of an installed Windows voice's name, e.g. \"Zira\", or blank for the Windows default.",
        "toast_seconds": "How long each alert stays on screen.",
        "show_repings": "Ping again (marked RE-PING) when a ship you already saw loads in again.",
        "nearby_list": "Show the list of ships seen recently. Easier: tray → Nearby ships list, or the nearby_hotkey.",
        "nearby_hotkey": "Shows and hides the nearby list, like hotkey. Blank for none.",
        "nearby_minutes": "Ships drop off the nearby list after this many minutes without loading in again. They dim after a third of that.",
        "nearby_position / nearby_offset_x / nearby_offset_y / nearby_scale": "Where the nearby list sits and its size. Easier: tray → Move / resize nearby list.",
        "batch_window_seconds": "Ships arriving this close together are grouped.",
        "burst_threshold": "More ships than this in one group become a single summary alert.",
        "catch_up_existing_log": "On start, read the current Game.log quietly so re-pings are accurate.",
        "check_for_updates": "Look for a new version at startup and every 6 hours. Updates are signed and only install when you choose.",
        "ignore": "Ships to never ping. Matches part of the name or code, e.g. \"Pisces\" or \"GRIN_\".",
        "priority": "Ships that get a red alert and louder sound. Matches part of the name or code.",
        "name_overrides": "Rename ship codes, e.g. {\"ORIG_m80\": \"Origin M80 Racer\"}.",
        "ship_line_regex": "Pattern for the log line. Must keep the groups code and id.",
    },
}


def load():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = copy.deepcopy(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cfg.update({k: v for k, v in user.items() if k in DEFAULTS and k != "_help"})
        except (OSError, ValueError) as e:
            log.warning("Could not read %s, using defaults: %s", CONFIG_PATH, e)
            return cfg
    save(cfg)
    return cfg


def save(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    out = dict(cfg)
    out["_help"] = DEFAULTS["_help"]
    CONFIG_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
