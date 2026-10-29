"""Pick the lines we care about out of Game.log."""

import re
from dataclasses import dataclass
from datetime import datetime, timezone

TS_RE = re.compile(r"^<(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?)Z?>")
CHANNEL_RE = re.compile(r"<UpdateNotificationItem> Notification \"You have joined channel '(?P<ship>.+?) : (?P<owner>[^']+)'")
LOGIN_RE = re.compile(r"User Login Success - Handle\[(?P<handle>[^\]]+)\]")


@dataclass
class ShipSeen:
    ts: datetime
    code: str
    ship_id: str


@dataclass
class ChannelJoined:
    ts: datetime
    ship: str
    owner: str


@dataclass
class LoggedIn:
    ts: datetime
    handle: str


class LineParser:
    def __init__(self, ship_regex):
        self.ship_re = re.compile(ship_regex)
        self.last_ts = datetime.now(timezone.utc).replace(tzinfo=None)

    def _ts(self, line):
        m = TS_RE.match(line)
        if m:
            try:
                self.last_ts = datetime.fromisoformat(m.group(1))
            except ValueError:
                pass
        return self.last_ts

    def parse(self, line):
        if "ShipATCDataManager" in line or "ATC '" in line:
            m = self.ship_re.search(line)
            if m:
                return ShipSeen(self._ts(line), m.group("code"), m.group("id"))
        if "You have joined channel" in line:
            m = CHANNEL_RE.search(line)
            if m:
                return ChannelJoined(self._ts(line), m.group("ship"), m.group("owner"))
        if "User Login Success" in line:
            m = LOGIN_RE.search(line)
            if m:
                return LoggedIn(self._ts(line), m.group("handle"))
        return None
