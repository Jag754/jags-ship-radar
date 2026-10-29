"""Alert sounds: short generated tones, or the user's own .wav files."""

import array
import hashlib
import logging
import math
import struct
import wave
import winsound
from pathlib import Path

from .config import CONFIG_DIR

log = logging.getLogger(__name__)
RATE = 44100


def _tone(freqs, volume, note_ms=90, gap_ms=35):
    frames = bytearray()
    n = int(RATE * note_ms / 1000)
    fade = int(RATE * 0.01)
    for f in freqs:
        for i in range(n):
            env = min(1.0, i / fade, (n - i) / fade)
            frames += struct.pack("<h", int(32767 * volume * env * math.sin(2 * math.pi * f * i / RATE)))
        frames += b"\x00\x00" * int(RATE * gap_ms / 1000)
    return bytes(frames)


def _write(path, freqs, volume):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(_tone(freqs, volume))


def _scaled_copy(src, folder, vol, tag):
    """A copy of the user's .wav at this volume, or the original if it isn't 16-bit PCM."""
    key = hashlib.sha1(f"{src.resolve()}|{src.stat().st_mtime_ns}".encode()).hexdigest()[:10]
    dst = folder / f"custom_{key}_{tag}.wav"
    if dst.exists():
        return dst
    try:
        with wave.open(str(src), "rb") as r:
            params, frames = r.getparams(), r.readframes(r.getnframes())
        if params.sampwidth != 2:
            return src
        samples = array.array("h", frames)
        for i, v in enumerate(samples):
            samples[i] = int(v * vol)
        with wave.open(str(dst), "wb") as w:
            w.setparams(params)
            w.writeframes(samples.tobytes())
        return dst
    except (OSError, wave.Error, EOFError) as e:
        log.warning("Could not set the volume of %s, playing it as is: %s", src, e)
        return src


class Sounds:
    def __init__(self, cfg):
        self.reload(cfg)

    def reload(self, cfg):
        self.enabled = cfg.get("sound", True)
        vol = max(0.0, min(1.0, float(cfg.get("volume", 0.6))))
        folder = CONFIG_DIR / "sounds"
        folder.mkdir(parents=True, exist_ok=True)
        tag = int(vol * 100)
        self.status = folder / f"status_{tag}.wav"
        self.normal = self._pick(cfg.get("sound_file"), folder / f"ping_{tag}.wav", folder, vol, tag)
        self.priority = self._pick(cfg.get("priority_sound_file"), folder / f"priority_{tag}.wav", folder, vol, tag)
        for path, freqs in ((self.normal, (880, 1320)), (self.priority, (740, 740, 740, 988)), (self.status, (660,))):
            if not path.exists() and path.parent == folder and not path.name.startswith("custom_"):
                _write(path, freqs, vol)

    @staticmethod
    def _pick(custom, default, folder, vol, tag):
        if not custom:
            return default
        src = Path(custom)
        return _scaled_copy(src, folder, vol, tag) if src.exists() else src

    def play(self, kind="normal"):
        if not self.enabled:
            return
        path = {"priority": self.priority, "status": self.status}.get(kind, self.normal)
        try:
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except RuntimeError as e:
            log.warning("Could not play %s: %s", path, e)
