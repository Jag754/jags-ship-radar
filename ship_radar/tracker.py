"""Decide which ship lines become alerts: re-pings, your own ship, ignore and priority lists."""

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import ships
from .parser import ChannelJoined, LoggedIn, ShipSeen

# A "joined channel" line and the ship it belongs to land within this long of each other.
OWN_SHIP_MATCH_WINDOW = timedelta(seconds=90)


@dataclass
class Alert:
    ts: datetime
    code: str
    ship_id: str
    name: str
    count: int
    first_seen: datetime
    priority: bool

    @property
    def is_reping(self):
        return self.count > 1


class Tracker:
    def __init__(self, cfg):
        # Called with every ship that isn't yours or ignored, re-pings included (the nearby list).
        self.on_seen = None
        self.reload(cfg)
        self.reset()

    def reload(self, cfg):
        self.ignore = [s.lower() for s in cfg.get("ignore", []) if s]
        self.priority = [s.lower() for s in cfg.get("priority", []) if s]
        self.overrides = cfg.get("name_overrides") or {}
        self.show_repings = cfg.get("show_repings", True)

    def reset(self):
        """Forget everything; called when the game starts a new Game.log."""
        self.seen = {}
        self.aboard = set()
        self.handle = None
        self.recent_ships = deque(maxlen=60)
        self.recent_channels = deque(maxlen=10)

    def _matches(self, needles, code, name):
        hay = f"{code} {name}".lower()
        return any(n in hay for n in needles)

    def _channel_matches(self, channel_ship, code):
        want = ships.model_tokens(code, self.overrides)
        return bool(want) and want <= ships.tokens(channel_ship)

    def feed(self, event):
        if isinstance(event, LoggedIn):
            self.handle = event.handle
            return None

        if isinstance(event, ChannelJoined):
            self.recent_channels.append(event)
            # The ship you boarded usually loaded just before the channel line.
            for ship in reversed(self.recent_ships):
                if event.ts - ship.ts > OWN_SHIP_MATCH_WINDOW:
                    break
                if self._channel_matches(event.ship, ship.code):
                    self.aboard.add(ship.ship_id)
                    break
            return None

        if not isinstance(event, ShipSeen):
            return None

        info = self.seen.get(event.ship_id)
        if info is None:
            info = self.seen[event.ship_id] = {"count": 0, "first": event.ts}
        info["count"] += 1
        self.recent_ships.append(event)

        for ch in reversed(self.recent_channels):
            if event.ts - ch.ts > OWN_SHIP_MATCH_WINDOW:
                break
            if self._channel_matches(ch.ship, event.code):
                self.aboard.add(event.ship_id)
                break

        name = ships.pretty_name(event.code, self.overrides)
        if event.ship_id in self.aboard or self._matches(self.ignore, event.code, name):
            return None
        alert = Alert(
            ts=event.ts,
            code=event.code,
            ship_id=event.ship_id,
            name=name,
            count=info["count"],
            first_seen=info["first"],
            priority=self._matches(self.priority, event.code, name),
        )
        if self.on_seen:
            self.on_seen(alert)
        if alert.is_reping and not self.show_repings:
            return None
        return alert


class Batcher:
    """Groups alerts that arrive close together so a station full of parked ships is one alert.

    Arriving somewhere busy loads ships in over a minute or two, not all at once. After a group
    bigger than `threshold`, the batcher stays in burst mode: it uses a longer window and keeps
    summarizing until ships stop arriving for `burst_hold` seconds. Priority ships skip the wait.
    """

    def __init__(self, window, max_wait, threshold, burst_window=8.0, burst_max_wait=20.0, burst_hold=30.0):
        self.window = window
        self.max_wait = max_wait
        self.threshold = threshold
        self.burst_window = burst_window
        self.burst_max_wait = burst_max_wait
        self.burst_hold = burst_hold
        self.pending = []
        self.start = self.last = 0.0
        self.burst_until = 0.0

    def in_burst(self, now):
        return now < self.burst_until

    def add(self, alert, now):
        """Returns a group to show right away (a priority ship during a burst), else None."""
        if self.in_burst(now):
            self.burst_until = now + self.burst_hold
            if alert.priority:
                return [alert]
        if not self.pending:
            self.start = now
        self.pending.append(alert)
        self.last = now
        return None

    def flush_due(self, now):
        """Returns (alerts, is_summary) when a group is ready, else None."""
        if not self.pending:
            return None
        burst = self.in_burst(now)
        window, max_wait = (self.burst_window, self.burst_max_wait) if burst else (self.window, self.max_wait)
        if now - self.last < window and now - self.start < max_wait:
            return None
        out, self.pending = self.pending, []
        if len(out) > self.threshold:
            burst = True
            self.burst_until = now + self.burst_hold
        return out, burst and len(out) > 1
