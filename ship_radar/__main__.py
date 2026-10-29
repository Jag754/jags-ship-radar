"""Entry point: `python -m ship_radar` or the packaged JagsShipRadar.exe."""

import argparse
import ctypes
import logging
import logging.handlers
import sys

from . import __version__, config


def _setup_logging(console):
    config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    handlers = [logging.handlers.RotatingFileHandler(config.CONFIG_DIR / "app.log", maxBytes=1_000_000,
                                                     backupCount=2, encoding="utf-8")]
    if console and sys.stderr:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)


def _single_instance():
    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\JagsShipRadar.SingleInstance")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def console_replay(path, cfg):
    """Print what the app would show for an old log, using the log's own timestamps. No window."""
    from .app import make_batcher
    from .parser import LineParser
    from .tracker import Tracker

    parser, tracker, batcher = LineParser(cfg["ship_line_regex"]), Tracker(cfg), make_batcher(cfg)

    def show(alerts, summary):
        t = alerts[0].ts.strftime("%H:%M:%S")
        if summary:
            print(f"{t}  SUMMARY  {len(alerts)} ships: " + ", ".join(a.name for a in alerts))
        for a in [] if summary else alerts:
            tags = (" PRIORITY" if a.priority else "") + (f" RE-PING x{a.count}" if a.is_reping else "")
            print(f"{t}  {a.name}{tags}")

    now = 0.0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            event = parser.parse(line)
            if not event:
                continue
            now = event.ts.timestamp()
            ready = batcher.flush_due(now)
            if ready:
                show(*ready)
            alert = tracker.feed(event)
            if alert:
                group = batcher.add(alert, now)
                if group:
                    show(group, False)
    ready = batcher.flush_due(now + 3600)
    if ready:
        show(*ready)


def main():
    ap = argparse.ArgumentParser(prog="JagsShipRadar", description="Ship arrival alerts for Star Citizen.")
    ap.add_argument("--replay", metavar="GAME_LOG", help="play an old Game.log through the app as if live")
    ap.add_argument("--speed", type=float, default=20.0, help="replay speed multiplier (default 20)")
    ap.add_argument("--console", action="store_true", help="with --replay: print alerts instead of showing them")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args()

    _setup_logging(args.console)
    cfg = config.load()

    if args.replay and args.console:
        console_replay(args.replay, cfg)
        return

    if not args.replay and not _single_instance():
        ctypes.windll.user32.MessageBoxW(None, "Jag's Ship Radar is already running. Look for it in the system tray.",
                                         "Jag's Ship Radar", 0x40)
        return

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass

    from .app import App
    logging.getLogger(__name__).info("Jag's Ship Radar %s starting", __version__)
    App(cfg, replay=args.replay, speed=args.speed).run()


if __name__ == "__main__":
    main()
