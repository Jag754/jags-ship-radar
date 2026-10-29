"""Follow Game.log as the game writes it, and notice when the game starts a new one."""

import ctypes
import logging
import msvcrt
import os
import threading
import time
from ctypes import wintypes

log = logging.getLogger(__name__)

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                             wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
_k32.CreateFileW.restype = wintypes.HANDLE
GENERIC_READ = 0x80000000
SHARE_ALL = 0x1 | 0x2 | 0x4  # read | write | delete
OPEN_EXISTING = 3
INVALID_HANDLE = wintypes.HANDLE(-1).value


def open_shared(path):
    """Open for reading without ever blocking the game from writing, renaming or deleting the log."""
    h = _k32.CreateFileW(str(path), GENERIC_READ, SHARE_ALL, None, OPEN_EXISTING, 0x80, None)
    if h == INVALID_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())
    fd = msvcrt.open_osfhandle(h, os.O_RDONLY | os.O_BINARY)
    return os.fdopen(fd, "rb", buffering=0)


class LogTailer(threading.Thread):
    """Calls on_lines(lines, live) from this thread. live=False is the quiet catch-up read at startup.

    on_new_file(path) is called when a different Game.log is picked up (a new game session).
    on_status(text) reports problems like the log not being found.
    """

    def __init__(self, resolve_path, on_lines, on_new_file, on_status, catch_up=True, poll=0.2):
        super().__init__(daemon=True, name="LogTailer")
        self.resolve_path = resolve_path
        self.on_lines = on_lines
        self.on_new_file = on_new_file
        self.on_status = on_status
        self.catch_up = catch_up
        self.poll = poll
        self._halt = threading.Event()
        self._rescan = threading.Event()
        self.f = None
        self.path = None
        self.ino = None
        self.pos = 0
        self.buf = b""

    def stop(self):
        self._halt.set()

    def rescan(self):
        self._rescan.set()

    def _open(self, path, from_start):
        self._close()
        self.f = open_shared(path)
        st = os.fstat(self.f.fileno())
        self.path, self.ino, self.buf = path, st.st_ino, b""
        self.pos = 0 if from_start else st.st_size
        self.f.seek(self.pos)
        log.info("Watching %s (from %s)", path, "start" if from_start else "end")

    def _close(self):
        if self.f:
            try:
                self.f.close()
            except OSError:
                pass
        self.f = None

    def _read(self, live):
        data = self.f.read()
        if not data:
            return
        self.pos += len(data)
        data = self.buf + data
        *lines, self.buf = data.split(b"\n")
        if lines:
            self.on_lines([ln.decode("utf-8", "replace").rstrip("\r") for ln in lines], live)

    def _same_file(self):
        try:
            st = os.stat(self.path)
        except OSError:
            return False
        return st.st_ino == self.ino and st.st_size >= self.pos

    def run(self):
        last_resolve = 0.0
        reported_missing = False
        while not self._halt.is_set():
            try:
                now = time.monotonic()
                if self.f is None or self._rescan.is_set() or now - last_resolve > 15:
                    self._rescan.clear()
                    last_resolve = now
                    path = self.resolve_path()
                    if path is None:
                        if not reported_missing:
                            self.on_status("Game.log not found. Use the tray menu to choose it.")
                            reported_missing = True
                        self._halt.wait(5)
                        continue
                    reported_missing = False
                    if self.f is None or path != self.path:
                        self._switch(path, quiet=True)

                if not self._same_file():
                    # The game started a new session: finish the old file, then read the new one from the top.
                    self._read(live=True)
                    self._switch(self.path, quiet=False)

                self._read(live=True)
            except OSError as e:
                log.warning("Log read problem: %s", e)
                self._close()
                self._halt.wait(2)
                continue
            self._halt.wait(self.poll)
        self._close()

    def _switch(self, path, quiet):
        """quiet: a log we start watching part-way through (app start, user picked a file), so read
        what is already there without alerting. Otherwise it is a brand-new session: alert on everything."""
        self.on_new_file(path)
        self._open(path, from_start=self.catch_up or not quiet)
        if quiet:
            self._read(live=False)
