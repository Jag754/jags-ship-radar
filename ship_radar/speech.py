"""Spoken callouts, using the voices built into Windows (SAPI)."""

import logging

log = logging.getLogger(__name__)

MODES = ("off", "priority", "all")
MAX_NAMES = 3
# Voices sound quieter than the pings at the same setting, so they run this much louder (capped at 100).
VOLUME_BOOST = 1.6

# SpeechVoiceSpeakFlags
SPEAK_ASYNC = 1
PURGE_BEFORE_SPEAK = 2  # a new callout cuts off the one still talking
IS_NOT_XML = 16


def _names(names):
    if len(names) > MAX_NAMES:
        return ", ".join(names[:MAX_NAMES]) + f", and {len(names) - MAX_NAMES} more"
    return " and ".join(names) if len(names) == 2 else ", ".join(names)


def group_line(alerts, summary, mode):
    """What to say for one group of alerts, or None to stay quiet."""
    if mode not in ("priority", "all") or not alerts:
        return None
    prio = list(dict.fromkeys(a.name for a in alerts if a.priority))
    if summary:
        if not prio and mode == "priority":
            return None
        line = f"Busy area, {len(alerts)} ships"
        return f"{line}, including {_names(prio)}" if prio else line
    parts = [f"Priority contact, {_names(prio)}"] if prio else []
    if mode == "all":
        new = list(dict.fromkeys(a.name for a in alerts if not a.priority and not a.is_reping))
        if new:
            parts.append(_names(new))
    return ". ".join(parts) or None


class Speech:
    def __init__(self, cfg):
        self.voice = None
        self.reload(cfg)

    def reload(self, cfg):
        mode = cfg.get("speech", "all")
        self.mode = mode if mode in MODES else "all"
        self.muted = not cfg.get("sound", True)
        if self.mode == "off":
            return
        if self.voice is None and not self._create():
            return
        try:
            vol = max(0.0, min(1.0, float(cfg.get("volume", 0.6))))
            self.voice.Volume = min(100, round(100 * vol * VOLUME_BOOST))
            self._pick_voice(cfg.get("voice", ""))
        except Exception as e:
            log.warning("Could not set up the voice: %s", e)

    def _create(self):
        try:
            import comtypes.client
            # Late-bound, so nothing gets generated into comtypes.gen (which a frozen exe can't write).
            self.voice = comtypes.client.CreateObject("SAPI.SpVoice", dynamic=True)
            return True
        except Exception as e:
            log.warning("Text-to-speech is unavailable, pings only: %s", e)
            self.mode = "off"
            return False

    def _pick_voice(self, want):
        want = (want or "").strip().lower()
        if not want:
            return
        voices = self.voice.GetVoices()
        for i in range(voices.Count):
            token = voices.Item(i)
            if want in token.GetDescription().lower():
                self.voice.Voice = token
                return
        log.warning("No installed voice matches %r, using the Windows default", want)

    def say(self, text):
        if not text or self.mode == "off" or self.muted or self.voice is None:
            return
        try:
            self.voice.Speak(text, SPEAK_ASYNC | PURGE_BEFORE_SPEAK | IS_NOT_XML)
        except Exception as e:
            log.warning("Could not speak %r: %s", text, e)
