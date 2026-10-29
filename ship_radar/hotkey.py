"""A system-wide hotkey that works while the game has focus."""

import ctypes
import logging
import threading
from ctypes import wintypes

log = logging.getLogger(__name__)

_u32 = ctypes.WinDLL("user32", use_last_error=True)
_k32 = ctypes.WinDLL("kernel32")
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MODS = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}
MOD_NOREPEAT = 0x4000
NAMED_KEYS = {
    "space": 0x20, "pageup": 0x21, "pagedown": 0x22, "end": 0x23, "home": 0x24,
    "insert": 0x2D, "delete": 0x2E, "pause": 0x13, "scrolllock": 0x91,
    **{f"f{i}": 0x6F + i for i in range(1, 25)},
    **{f"num{i}": 0x60 + i for i in range(10)},
}


KEY_NAMES = {vk: name for name, vk in NAMED_KEYS.items()}
# Keys that are fine on their own; anything else needs a modifier, or it would stop working everywhere else.
SOLO_OK = {name for name in NAMED_KEYS if name.startswith("f") or name in ("pause", "scrolllock")}


def key_name(vk):
    """Windows virtual key code -> the name parse() understands, or None for keys we don't support."""
    if vk in KEY_NAMES:
        return KEY_NAMES[vk]
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk).lower()
    return None


def check(text):
    """Problem with this hotkey as a sentence, or None if it can be used."""
    try:
        mods, vk = parse(text)
    except ValueError as e:
        return str(e)
    if not mods and key_name(vk) not in SOLO_OK:
        return "Add Ctrl, Alt or Shift, or that key would stop working in other programs."
    # Briefly claim it to find out whether another program already has it.
    if not _u32.RegisterHotKey(None, 0xBEEF, mods | MOD_NOREPEAT, vk):
        return "Another program already uses that combination."
    _u32.UnregisterHotKey(None, 0xBEEF)
    return None


def parse(text):
    """'ctrl+shift+f8' -> (modifiers, virtual key code)."""
    mods, vk = 0, None
    for part in text.lower().replace(" ", "").split("+"):
        if part in MODS:
            mods |= MODS[part]
        elif part in NAMED_KEYS:
            vk = NAMED_KEYS[part]
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        else:
            raise ValueError(f"Unknown key '{part}' in hotkey '{text}'")
    if vk is None:
        raise ValueError(f"Hotkey '{text}' has no main key")
    return mods, vk


class Hotkey(threading.Thread):
    """Calls callback() from this thread each time the hotkey is pressed."""

    def __init__(self, text, callback, on_error):
        super().__init__(daemon=True, name="Hotkey")
        self.text = text
        self.callback = callback
        self.on_error = on_error
        self.tid = None

    def run(self):
        try:
            mods, vk = parse(self.text)
        except ValueError as e:
            self.on_error(str(e))
            return
        self.tid = _k32.GetCurrentThreadId()
        if not _u32.RegisterHotKey(None, 1, mods | MOD_NOREPEAT, vk):
            self.on_error(f"Hotkey {self.text} is already used by another program. Change it in settings.")
            return
        log.info("Hotkey %s registered", self.text)
        msg = wintypes.MSG()
        while _u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                self.callback()
        _u32.UnregisterHotKey(None, 1)

    def stop(self):
        if self.tid:
            _u32.PostThreadMessageW(self.tid, WM_QUIT, 0, 0)
