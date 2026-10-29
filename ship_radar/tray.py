"""System tray icon and menu."""

import threading

import pystray
from PIL import Image, ImageDraw


def make_icon(on=True, size=64):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ring = (63, 182, 255, 255) if on else (140, 151, 166, 255)
    d.ellipse((2, 2, size - 3, size - 3), fill=(16, 21, 28, 255), outline=ring, width=max(2, size // 16))
    d.ellipse((size * 0.28, size * 0.28, size * 0.72, size * 0.72), outline=ring, width=max(1, size // 24))
    d.line((size / 2, size / 2, size * 0.82, size * 0.22), fill=ring, width=max(2, size // 20))
    if on:
        d.ellipse((size * 0.6, size * 0.3, size * 0.72, size * 0.42), fill=(255, 77, 77, 255))
    return img


VOLUME_STEPS = (100, 80, 60, 40, 20, 10)
SPEECH_CHOICES = (("off", "Off"), ("priority", "Priority ships only"), ("all", "All new ships"))


def volume_item(app, pct):
    return pystray.MenuItem(f"Volume {pct}%", lambda: app.post(app.set_volume, pct / 100), radio=True,
                            checked=lambda _: round(float(app.cfg["volume"]) * 100) == pct)


def speech_item(app, mode, label):
    return pystray.MenuItem(label, lambda: app.post(app.set_speech, mode), radio=True,
                            checked=lambda _: app.cfg.get("speech", "all") == mode)


class Tray:
    """Menu callbacks run on the tray thread; `post` hands them to the UI thread."""

    def __init__(self, app):
        self.app = app
        p = app.post
        menu = pystray.Menu(
            pystray.MenuItem(lambda _: f"Alerts on  ({app.cfg['hotkey']})", lambda: p(app.toggle),
                             checked=lambda _: app.enabled, default=True),
            pystray.MenuItem("Show test alert", lambda: p(app.test_alert)),
            pystray.MenuItem("Move / resize alerts…", lambda: p(app.place_overlay)),
            pystray.MenuItem(lambda _: "Nearby ships list" + (f"  ({app.cfg['nearby_hotkey']})" if app.cfg.get("nearby_hotkey") else ""),
                             lambda: p(app.toggle_nearby), checked=lambda _: bool(app.cfg["nearby_list"])),
            pystray.MenuItem("Move / resize nearby list…", lambda: p(app.place_nearby)),
            pystray.MenuItem("Change hotkey…", lambda: p(app.change_hotkey)),
            pystray.MenuItem("Sound", pystray.Menu(
                pystray.MenuItem("Mute pings", lambda: p(app.toggle_mute), checked=lambda _: not app.cfg["sound"]),
                pystray.Menu.SEPARATOR,
                *(volume_item(app, pct) for pct in VOLUME_STEPS),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Speak ship names", pystray.Menu(
                    *(speech_item(app, mode, label) for mode, label in SPEECH_CHOICES),
                )),
            )),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda _: f"Install update v{app.update_manifest.version}" if app.update_manifest else "",
                             lambda: p(app.install_update), visible=lambda _: app.update_manifest is not None),
            pystray.MenuItem("Check for updates", lambda: p(app.check_updates)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda _: f"Watching: {app.log_label()}", None, enabled=False),
            pystray.MenuItem("Choose Game.log…", lambda: p(app.choose_log)),
            pystray.MenuItem("Open settings file", lambda: p(app.open_settings)),
            pystray.MenuItem("Reload settings", lambda: p(app.reload_settings)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda: p(app.quit)),
        )
        self.icon = pystray.Icon("JagsShipRadar", make_icon(True), "Jag's Ship Radar", menu)
        self.thread = threading.Thread(target=self.icon.run, daemon=True, name="Tray")

    def start(self):
        self.thread.start()

    def set_enabled(self, on):
        self.icon.icon = make_icon(on)
        self.icon.title = f"Jag's Ship Radar ({'on' if on else 'off'})"
        self.icon.update_menu()

    def refresh(self):
        self.icon.update_menu()

    def stop(self):
        self.icon.stop()
