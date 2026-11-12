"""Problem reports: the player sends the radar's own logs to jaghost.org from the tray menu.

Nothing is ever sent on its own. The player opens the window, can read exactly what will go,
and presses Send. What goes: their note, the end of app.log and crash.log, the radar's version,
the Windows version and the radar's settings, with their Windows user name and game handle
taken out. Sent over HTTPS to one hard-coded address; the reply is only read for ok/error.
"""

import json
import os
import platform
import re
import threading
import tkinter as tk
import urllib.error
import urllib.request

from . import __version__, config
from .overlay import ACCENTS, BG, FG, MUTED

# Hard-coded on purpose, like the update address: a config.json can't send reports elsewhere.
REPORT_URL = "https://updates.jaghost.org/report/ship-radar"
USER_AGENT = f"Jags-ShipRadar-report/{__version__}"
APP_LOG_BYTES = 300_000
CRASH_LOG_BYTES = 120_000
# Settings that help explain a problem and say nothing about who the player is.
SETTINGS_KEYS = ("enabled_on_start", "position", "scale", "opacity", "toast_seconds", "max_toasts", "sound",
                 "volume", "speech", "show_repings", "nearby_list", "nearby_position", "nearby_scale",
                 "catch_up_existing_log", "check_for_updates", "hotkey", "nearby_hotkey")
STATE_PATH = config.CONFIG_DIR / "report_state.json"
BUTTON = "#1c2430"


def tail(path, limit):
    """The last `limit` bytes of a text file, starting at a whole line; '' if it isn't there."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - limit))
            data = f.read()
    except OSError:
        return ""
    if size > limit and b"\n" in data:
        data = data[data.index(b"\n") + 1:]
    return data.decode("utf-8", "replace")


def redact(text, handle=None, env=os.environ):
    """Take the Windows user name (and the game handle, if known) out of log text."""
    for value, mask in ((env.get("USERPROFILE"), "%USERPROFILE%"), (env.get("USERNAME"), "<user>"), (handle, "<handle>")):
        if value and len(value) >= 2:
            text = re.sub(re.escape(value), mask, text, flags=re.IGNORECASE)
    return text


def build(cfg, note, reason="manual", handle=None, folder=None):
    folder = folder or config.CONFIG_DIR
    app_log = tail(folder / "app.log", APP_LOG_BYTES)
    if len(app_log) < APP_LOG_BYTES // 2:  # just rotated: the older file has the rest
        app_log = tail(folder / "app.log.1", APP_LOG_BYTES - len(app_log)) + app_log
    return {
        "version": __version__,
        "reason": reason,
        "windows": f"{platform.system()} {platform.release()} ({platform.version()})",
        "note": redact(note.strip(), handle)[:2000],
        "settings": {k: cfg.get(k) for k in SETTINGS_KEYS},
        "app_log": redact(app_log, handle),
        "crash_log": redact(tail(folder / "crash.log", CRASH_LOG_BYTES), handle),
    }


def preview(report):
    """The report as the plain text shown by 'Show what's sent'."""
    return "\n".join([
        f"Jag's Ship Radar {report['version']} · {report['windows']} · {report['reason']}",
        f"Sent to {REPORT_URL}", "",
        "Your note:", report["note"] or "(none)", "",
        "Settings:", json.dumps(report["settings"], indent=2), "",
        "----- crash.log -----", report["crash_log"] or "(empty)", "",
        "----- app.log -----", report["app_log"] or "(empty)",
    ])


def send(report, url=REPORT_URL, timeout=20, opener=urllib.request.urlopen):
    """POST the report. Returns (ok, message for the player). Never raises."""
    body = json.dumps(report).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "User-Agent": USER_AGENT})
    try:
        with opener(req, timeout=timeout) as resp:
            data = json.loads(resp.read(4096) or b"{}")
        return (True, "Sent. Thanks!") if data.get("ok") else (False, "The server didn't accept it.")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read(4096)).get("error")
        except Exception:
            msg = None
        return False, msg or f"The server said {e.code}."
    except Exception as e:
        return False, f"Couldn't reach jaghost.org: {getattr(e, 'reason', e)}"


# ---- "did it freeze or crash last time?" ------------------------------------

def last_run_trouble(folder=None, state_path=None):
    """'after-freeze' or 'after-crash' if crash.log gained a freeze or crash since the last start,
    else None. Remembers how far it has read, so each one is reported once."""
    folder = folder or config.CONFIG_DIR
    state_path = state_path or STATE_PATH
    try:
        seen = int(json.loads(state_path.read_text(encoding="utf-8")).get("crash_log_seen", 0))
    except (OSError, ValueError, AttributeError):
        seen = None
    path = folder / "crash.log"
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    try:
        state_path.write_text(json.dumps({"crash_log_seen": size}), encoding="utf-8")
    except OSError:
        pass
    if seen is None or size <= seen:  # first run with reports, or nothing new (or the log was trimmed)
        return None
    with open(path, "rb") as f:
        f.seek(seen)
        new = f.read().decode("utf-8", "replace")
    if "UI thread stalled" in new:
        return "after-freeze"
    if "Fatal Python error" in new:
        return "after-crash"
    return None


# ---- the window -------------------------------------------------------------

class ReportWindow:
    """Note box, what gets sent, Send. Sending runs on a thread; `post` brings the answer back."""

    def __init__(self, root, cfg, reason, handle, post, on_close):
        self.cfg, self.reason, self.handle, self.post, self.on_close = cfg, reason, handle, post, on_close
        w = self.win = tk.Toplevel(root, bg=BG, padx=20, pady=16)
        w.title("Send a problem report · Jag's Ship Radar")
        w.resizable(False, False)
        w.attributes("-topmost", True)
        w.protocol("WM_DELETE_WINDOW", self.close)

        heading = {"after-freeze": "The radar froze last time. Send a report?",
                   "after-crash": "The radar crashed last time. Send a report?"}.get(reason, "Send a problem report")
        tk.Label(w, text=heading, bg=BG, fg=FG, font=("Segoe UI", 12, "bold"), anchor="w").pack(fill="x")
        tk.Label(w, text="What happened? (What you were doing, e.g. Alt+Tab out of the game and back.)",
                 bg=BG, fg=MUTED, font=("Segoe UI", 9), anchor="w").pack(fill="x", pady=(2, 6))
        self.note = tk.Text(w, width=56, height=5, bg=BUTTON, fg=FG, insertbackground=FG, relief="flat",
                            font=("Segoe UI", 10), wrap="word", padx=8, pady=6)
        self.note.pack(fill="x")
        tk.Label(w, text="Sent with it: the radar's recent log and crash log, its version and settings, and your "
                         "Windows version. Your Windows user name and game handle are taken out. It goes to "
                         "jaghost.org, only when you press Send.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 9), anchor="w", justify="left", wraplength=440).pack(fill="x", pady=(8, 8))
        self.status = tk.Label(w, text="", bg=BG, fg=MUTED, font=("Segoe UI", 9), anchor="w", wraplength=440,
                               justify="left")
        self.status.pack(fill="x", pady=(0, 8))

        row = tk.Frame(w, bg=BG)
        row.pack(fill="x")
        self.send_btn = self._button(row, "Send", ACCENTS["on"], self._send, "right")
        self._button(row, "Cancel", MUTED, self.close, "right")
        self._button(row, "Show what's sent", ACCENTS["ship"], self._show, "left")

        w.update_idletasks()
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        w.geometry(f"+{(sw - w.winfo_reqwidth()) // 2}+{(sh - w.winfo_reqheight()) // 3}")
        w.after(50, w.focus_force)
        w.after(80, self.note.focus_set)
        self.busy = False

    def _button(self, parent, text, color, command, side):
        b = tk.Label(parent, text=text, bg=BUTTON, fg=color, font=("Segoe UI", 10, "bold"), padx=14, pady=4,
                     cursor="hand2")
        b.pack(side=side, padx=(8, 0) if side == "right" else (0, 8))
        b.bind("<Button-1>", lambda e: command())
        return b

    def _report(self):
        return build(self.cfg, self.note.get("1.0", "end"), self.reason, self.handle)

    def _show(self):
        path = config.CONFIG_DIR / "report-preview.txt"
        try:
            path.write_text(preview(self._report()), encoding="utf-8")
            os.startfile(path)
        except OSError as e:
            self.status.configure(text=f"Couldn't open the preview: {e}", fg=ACCENTS["warn"])

    def _send(self):
        if self.busy:
            return
        self.busy = True
        self.status.configure(text="Sending…", fg=MUTED)
        report = self._report()
        threading.Thread(target=lambda: self.post(self._sent, *send(report)), daemon=True, name="Report").start()

    def _sent(self, ok, message):
        self.busy = False
        try:
            self.status.configure(text=message, fg=ACCENTS["on"] if ok else ACCENTS["warn"])
        except tk.TclError:
            return  # closed while sending
        if ok:
            self.win.after(1500, self.close)

    def close(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        self.on_close()
