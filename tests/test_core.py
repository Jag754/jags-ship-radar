import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta

from ship_radar import config, hotkey, ships
from ship_radar.parser import ChannelJoined, LineParser, LoggedIn, ShipSeen
from ship_radar.tailer import LogTailer
from ship_radar.tracker import Alert, Batcher, Tracker

SHIP_LINE = ("<2026-10-28T01:15:18.475Z> [Notice] <ATC_Reset_VehiclesBeingStoredCleared> ATC "
             "'AEGS_Idris_ShipATCDataManager_905844157977' [905844157977] clearing 0 entries from "
             "vehicles-being-stored list on Reset [Team_MissionFeatures][ATC]")
STATION_LINE = ("<2026-10-28T01:15:19.000Z> [Notice] <ATC_Reset_VehiclesBeingStoredCleared> ATC "
                "'ATC_Lorville_Station_123' [123] clearing 0 entries")
CHANNEL_LINE = ("<2026-10-28T01:16:00.000Z> [Notice] <UpdateNotificationItem> Notification "
                "\"You have joined channel 'Drake Cutlass Blue : TamaleZ'.")
LOGIN_LINE = ("<2026-10-28T01:09:07.304Z> [Notice] <Legacy login response> [CIG-net] User Login Success "
              "- Handle[CaptnJoe] - Time[164769578]")
T0 = datetime(2026, 10, 28, 1, 0, 0)


def ship(code, sid, sec):
    return ShipSeen(T0 + timedelta(seconds=sec), code, sid)


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.p = LineParser(config.DEFAULT_SHIP_REGEX)

    def test_ship_line(self):
        ev = self.p.parse(SHIP_LINE)
        self.assertEqual((ev.code, ev.ship_id), ("AEGS_Idris", "905844157977"))
        self.assertEqual(ev.ts, datetime(2026, 10, 28, 1, 15, 18, 475000))

    def test_station_is_not_a_ship(self):
        self.assertIsNone(self.p.parse(STATION_LINE))

    def test_channel_and_login(self):
        ch = self.p.parse(CHANNEL_LINE)
        self.assertIsInstance(ch, ChannelJoined)
        self.assertEqual((ch.ship, ch.owner), ("Drake Cutlass Blue", "TamaleZ"))
        self.assertEqual(self.p.parse(LOGIN_LINE), LoggedIn(datetime(2026, 10, 28, 1, 9, 7, 304000), "CaptnJoe"))


class ShipNameTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(ships.pretty_name("ANVL_Hornet"), "Anvil Hornet")
        self.assertEqual(ships.pretty_name("ORIG_m80"), "Origin M80")
        self.assertEqual(ships.pretty_name("Krig_l22_alphawolf"), "Kruger L-22 Alpha Wolf")
        self.assertEqual(ships.pretty_name("XYZ_New_Ship"), "XYZ New Ship")
        self.assertEqual(ships.pretty_name("ANVL_Hornet", {"ANVL_Hornet": "Hornet!"}), "Hornet!")


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.t = Tracker(dict(config.DEFAULTS))

    def test_reping_is_marked(self):
        a1 = self.t.feed(ship("ANVL_Hornet", "1", 0))
        a2 = self.t.feed(ship("ANVL_Hornet", "1", 300))
        self.assertFalse(a1.is_reping)
        self.assertTrue(a2.is_reping)
        self.assertEqual((a2.count, a2.first_seen), (2, T0))

    def test_repings_can_be_hidden(self):
        self.t.reload({**config.DEFAULTS, "show_repings": False})
        self.t.feed(ship("ANVL_Hornet", "1", 0))
        self.assertIsNone(self.t.feed(ship("ANVL_Hornet", "1", 5)))

    def test_ship_you_board_goes_quiet(self):
        self.assertIsNotNone(self.t.feed(ship("DRAK_Cutlass", "7", 0)))
        self.t.feed(ChannelJoined(T0 + timedelta(seconds=20), "Drake Cutlass Blue", "TamaleZ"))
        self.assertIsNone(self.t.feed(ship("DRAK_Cutlass", "7", 400)))
        self.assertIsNotNone(self.t.feed(ship("DRAK_Cutlass", "8", 401)), "another Cutlass still pings")

    def test_channel_before_ship(self):
        self.t.feed(ChannelJoined(T0, "Aegis Idris-P", "Zenairis"))
        self.assertIsNone(self.t.feed(ship("AEGS_Idris", "9", 10)))

    def test_ignore_and_priority(self):
        self.t.reload({**config.DEFAULTS, "ignore": ["pisces"], "priority": ["Hornet"]})
        self.assertIsNone(self.t.feed(ship("ANVL_Pisces_Rescue", "1", 0)))
        self.assertTrue(self.t.feed(ship("ANVL_Hornet", "2", 0)).priority)


def alert(priority=False):
    return Alert(T0, "ANVL_Hornet", "1", "Anvil Hornet", 1, T0, priority)


class BatcherTests(unittest.TestCase):
    def test_single_ship_shows_after_window(self):
        b = Batcher(1.5, 6, 4)
        b.add(alert(), 0)
        self.assertIsNone(b.flush_due(1.0))
        group, summary = b.flush_due(1.6)
        self.assertEqual((len(group), summary), (1, False))

    def test_groups_and_bursts(self):
        b = Batcher(1.5, 6, 4)
        b.add(alert(), 0)
        group, summary = b.flush_due(2)
        self.assertEqual((len(group), summary), (1, False))
        for i in range(6):
            b.add(alert(), 10 + i * 0.2)
        group, summary = b.flush_due(13)
        self.assertEqual((len(group), summary), (6, True))
        # Still busy: two more ships 5s later get summarized together, not shown one by one.
        b.add(alert(), 17)
        b.add(alert(), 20)
        self.assertIsNone(b.flush_due(22), "burst mode waits longer")
        group, summary = b.flush_due(29)
        self.assertEqual((len(group), summary), (2, True))
        # Priority ships skip the wait during a burst.
        self.assertEqual(len(b.add(alert(priority=True), 30)), 1)
        # Quiet for longer than burst_hold: back to normal.
        b.add(alert(), 80)
        self.assertFalse(b.in_burst(80))
        group, summary = b.flush_due(82)
        self.assertEqual((len(group), summary), (1, False))


class PlacementTests(unittest.TestCase):
    def test_nearest_corner(self):
        from ship_radar.overlay import corner_placement
        # 1920x1080 at 150% DPI; offsets are stored in unscaled pixels.
        self.assertEqual(corner_placement(1300, 180, 570, 200, 1920, 1080, 1.5),
                         {"position": "top-right", "offset_x": 33, "offset_y": 120})
        self.assertEqual(corner_placement(30, 700, 570, 200, 1920, 1080, 1.5),
                         {"position": "bottom-left", "offset_x": 20, "offset_y": 120})
        self.assertEqual(corner_placement(-5, -5, 570, 200, 1920, 1080, 1.0)["offset_x"], 0)


class GameWatchTests(unittest.TestCase):
    def test_sees_running_processes(self):
        from ship_radar import gamewatch
        import sys
        self.assertIn(os.path.basename(sys.executable).lower(), gamewatch.process_names())


class SoundTests(unittest.TestCase):
    def setUp(self):
        from pathlib import Path
        from unittest import mock
        from ship_radar import sound
        self.sound = sound
        self.dir = Path(tempfile.mkdtemp())
        patcher = mock.patch.object(sound, "CONFIG_DIR", self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def peak(self, path):
        import array
        import wave
        with wave.open(str(path), "rb") as w:
            return max(abs(v) for v in array.array("h", w.readframes(w.getnframes())))

    def test_volume_and_mute(self):
        from unittest import mock
        loud = self.sound.Sounds({**config.DEFAULTS, "volume": 1.0})
        quiet = self.sound.Sounds({**config.DEFAULTS, "volume": 0.2})
        self.assertAlmostEqual(self.peak(quiet.normal) / self.peak(loud.normal), 0.2, places=2)
        muted = self.sound.Sounds({**config.DEFAULTS, "sound": False})
        with mock.patch.object(self.sound.winsound, "PlaySound") as play:
            muted.play()
            self.assertFalse(play.called)

    def test_own_wav_follows_volume(self):
        own = self.dir / "mine.wav"
        self.sound._write(own, (500,), 1.0)
        s = self.sound.Sounds({**config.DEFAULTS, "volume": 0.4, "sound_file": str(own)})
        self.assertNotEqual(s.normal, own)
        self.assertAlmostEqual(self.peak(s.normal) / self.peak(own), 0.4, places=2)


class SpeechTests(unittest.TestCase):
    def alert(self, name, priority=False, count=1):
        return Alert(T0, "X", "1", name, count, T0, priority)

    def test_what_gets_said(self):
        from ship_radar.speech import group_line
        hornet, idris = self.alert("Anvil Hornet"), self.alert("Aegis Idris", priority=True)
        again = self.alert("Drake Cutlass", count=2)
        self.assertIsNone(group_line([hornet], False, "off"))
        self.assertIsNone(group_line([hornet], False, "priority"))
        self.assertEqual(group_line([hornet], False, "all"), "Anvil Hornet")
        self.assertIsNone(group_line([again], False, "all"))
        self.assertEqual(group_line([hornet, idris, again], False, "priority"), "Priority contact, Aegis Idris")
        self.assertEqual(group_line([hornet, idris, again], False, "all"), "Priority contact, Aegis Idris. Anvil Hornet")
        self.assertEqual(group_line([self.alert(n) for n in "ABCDE"], False, "all"), "A, B, C, and 2 more")

    def test_busy_area(self):
        from ship_radar.speech import group_line
        crowd = [self.alert("Anvil Hornet")] * 5
        self.assertIsNone(group_line(crowd, True, "priority"))
        self.assertEqual(group_line(crowd, True, "all"), "Busy area, 5 ships")
        crowd += [self.alert("Aegis Idris", True), self.alert("Aegis Javelin", True), self.alert("Aegis Idris", True)]
        self.assertEqual(group_line(crowd, True, "priority"), "Busy area, 8 ships, including Aegis Idris and Aegis Javelin")

    def test_muted_and_missing_voice(self):
        from unittest import mock
        from ship_radar import speech
        with mock.patch.object(speech.Speech, "_create", lambda self: setattr(self, "voice", mock.Mock()) or True):
            s = speech.Speech({**config.DEFAULTS, "sound": False})
            s.say("hello")
            self.assertFalse(s.voice.Speak.called)
            s.reload({**config.DEFAULTS, "volume": 0.4})
            self.assertEqual(s.voice.Volume, 64)
            s.reload({**config.DEFAULTS, "volume": 1.0})
            self.assertEqual(s.voice.Volume, 100)
            s.say("hello")
            self.assertTrue(s.voice.Speak.called)
        with mock.patch.dict("sys.modules", {"comtypes": None, "comtypes.client": None}):
            s = speech.Speech(config.DEFAULTS)
            self.assertEqual(s.mode, "off")
            s.say("hello")  # no voice, no error


class NearbyTests(unittest.TestCase):
    def test_list_groups_ages_out_and_sorts(self):
        from ship_radar.nearby import RecentShips
        r = RecentShips(10)
        t = Tracker(dict(config.DEFAULTS, show_repings=False))
        t.on_seen = r.add
        t.feed(ship("ANVL_Hornet", "1", 0))
        t.feed(ship("AEGS_Idris", "2", 60))
        t.feed(ship("DRAK_Cutlass_Black", "3", 120))
        t.feed(ship("ANVL_Hornet", "4", 200))
        self.assertIsNone(t.feed(ship("ANVL_Hornet", "1", 300)))  # a hidden re-ping still refreshes the list
        rows = r.rows(T0 + timedelta(seconds=330))
        self.assertEqual([(x.name, x.ships, x.age, x.dim) for x in rows],
                         [("Aegis Idris", 1, 270, True), ("Anvil Hornet", 2, 30, False),
                          ("Drake Cutlass Black", 1, 210, True)])
        rows = r.rows(T0 + timedelta(seconds=700), aboard={"3"})
        self.assertEqual([(x.name, x.ships) for x in rows], [("Anvil Hornet", 2)])  # Idris aged out, Cutlass is yours
        self.assertNotIn("2", r.ships)

    def test_short_age(self):
        from ship_radar.nearby import short_age
        self.assertEqual([short_age(n) for n in (5, 40, 125, 3700)], ["now", "40s", "2m", "1h 1m"])


class HotkeyTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(hotkey.parse("ctrl+shift+f8"), (0x2 | 0x4, 0x77))
        self.assertEqual(hotkey.parse("Alt + K"), (0x1, ord("K")))
        with self.assertRaises(ValueError):
            hotkey.parse("ctrl+shift")

    def test_key_names_round_trip(self):
        for name in ("a", "7", "f8", "f24", "num5", "pageup", "scrolllock"):
            self.assertEqual(hotkey.key_name(hotkey.parse(name)[1]), name)
        self.assertIsNone(hotkey.key_name(0x10))  # Shift on its own

    def test_check(self):
        self.assertIn("Add Ctrl", hotkey.check("k"))
        self.assertIn("Unknown key", hotkey.check("ctrl+banana"))
        self.assertIsNone(hotkey.check("ctrl+alt+shift+f23"))


class TailerTests(unittest.TestCase):
    def test_follows_appends_and_new_session(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "Game.log")
        with open(path, "w") as f:
            f.write("old line 1\nold line 2\n")
        got, new_files = [], []
        t = LogTailer(lambda: path, lambda lines, live: got.extend((l, live) for l in lines),
                      new_files.append, lambda s: None, catch_up=True, poll=0.05)
        t.start()
        try:
            time.sleep(0.3)
            with open(path, "a") as f:
                f.write("live 1\npart")
            time.sleep(0.3)
            with open(path, "a") as f:
                f.write("ial\n")
            time.sleep(0.3)
            # Game relaunch: old log is renamed away while we hold it open, a new one appears.
            os.replace(path, os.path.join(d, "Game-backup.log"))
            with open(path, "w") as f:
                f.write("new session\n")
            time.sleep(0.5)
        finally:
            t.stop()
        self.assertEqual(got, [("old line 1", False), ("old line 2", False), ("live 1", True),
                               ("partial", True), ("new session", True)])
        self.assertEqual(len(new_files), 2)


if __name__ == "__main__":
    unittest.main()
