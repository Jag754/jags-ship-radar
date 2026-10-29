"""The nearby list: ships seen recently, newest first, priority ships on top.

The game log only says when a ship loads in near you, never when it leaves, so "nearby" means
"loaded in within the last few minutes". Ships dim after a third of that time and then drop off;
one that keeps re-pinging stays on, since it's clearly still around.
"""

import tkinter as tk
from dataclasses import dataclass
from datetime import datetime

from .overlay import ACCENTS, BG, FG, HWND_TOPMOST, MUTED, SWP_FLAGS, Placer, _u32, make_passive

PRIORITY_FG = "#ff6b6b"
MAX_ROWS = 15
REFRESH_MS = 1000


@dataclass
class Seen:
    ship_id: str
    name: str
    priority: bool
    count: int
    first_seen: datetime
    last_seen: datetime


@dataclass
class Row:
    """One line of the list: every recent ship of one type."""
    name: str
    priority: bool
    ships: int
    age: float  # seconds since the most recent of them loaded in
    dim: bool


def short_age(seconds):
    seconds = max(0, int(seconds))
    if seconds < 60:
        return "now" if seconds < 15 else f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h {seconds % 3600 // 60}m"


class RecentShips:
    def __init__(self, minutes):
        self.minutes = float(minutes)
        self.ships = {}

    def add(self, alert):
        s = self.ships.get(alert.ship_id)
        if s is None:
            self.ships[alert.ship_id] = Seen(alert.ship_id, alert.name, alert.priority, alert.count,
                                             alert.first_seen, alert.ts)
        else:
            s.count, s.priority, s.name = alert.count, alert.priority, alert.name
            s.last_seen = max(s.last_seen, alert.ts)

    def clear(self):
        self.ships.clear()

    def rows(self, now, aboard=()):
        """[Row], one per ship type, priority first, then most recently seen. Forgets stale ships."""
        limit = self.minutes * 60
        for sid in [sid for sid, s in self.ships.items() if (now - s.last_seen).total_seconds() > limit]:
            del self.ships[sid]
        groups = {}
        for s in self.ships.values():
            if s.ship_id in aboard:
                continue
            age = (now - s.last_seen).total_seconds()
            row = groups.get(s.name)
            if row is None:
                groups[s.name] = Row(s.name, s.priority, 1, age, False)
            else:
                row.ships += 1
                row.age = min(row.age, age)
                row.priority = row.priority or s.priority
        out = list(groups.values())
        for row in out:
            row.dim = row.age > limit / 3
        out.sort(key=lambda r: (not r.priority, r.age, r.name))
        return out


class NearbyPanel:
    """An always-on-top, click-through window listing RecentShips."""

    base_width = 300

    def __init__(self, root, ships, now_fn, aboard_fn):
        self.root = root
        self.ships, self.now_fn, self.aboard_fn = ships, now_fn, aboard_fn
        self.win = None
        self.shown_rows = None
        self.placer = None
        self.visible = False

    def apply(self, cfg):
        self.cfg = cfg
        self.ships.minutes = float(cfg.get("nearby_minutes", 10))
        self.dpi = self.root.winfo_fpixels("1i") / 96
        self.user_scale = float(cfg.get("nearby_scale", 1.0))
        self.s = self.user_scale * self.dpi
        self.pos = cfg.get("nearby_position", "top-left")
        self.bottom = self.pos.startswith("bottom")
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        ox, oy = int(cfg.get("nearby_offset_x", 24) * self.dpi), int(cfg.get("nearby_offset_y", 120) * self.dpi)
        width = int(self.base_width * self.s)
        x = ox if "left" in self.pos else sw - width - ox
        self.origin = (x, oy, sh)
        if self.win:
            self.win.destroy()
            self.win = None
        self.shown_rows = None
        if self.visible:
            self._open()

    def _open(self):
        w = self.win = tk.Toplevel(self.root, bg=BG)
        w.withdraw()
        w.overrideredirect(True)
        w.attributes("-alpha", float(self.cfg.get("opacity", 0.93)))
        w.attributes("-topmost", True)
        w.attributes("-toolwindow", True)
        self.body = tk.Frame(w, bg=BG)
        self.body.pack(fill="both", expand=True)
        self._render(force=True)
        w.deiconify()
        w.update_idletasks()
        self.hwnd = _u32.GetParent(w.winfo_id())
        make_passive(self.hwnd)
        self._tick()

    def set_visible(self, on):
        self.visible = on
        if on and not self.win and not self.placer:
            self._open()
        elif not on and self.win:
            self.win.destroy()
            self.win = None
            self.shown_rows = None

    def _tick(self):
        if not self.win:
            return
        self._render()
        # Some games push themselves above other topmost windows; re-assert quietly.
        _u32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_FLAGS)
        self.win.after(REFRESH_MS, self._tick)

    def _render(self, force=False):
        rows = self.ships.rows(self.now_fn(), self.aboard_fn())
        # Only rebuild when something visible changed, so the list doesn't flicker every second.
        key = [(r.name, r.priority, r.ships, short_age(r.age), r.dim) for r in rows]
        if key == self.shown_rows and not force:
            return
        self.shown_rows = key
        for child in self.body.winfo_children():
            child.destroy()
        self._draw(self.body, self.user_scale, rows)
        self._place()

    def _draw(self, parent, scale, rows):
        s = scale * self.dpi

        def font(size, bold=False):
            return ("Segoe UI", max(7, round(size * scale)), "bold" if bold else "normal")

        tk.Frame(parent, bg=ACCENTS["ship"], width=int(5 * s)).pack(side="left", fill="y")
        box = tk.Frame(parent, bg=BG, padx=int(12 * s), pady=int(8 * s))
        box.pack(side="left", fill="both", expand=True)
        head = tk.Frame(box, bg=BG)
        head.pack(fill="x", pady=(0, int(4 * s)))
        tk.Label(head, text="NEARBY SHIPS", bg=BG, fg=ACCENTS["ship"], font=font(8, True)).pack(side="left")
        total = sum(r.ships for r in rows)
        tk.Label(head, text=f"{total} ship{'s' if total != 1 else ''}" if rows else "", bg=BG, fg=MUTED,
                 font=font(8, True)).pack(side="right")
        if not rows:
            tk.Label(box, text=f"Nothing loaded in for {int(self.ships.minutes)} min", bg=BG, fg=MUTED,
                     font=font(10), anchor="w").pack(fill="x")
        for r in rows[:MAX_ROWS]:
            line = tk.Frame(box, bg=BG)
            line.pack(fill="x")
            color = MUTED if r.dim else PRIORITY_FG if r.priority else FG
            if r.ships > 1:
                tk.Label(line, text=f"{r.ships}×", bg=BG, fg=MUTED, font=font(10, True)).pack(side="left")
            tk.Label(line, text=r.name, bg=BG, fg=color, font=font(11, r.priority and not r.dim),
                     anchor="w").pack(side="left")
            tk.Label(line, text=short_age(r.age), bg=BG, fg=MUTED, font=font(9)).pack(side="right")
        if len(rows) > MAX_ROWS:
            rest = rows[MAX_ROWS:]
            tk.Label(box, text=f"+ {sum(r.ships for r in rest)} more ({len(rest)} types)", bg=BG, fg=MUTED,
                     font=font(9), anchor="w").pack(fill="x")

    def _place(self):
        w = self.win
        w.update_idletasks()
        width, height = int(self.base_width * self.s), w.winfo_reqheight()
        x, oy, sh = self.origin
        y = sh - oy - height if self.bottom else oy
        w.geometry(f"{width}x{height}+{x}+{y}")

    # ---- move / resize ------------------------------------------------------

    def sample(self, parent, scale, s):
        """Stand-in for the move/resize window: the real list if there is one, else examples."""
        now = self.now_fn()
        rows = self.ships.rows(now, self.aboard_fn())[:6]
        if not rows:
            rows = [Row("Aegis Idris", True, 1, 40, False), Row("Anvil Hornet F7C Mk II", False, 3, 90, False),
                    Row("Drake Cutlass Black", False, 1, 300, True)]
        frame = tk.Frame(parent, bg=BG)
        frame.pack(fill="x")
        self._draw(frame, scale, rows)

    def start_placing(self, on_done):
        if self.placer:
            self.placer.win.lift()
            return
        was = self.visible
        self.set_visible(False)
        self.visible = was

        def done(result):
            self.placer = None
            if self.visible:
                self._open()
            on_done(result)

        self.placer = Placer(self, done)

    @staticmethod
    def placement_settings(result):
        """Placer's result -> this panel's settings keys."""
        return {f"nearby_{k}": v for k, v in result.items()}
