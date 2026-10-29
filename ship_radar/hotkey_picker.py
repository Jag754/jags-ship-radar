"""A small window that records a new hotkey from the keys you press."""

import tkinter as tk

from . import hotkey
from .overlay import ACCENTS, BG, FG, MUTED

# Tk keysyms for the modifier keys, in the order they're written in a hotkey.
MODIFIERS = {
    "ctrl": ("Control_L", "Control_R"),
    "alt": ("Alt_L", "Alt_R"),
    "shift": ("Shift_L", "Shift_R"),
    "win": ("Win_L", "Win_R"),
}
BUTTON = "#1c2430"


class HotkeyPicker:
    """Shows the combination as you press it. Save checks it can be used; on_done gets it, or None."""

    def __init__(self, root, current, on_done):
        self.on_done = on_done
        self.held = set()
        self.combo = None
        w = self.win = tk.Toplevel(root, bg=BG, padx=20, pady=16)
        w.title("Change hotkey · Jag's Ship Radar")
        w.resizable(False, False)
        w.attributes("-topmost", True)
        w.protocol("WM_DELETE_WINDOW", lambda: self._finish(None))

        tk.Label(w, text="Press the new key combination", bg=BG, fg=FG, font=("Segoe UI", 12, "bold"),
                 anchor="w").pack(fill="x")
        tk.Label(w, text=f"Currently {current.upper()}. Turns alerts on and off, even while the game has focus.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 9), anchor="w").pack(fill="x", pady=(2, 12))
        self.shown = tk.Label(w, text="…", bg=BUTTON, fg=ACCENTS["ship"], font=("Segoe UI", 18, "bold"),
                              width=18, pady=10)
        self.shown.pack(fill="x")
        self.status = tk.Label(w, text="For example Ctrl+Shift+F8, Alt+F10 or Ctrl+Num5.", bg=BG, fg=MUTED,
                               font=("Segoe UI", 9), anchor="w", wraplength=360, justify="left")
        self.status.pack(fill="x", pady=(8, 12))

        row = tk.Frame(w, bg=BG)
        row.pack(fill="x")
        self.save = self._button(row, "Save", ACCENTS["on"], self._save)
        self._button(row, "Cancel", MUTED, lambda: self._finish(None))

        w.bind("<KeyPress>", self._press)
        w.bind("<KeyRelease>", self._release)
        w.update_idletasks()
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        w.geometry(f"+{(sw - w.winfo_reqwidth()) // 2}+{(sh - w.winfo_reqheight()) // 3}")
        w.after(50, w.focus_force)

    def _button(self, parent, text, color, command):
        b = tk.Label(parent, text=text, bg=BUTTON, fg=color, font=("Segoe UI", 10, "bold"), padx=14, pady=4,
                     cursor="hand2")
        b.pack(side="right", padx=(8, 0))
        b.bind("<Button-1>", lambda e: command())
        return b

    def _mods(self):
        return [m for m, syms in MODIFIERS.items() if self.held & set(syms)]

    def _press(self, e):
        if any(e.keysym in syms for syms in MODIFIERS.values()):
            self.held.add(e.keysym)
            if not self.combo:
                self.shown.configure(text="+".join(self._mods()).upper() + "+…")
            return "break"
        if e.keysym in ("Escape",) and not self._mods():
            self._finish(None)
            return "break"
        if e.keysym in ("Return", "KP_Enter") and not self._mods() and self.combo:
            self._save()
            return "break"
        # On Windows, Tk's keycode is the Windows virtual key code, which is what RegisterHotKey wants.
        name = hotkey.key_name(e.keycode)
        if name is None:
            self.status.configure(text=f"{e.keysym} can't be used. Try a letter, number, F-key or Num key.",
                                  fg=ACCENTS["warn"])
            return "break"
        self.combo = "+".join(self._mods() + [name])
        self.shown.configure(text=self.combo.upper())
        problem = hotkey.check(self.combo)
        self.status.configure(text=problem or "Looks good. Click Save, or press Enter.",
                              fg=ACCENTS["warn"] if problem else ACCENTS["on"])
        return "break"

    def _release(self, e):
        self.held.discard(e.keysym)
        return "break"

    def _save(self):
        if not self.combo:
            self.status.configure(text="Press a key combination first.", fg=ACCENTS["warn"])
            return
        problem = hotkey.check(self.combo)
        if problem:
            self.status.configure(text=problem, fg=ACCENTS["warn"])
            return
        self._finish(self.combo)

    def _finish(self, combo):
        self.win.destroy()
        self.on_done(combo)
