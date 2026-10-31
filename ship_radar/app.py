"""Wires the log reader, tracker, overlay, hotkey and tray together. All state lives on the Tk thread."""

import logging
import os
import queue
import threading
import time
import tkinter as tk
from collections import Counter
from datetime import datetime, timedelta, timezone
from tkinter import filedialog

from . import __version__, config, gamewatch, logfind
from .hotkey import Hotkey
from .nearby import NearbyPanel, RecentShips
from .overlay import ago, local_time, Overlay
from .parser import LineParser, TS_RE
from .sound import Sounds
from .speech import group_line, Speech
from .tailer import LogTailer
from .tracker import Batcher, Tracker
from .tray import Tray

log = logging.getLogger(__name__)
PRIORITY_COLOR = "#ff6b6b"
FIRST_UPDATE_CHECK_MS = 30_000
UPDATE_CHECK_EVERY_MS = 6 * 3600_000
GAME_CHECK_MS = 3000
# Let the ping finish before the voice starts (built-in pings are about 0.25 s, priority 0.5 s).
SPEAK_AFTER_MS = {"normal": 300, "priority": 550, "status": 150}


def make_batcher(cfg):
    return Batcher(float(cfg["batch_window_seconds"]), float(cfg["batch_max_wait_seconds"]),
                   int(cfg["burst_threshold"]))


class App:
    def __init__(self, cfg, replay=None, speed=20.0):
        self.cfg = cfg
        self.q = queue.Queue()
        self.root = tk.Tk()
        self.root.withdraw()
        self.overlay = Overlay(self.root, cfg)
        self.sounds = Sounds(cfg)
        self.speech = Speech(cfg)
        self.parser = LineParser(cfg["ship_line_regex"])
        self.tracker = Tracker(cfg)
        self.recent = RecentShips(cfg["nearby_minutes"])
        self.tracker.on_seen = self.recent.add
        self.log_clock = None
        self.nearby = NearbyPanel(self.root, self.recent, self._now, lambda: self.tracker.aboard)
        self.nearby.visible = bool(cfg["nearby_list"])
        self.batcher = make_batcher(cfg)
        self.enabled = bool(cfg["enabled_on_start"])
        self.log_path = None
        self.replay = replay
        self.speed = speed
        self.updates = None
        self.update_manifest = None
        self.update_busy = False
        self.update_announced = None
        self.tray = Tray(self)
        self.hotkey = None
        self.nearby_hotkey = None
        self.picker = None
        # A replay has no game to wait for.
        self.game_running = bool(replay)
        self.source = None

    # ---- threading ----------------------------------------------------------

    def post(self, fn, *args):
        """Run fn(*args) on the UI thread. Safe to call from any thread."""
        self.q.put((fn, args))

    def _pump(self):
        deadline = time.monotonic() + 0.03
        while time.monotonic() < deadline:
            try:
                fn, args = self.q.get_nowait()
            except queue.Empty:
                break
            try:
                fn(*args)
            except Exception:
                log.exception("Error in %s", getattr(fn, "__name__", fn))
        ready = self.batcher.flush_due(time.monotonic())
        if ready:
            self._show_group(*ready)
        self.root.after(50, self._pump)

    # ---- lifecycle ----------------------------------------------------------

    def run(self):
        self.tray.start()
        self.nearby.apply(self.cfg)
        if not self.replay:
            self.game_running = gamewatch.game_running()
            self.root.after(GAME_CHECK_MS, self._watch_game)
        self._sync_hotkey()
        self._start_source()
        self.root.after(50, self._pump)
        when = "" if self.game_running else " while Star Citizen is running"
        self.overlay.show("on", "Jag's Ship Radar running", f"Alerts {'ON' if self.enabled else 'OFF'}",
                          f"{self.cfg['hotkey'].upper()} turns alerts on and off{when}", seconds=4)
        if not self.replay and self.cfg.get("check_for_updates", True):
            self.root.after(FIRST_UPDATE_CHECK_MS, self._scheduled_update_check)
        self.root.mainloop()

    def _watch_game(self):
        running = gamewatch.game_running()
        if running != self.game_running:
            self.game_running = running
            log.info("Star Citizen %s", "started" if running else "closed")
            self._sync_hotkey()
        self.root.after(GAME_CHECK_MS, self._watch_game)

    def _sync_hotkey(self, restart=False):
        """Hold the hotkeys only while the game runs, so the keys are free for everything else otherwise."""
        want = self.game_running and not self.picker
        for attr, combo, action in (("hotkey", self.cfg["hotkey"], self.toggle),
                                    ("nearby_hotkey", self.cfg.get("nearby_hotkey", ""), self.toggle_nearby)):
            current = getattr(self, attr)
            if current and (restart or not want):
                current.stop()
                current = None
                setattr(self, attr, None)
            if want and combo and not current:
                hk = Hotkey(combo, lambda action=action: self.post(action), lambda msg: self.post(self._warn, msg))
                hk.start()
                setattr(self, attr, hk)

    def _start_source(self):
        if self.replay:
            self.source = Replay(self.replay, self.speed, self._on_lines_thread)
            self.log_path = self.replay
        else:
            self.source = LogTailer(self._resolve, self._on_lines_thread,
                                    lambda p: self.post(self._new_file, p),
                                    lambda msg: self.post(self._warn, msg),
                                    catch_up=bool(self.cfg["catch_up_existing_log"]))
        self.source.start()

    def _resolve(self):
        return logfind.resolve(self.cfg.get("log_path", ""))

    # ---- updates ------------------------------------------------------------
    # Network and hashing run on a worker thread; results come back through post().

    def _update_service(self):
        if self.updates is None:
            from .update.service import UpdateService
            self.updates = UpdateService(__version__, str(config.CONFIG_DIR))
        return self.updates

    def _scheduled_update_check(self):
        self.check_updates(manual=False)
        self.root.after(UPDATE_CHECK_EVERY_MS, self._scheduled_update_check)

    def check_updates(self, manual=True):
        if self.update_busy or self.replay:
            return
        self.update_busy = True
        if manual:
            self.overlay.show("on", "Jag's Ship Radar", "Checking for updates…", seconds=2.5)
        service = self._update_service()
        threading.Thread(target=lambda: self.post(self._on_update_check, service.check(), manual),
                         daemon=True, name="UpdateCheck").start()

    def _on_update_check(self, result, manual):
        self.update_busy = False
        log.info("Update check: %s", result.message)
        if result.rejected:
            # A bad signature or replayed manifest is never kept quiet.
            self.overlay.show("warn", "Update refused", "Jag's Ship Radar", result.message, seconds=12)
            return
        if result.available:
            self.update_manifest = result.manifest
            self.tray.refresh()
            if manual or self.update_announced != result.manifest.version:
                self.update_announced = result.manifest.version
                notes = [(line, None) for line in result.manifest.notes.splitlines()[:3] if line.strip()]
                self.overlay.show("summary", f"Update available · v{result.manifest.version}",
                                  "Jag's Ship Radar", "Tray icon → Install update", notes, seconds=10)
        elif manual:
            self.overlay.show("warn" if result.failed else "on", "Jag's Ship Radar", result.message, seconds=5)

    def install_update(self):
        if self.update_busy or not self.update_manifest:
            return
        self.update_busy = True
        manifest, service = self.update_manifest, self._update_service()
        self.overlay.show("on", f"Updating to v{manifest.version}", "Downloading update…", seconds=4)

        def work():
            try:
                path = service.download(manifest)
            except Exception as exc:
                log.exception("update download failed")
                self.post(self._on_update_downloaded, None, str(exc))
            else:
                self.post(self._on_update_downloaded, path, None)

        threading.Thread(target=work, daemon=True, name="UpdateDownload").start()

    def _on_update_downloaded(self, path, error):
        self.update_busy = False
        if error:
            self.overlay.show("warn", "Update failed", "Jag's Ship Radar", error, seconds=10)
            return
        from .update.service import UpdateService
        try:
            UpdateService.launch_installer(path)
        except Exception as exc:
            self.overlay.show("warn", "Update failed", "Jag's Ship Radar", str(exc), seconds=10)
            return
        # The installer replaces this exe, then starts the new one (installer.iss, RESTARTRADAR).
        self.quit()

    def quit(self):
        for part in (self.source, self.hotkey, self.nearby_hotkey, self.tray):
            try:
                part and part.stop()
            except Exception:
                log.exception("Stopping %s", part)
        self.root.destroy()

    # ---- log handling -------------------------------------------------------

    def _on_lines_thread(self, lines, live):
        self.post(self._on_lines, lines, live)

    def _new_file(self, path):
        log.info("New game log: %s", path)
        self.log_path = str(path)
        self.tracker.reset()
        self.recent.clear()
        self.tray.refresh()

    def _on_lines(self, lines, live):
        for line in lines:
            event = self.parser.parse(line)
            if event is None:
                continue
            self.log_clock = (event.ts, time.monotonic())
            alert = self.tracker.feed(event)
            if alert is None or not live or not self.enabled:
                continue
            log.info("Ship: %s %s x%d%s", alert.name, alert.ship_id, alert.count, " [priority]" if alert.priority else "")
            now_group = self.batcher.add(alert, time.monotonic())
            if now_group:
                self._show_group(now_group, False)

    def _now(self):
        """The time the nearby list measures ages against: the log's own clock when replaying."""
        if self.replay and self.log_clock:
            ts, mono = self.log_clock
            return ts + timedelta(seconds=(time.monotonic() - mono) * self.speed)
        return datetime.now(timezone.utc).replace(tzinfo=None)

    # ---- alerts -------------------------------------------------------------

    def _show_group(self, alerts, summary):
        if not self.enabled:
            return
        if summary:
            self._show_summary(alerts)
        else:
            for a in alerts:
                self._show_one(a)
        kind = "priority" if any(a.priority for a in alerts) else "normal"
        self.sounds.play(kind)
        self._say(group_line(alerts, summary, self.speech.mode), kind)

    def _say(self, text, after="normal"):
        if text:
            self.root.after(SPEAK_AFTER_MS[after], self.speech.say, text)

    def _show_one(self, a):
        reping = f"Re-ping ×{a.count}"
        if a.priority:
            kind, tag = "priority", "Priority contact" + (f" · {reping}" if a.is_reping else "")
        elif a.is_reping:
            kind, tag = "reping", reping
        else:
            kind, tag = "ship", "New contact"
        sub = local_time(a.ts)
        if a.is_reping:
            sub += f" · first seen {ago((a.ts - a.first_seen).total_seconds())}"
        sub += f" · ID …{a.ship_id[-5:]}"
        self.overlay.show(kind, tag, a.name, sub)

    def _show_summary(self, alerts):
        new = sum(1 for a in alerts if not a.is_reping)
        counts = Counter(a.name for a in alerts)
        prio = {a.name for a in alerts if a.priority}
        names = sorted(counts, key=lambda n: (n not in prio, -counts[n], n))
        shown = names[:6]
        lines = [(f"{n}{f'  ×{counts[n]}' if counts[n] > 1 else ''}", PRIORITY_COLOR if n in prio else None) for n in shown]
        if len(names) > len(shown):
            lines.append((f"+ {len(names) - len(shown)} more types", "#8c97a6"))
        sub = f"{local_time(alerts[-1].ts)} · {new} new · {len(alerts) - new} re-pings"
        kind = "priority" if prio else "summary"
        self.overlay.show(kind, f"Busy area · {len(alerts)} ships", f"{len(alerts)} ships loaded in", sub, lines,
                          seconds=float(self.cfg["toast_seconds"]) + 3)

    def _warn(self, msg):
        log.warning(msg)
        self.overlay.show("warn", "Jag's Ship Radar", msg, seconds=8)

    # ---- tray / hotkey actions ---------------------------------------------

    def toggle(self):
        self.enabled = not self.enabled
        if not self.enabled:
            self.batcher = make_batcher(self.cfg)
        elif not self.overlay.placer:
            # A fresh window always shows over the game, so Off then On fixes alerts gone missing.
            self.overlay.apply(self.cfg)
        self.tray.set_enabled(self.enabled)
        self.overlay.show("on" if self.enabled else "off", "Jag's Ship Radar",
                          f"Alerts {'ON' if self.enabled else 'OFF'}", seconds=2.5)
        self.sounds.play("status")
        if self.speech.mode != "off":
            self._say(f"Alerts {'on' if self.enabled else 'off'}", "status")

    def test_alert(self):
        from .tracker import Alert
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        alerts = [Alert(now, "ANVL_Hornet", "900000012345", "Anvil Hornet", 1, now, False),
                  Alert(now, "AEGS_Idris", "900000067890", "Aegis Idris", 3, now - timedelta(minutes=14), True)]
        for a in alerts:
            self._show_one(a)
        self.sounds.play("priority")
        self._say(group_line(alerts, False, self.speech.mode), "priority")

    def toggle_mute(self):
        self.cfg["sound"] = not self.cfg["sound"]
        self._sound_changed("Sound muted" if not self.cfg["sound"] else "Sound on")

    def set_volume(self, vol):
        self.cfg["volume"] = vol
        self.cfg["sound"] = True  # picking a volume unmutes
        self._sound_changed(f"Volume {round(vol * 100)}%")

    def set_speech(self, mode):
        self.cfg["speech"] = mode
        config.save(self.cfg)
        self.speech.reload(self.cfg)
        self.tray.refresh()
        if self.speech.mode != mode:
            self._warn("Text-to-speech isn't available on this PC. See app.log.")
            return
        text = {"off": "Speech off", "priority": "Speaking priority ships", "all": "Speaking all new ships"}[mode]
        self.overlay.show("on" if mode != "off" else "off", "Jag's Ship Radar", text, seconds=2.5)
        if mode != "off":
            self._say("Priority contact, Aegis Idris" if mode == "priority" else "Anvil Hornet", "status")

    def _sound_changed(self, text):
        config.save(self.cfg)
        self.sounds.reload(self.cfg)
        self.speech.reload(self.cfg)
        self.tray.refresh()
        self.overlay.show("on" if self.cfg["sound"] else "off", "Jag's Ship Radar", text, seconds=2.5)
        self.sounds.play("normal")  # a sample at the new level; silent when muted

    def change_hotkey(self):
        if self.picker:
            self.picker.win.lift()
            return
        from .hotkey_picker import HotkeyPicker
        self.picker = HotkeyPicker(self.root, self.cfg["hotkey"], self._on_hotkey_picked)
        # Let go of the current hotkey while recording, so pressing it again shows up in the picker.
        self._sync_hotkey()

    def _on_hotkey_picked(self, combo):
        self.picker = None
        if combo:
            self.cfg["hotkey"] = combo
            config.save(self.cfg)
            log.info("Hotkey changed to %s", combo)
            self.overlay.show("on", "Jag's Ship Radar", f"Hotkey is now {combo.upper()}",
                              "Turns alerts on and off" + ("" if self.game_running else " while Star Citizen is running"),
                              seconds=4)
        self._sync_hotkey()
        self.tray.refresh()

    def toggle_nearby(self):
        self.cfg["nearby_list"] = not self.cfg["nearby_list"]
        config.save(self.cfg)
        self.nearby.set_visible(self.cfg["nearby_list"])
        self.tray.refresh()

    def place_nearby(self):
        self.nearby.start_placing(self._on_nearby_placed)

    def _on_nearby_placed(self, placement):
        if not placement:
            return
        self.cfg.update(NearbyPanel.placement_settings(placement))
        config.save(self.cfg)
        self.nearby.apply(self.cfg)
        log.info("Nearby list moved: %s", placement)

    def place_overlay(self):
        self.overlay.start_placing(self._on_placed)

    def _on_placed(self, placement):
        if not placement:
            return
        self.cfg.update(placement)
        config.save(self.cfg)
        self.overlay.apply(self.cfg)
        log.info("Alerts moved: %s", placement)
        self.overlay.show("on", "Jag's Ship Radar", "Alerts moved",
                          f"{placement['position']} · size {round(placement['scale'] * 100)}%", seconds=3)

    def log_label(self):
        if not self.log_path:
            return "searching…"
        parts = os.path.normpath(self.log_path).split(os.sep)
        return os.sep.join(parts[-2:])

    def choose_log(self):
        start = os.path.dirname(self.log_path) if self.log_path else "C:\\"
        path = filedialog.askopenfilename(title="Choose Star Citizen Game.log", initialdir=start,
                                          filetypes=[("Game log", "Game.log"), ("Log files", "*.log")])
        if not path or self.replay:
            return
        self.cfg["log_path"] = os.path.normpath(path)
        config.save(self.cfg)
        self.source.rescan()

    def open_settings(self):
        config.save(self.cfg)
        os.startfile(config.CONFIG_PATH)

    def reload_settings(self):
        old = self.cfg
        self.cfg = config.load()
        self.tracker.reload(self.cfg)
        self.sounds.reload(self.cfg)
        self.speech.reload(self.cfg)
        self.batcher = make_batcher(self.cfg)
        self.parser.ship_re = LineParser(self.cfg["ship_line_regex"]).ship_re
        self.overlay.apply(self.cfg)
        self.nearby.visible = bool(self.cfg["nearby_list"])
        self.nearby.apply(self.cfg)
        if self.cfg["hotkey"] != old["hotkey"] or self.cfg["nearby_hotkey"] != old["nearby_hotkey"]:
            self._sync_hotkey(restart=True)
        if self.cfg.get("log_path") != old.get("log_path") and not self.replay:
            self.source.rescan()
        self.tray.refresh()
        self.overlay.show("on", "Jag's Ship Radar", "Settings reloaded", seconds=2.5)


class Replay(threading.Thread):
    """Feeds an old Game.log through the app as if it were live, sped up by `speed`."""

    def __init__(self, path, speed, on_lines, max_gap=3.0):
        super().__init__(daemon=True, name="Replay")
        self.path, self.speed, self.on_lines, self.max_gap = path, speed, on_lines, max_gap
        self._halt = threading.Event()

    def stop(self):
        self._halt.set()

    def run(self):
        prev = None
        with open(self.path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if self._halt.is_set():
                    return
                m = TS_RE.match(line)
                if m and self.speed > 0:
                    ts = datetime.fromisoformat(m.group(1))
                    if prev:
                        self._halt.wait(min(self.max_gap, max(0.0, (ts - prev).total_seconds() / self.speed)))
                    prev = ts
                self.on_lines([line.rstrip("\n")], True)
