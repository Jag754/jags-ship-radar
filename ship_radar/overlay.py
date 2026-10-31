"""On-screen alerts drawn in our own always-on-top window.

One invisible, click-through window sits in a corner of the screen for the whole session and the
alerts are drawn inside it. Because no new window is ever opened, an alert can never take focus
away from the game. Needs the game in Borderless Window mode (exclusive fullscreen hides everything).
"""

import ctypes
import tkinter as tk
from datetime import timezone

_u32 = ctypes.windll.user32
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x80000
WS_EX_TRANSPARENT = 0x20
WS_EX_TOOLWINDOW = 0x80
WS_EX_NOACTIVATE = 0x8000000
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_FLAGS = 0x1 | 0x2 | 0x10  # no size | no move | no activate
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4

KEY = "#010203"  # painted fully transparent
BG = "#10151c"
FG = "#e8edf3"
MUTED = "#8c97a6"
ACCENTS = {
    "ship": "#3fb6ff",
    "reping": "#8c97a6",
    "priority": "#ff4d4d",
    "summary": "#f5a524",
    "on": "#3ddc84",
    "off": "#8c97a6",
    "warn": "#f5a524",
}


def local_time(ts):
    return ts.replace(tzinfo=timezone.utc).astimezone().strftime("%H:%M:%S")


def ago(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    return f"{seconds // 3600}h {seconds % 3600 // 60}m ago"


def make_passive(hwnd):
    """Click-through, never focused, kept off the taskbar and Alt+Tab.

    Tk rewrites the extended style whenever it applies -alpha, -topmost and the like, so call this
    after them and again each time the window is shown."""
    style = _u32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    _u32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                        style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)


def bring_to_top(hwnd):
    """Put the window back on top of every always-on-top window, without taking focus.

    After Alt+Tab back into the game, the game can sit above us, and asking for HWND_TOPMOST
    again doesn't move a window that's already topmost. Dropping out of the topmost band and
    back in re-inserts it at the very top."""
    _u32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_FLAGS)
    _u32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_FLAGS)


def reshow(hwnd):
    """Hide and show the window again, without taking focus, so Windows draws it over the game again."""
    _u32.ShowWindow(hwnd, SW_HIDE)
    _u32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
    bring_to_top(hwnd)


class TopKeeper:
    """Keeps a window over the game. When another window comes to the front (checked twice a
    second), e.g. Alt+Tab back into the game, the window is shown again; every few seconds it's
    put back on top regardless."""

    POLL_MS, EVERY = 500, 6

    def __init__(self, widget, hwnd_fn):
        self.widget, self.hwnd_fn = widget, hwnd_fn
        self.fg, self.n = None, 0
        self._tick()

    def _tick(self):
        try:
            if not self.widget.winfo_exists():
                return
        except tk.TclError:
            return
        fg = _u32.GetForegroundWindow()
        self.n += 1
        if fg != self.fg:
            self.fg, self.n = fg, 0
            if self.widget.winfo_viewable():
                reshow(self.hwnd_fn())
        elif self.n >= self.EVERY:
            self.n = 0
            bring_to_top(self.hwnd_fn())
        self.widget.after(self.POLL_MS, self._tick)


def corner_placement(x, y, w, h, sw, sh, dpi):
    """Settings for alerts whose first card sits at (x, y, w, h) on a sw×sh screen.

    Anchors to the nearest corner so the alerts stay put if the resolution changes, and so they
    stack away from that corner (downwards at the top, upwards at the bottom)."""
    right = x + w / 2 > sw / 2
    bottom = y + h / 2 > sh / 2
    return {
        "position": f"{'bottom' if bottom else 'top'}-{'right' if right else 'left'}",
        "offset_x": max(0, round((sw - x - w if right else x) / dpi)),
        "offset_y": max(0, round((sh - y - h if bottom else y) / dpi)),
    }


class Overlay:
    base_width = 380

    def __init__(self, root, cfg):
        self.root = root
        self.toasts = []
        self.win = None
        self.placer = None
        self.apply(cfg)

    def apply(self, cfg):
        """(Re)build the overlay window from settings."""
        self.cfg = cfg
        for t in self.toasts:
            t.destroy()
        self.toasts = []
        if self.win:
            self.win.destroy()

        dpi = self.dpi = self.root.winfo_fpixels("1i") / 96
        self.user_scale = float(cfg.get("scale", 1.0))
        self.s = self.user_scale * dpi
        width = int(380 * self.s)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        pos = cfg.get("position", "top-right")
        ox, oy = int(cfg.get("offset_x", 24) * dpi), int(cfg.get("offset_y", 120) * dpi)
        x = ox if "left" in pos else sw - width - ox
        self.bottom = pos.startswith("bottom")
        # The window runs from the anchored edge to the far edge of the screen; it's invisible and
        # click-through, so only where the cards start matters.
        top, height = (0, max(200, sh - oy)) if self.bottom else (oy, max(200, sh - oy))
        self.origin = (x, oy, sh)

        w = self.win = tk.Toplevel(self.root, bg=KEY)
        w.withdraw()
        w.overrideredirect(True)
        w.geometry(f"{width}x{height}+{x}+{top}")
        w.attributes("-transparentcolor", KEY)
        w.attributes("-alpha", float(cfg.get("opacity", 0.93)))
        w.attributes("-topmost", True)
        w.attributes("-toolwindow", True)
        w.deiconify()
        w.update_idletasks()
        self.hwnd = _u32.GetParent(w.winfo_id())
        make_passive(self.hwnd)
        TopKeeper(w, lambda: self.hwnd)

    def card(self, parent, scale, kind, tag, title, subtitle="", lines=()):
        """One alert card at `scale` (the user's size setting), not yet packed."""
        s = scale * self.dpi

        def font(size, bold=False):
            # Tk already scales point sizes for screen DPI, so only the user's scale applies here.
            return ("Segoe UI", max(7, round(size * scale)), "bold" if bold else "normal")

        card = tk.Frame(parent, bg=BG)
        tk.Frame(card, bg=ACCENTS.get(kind, ACCENTS["ship"]), width=int(5 * s)).pack(side="left", fill="y")
        body = tk.Frame(card, bg=BG, padx=int(12 * s), pady=int(8 * s))
        body.pack(side="left", fill="both", expand=True)
        tk.Label(body, text=tag.upper(), bg=BG, fg=ACCENTS.get(kind, MUTED), font=font(8, True), anchor="w").pack(fill="x")
        tk.Label(body, text=title, bg=BG, fg=FG, font=font(14, True), anchor="w",
                 justify="left", wraplength=int(340 * s)).pack(fill="x")
        if subtitle:
            tk.Label(body, text=subtitle, bg=BG, fg=MUTED, font=font(9), anchor="w",
                     justify="left", wraplength=int(340 * s)).pack(fill="x")
        for text, color in lines:
            tk.Label(body, text=text, bg=BG, fg=color or FG, font=font(10), anchor="w").pack(fill="x")
        return card

    def show(self, kind, tag, title, subtitle="", lines=(), seconds=None):
        s = self.s
        card = self.card(self.win, self.user_scale, kind, tag, title, subtitle, lines)

        side = "bottom" if self.bottom else "top"
        if self.toasts:
            ref = self.toasts[-1]
            card.pack(side=side, fill="x", pady=(0, int(8 * s)) if side == "top" else (int(8 * s), 0), before=ref)
        else:
            card.pack(side=side, fill="x", pady=(0, int(8 * s)) if side == "top" else (int(8 * s), 0))
        self.toasts.append(card)

        while len(self.toasts) > int(self.cfg.get("max_toasts", 5)):
            self.toasts.pop(0).destroy()
        secs = seconds if seconds is not None else float(self.cfg.get("toast_seconds", 7))
        self.root.after(int(secs * 1000), lambda: self._remove(card))
        bring_to_top(self.hwnd)

    def sample(self, parent, scale, s):
        """Stand-in cards for the move/resize window."""
        now = "12:00:00"
        self.card(parent, scale, "ship", "New contact", "Anvil Hornet F7C Mk2",
                  f"{now} · ID …12345").pack(fill="x", pady=(0, int(8 * s)))
        self.card(parent, scale, "priority", "Priority contact", "Aegis Idris", f"{now} · ID …67890").pack(fill="x")

    def _remove(self, card):
        if card in self.toasts:
            self.toasts.remove(card)
            card.destroy()

    def start_placing(self, on_done):
        """Let the user drag and resize the alerts. on_done gets the new settings, or None if cancelled."""
        if self.placer:
            self.placer.win.lift()
            return

        def done(result):
            self.placer = None
            self.win.deiconify()
            make_passive(self.hwnd)
            on_done(result)

        self.win.withdraw()
        self.placer = Placer(self, done)


class Placer:
    """Move-and-resize mode: a solid stand-in for the alerts (or the nearby list) that takes the mouse.

    `target` provides root, dpi, user_scale, base_width, origin, bottom and sample().

    Drag it anywhere, drag the corner grip to change the size, then Done (Enter) or Cancel (Esc).
    """

    MIN_SCALE, MAX_SCALE = 0.6, 2.0

    def __init__(self, overlay, on_done):
        self.ov, self.on_done = overlay, on_done
        self.scale = overlay.user_scale
        self.sw, self.sh = overlay.root.winfo_screenwidth(), overlay.root.winfo_screenheight()
        w = self.win = tk.Toplevel(overlay.root, bg=ACCENTS["ship"])
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.bind("<Escape>", lambda e: self._finish(False))
        w.bind("<Return>", lambda e: self._finish(True))
        self.frame = None
        self._build()
        x, oy, sh = overlay.origin
        h = w.winfo_reqheight()
        self._place(x, sh - oy - h if overlay.bottom else oy)
        w.after(50, w.focus_force)

    def _width(self):
        return int(self.ov.base_width * self.scale * self.ov.dpi)

    def _build(self):
        if self.frame:
            self.frame.destroy()
        f = self.frame = tk.Frame(self.win, bg=BG)
        f.pack(fill="both", expand=True, padx=2, pady=2)
        s = self.scale * self.ov.dpi
        font = ("Segoe UI", max(7, round(9 * self.scale)))

        bar = tk.Frame(f, bg=BG, padx=int(8 * s), pady=int(6 * s))
        bar.pack(fill="x")
        self.hint = tk.Label(bar, bg=BG, fg=MUTED, font=font, anchor="w")
        self.hint.pack(side="left")
        self._update_hint()
        for text, ok, color in (("Done", True, ACCENTS["on"]), ("Cancel", False, MUTED)):
            b = tk.Label(bar, text=text, bg="#1c2430", fg=color, font=(font[0], font[1], "bold"),
                         padx=int(8 * s), pady=int(2 * s), cursor="hand2")
            b.pack(side="right", padx=(int(6 * s), 0))
            b.bind("<Button-1>", lambda e, ok=ok: self._finish(ok))

        self.ov.sample(f, self.scale, s)

        grip = tk.Label(f, text="◢", bg=BG, fg=ACCENTS["ship"], font=("Segoe UI", max(9, round(14 * self.scale))),
                        cursor="size_nw_se")
        grip.place(relx=1, rely=1, anchor="se")
        grip.bind("<ButtonPress-1>", self._grip_start)
        grip.bind("<B1-Motion>", self._grip_move)
        grip.bind("<ButtonRelease-1>", self._grip_end)

        def bind_drag(widget):
            if widget is grip or widget.cget("cursor") == "hand2":
                return
            widget.configure(cursor="fleur")
            widget.bind("<ButtonPress-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)
            for child in widget.winfo_children():
                bind_drag(child)

        bind_drag(f)

    def _update_hint(self):
        self.hint.configure(text=f"Drag to move · corner to resize · {round(self.scale * 100)}%")

    def _place(self, x, y):
        w = self.win
        w.update_idletasks()
        width, height = self._width() + 4, w.winfo_reqheight()
        x = min(max(0, x), self.sw - width)
        y = min(max(0, y), self.sh - height)
        w.geometry(f"{width}x{height}+{int(x)}+{int(y)}")

    def _drag_start(self, e):
        self.grab = (e.x_root - self.win.winfo_x(), e.y_root - self.win.winfo_y())

    def _drag_move(self, e):
        self._place(e.x_root - self.grab[0], e.y_root - self.grab[1])

    def _grip_start(self, e):
        self.grab = (e.x_root, self._width())

    def _grip_move(self, e):
        width = self.grab[1] + e.x_root - self.grab[0]
        self.scale = min(self.MAX_SCALE, max(self.MIN_SCALE, round(width / (self.ov.base_width * self.ov.dpi), 2)))
        self._update_hint()
        self.win.geometry(f"{self._width() + 4}x{self.win.winfo_height()}")

    def _grip_end(self, e):
        # Rebuild the sample cards at the new size, keeping the top-left corner where it was.
        x, y = self.win.winfo_x(), self.win.winfo_y()
        self._build()
        self._place(x, y)

    def _finish(self, ok):
        w = self.win
        result = None
        if ok:
            # The stand-in's 2px border and button bar aren't part of the alerts; measure the cards.
            x, y = w.winfo_x() + 2, w.winfo_y() + 2
            result = corner_placement(x, y, self._width(), w.winfo_height() - 4, self.sw, self.sh, self.ov.dpi)
            result["scale"] = self.scale
        w.destroy()
        self.on_done(result)
