"""Notice when the UI thread stops, and write down where it stopped."""

import faulthandler
import logging
import threading
import time

log = logging.getLogger(__name__)


class Watchdog(threading.Thread):
    """Writes every thread's stack to crash.log if the UI thread stops checking in, so a report of
    "it stopped working" comes with the line it stopped on."""

    def __init__(self, log_file, stall_after=15.0, poll=5.0, clock=time.monotonic):
        super().__init__(daemon=True, name="Watchdog")
        self.log_file, self.stall_after, self.poll, self.clock = log_file, stall_after, poll, clock
        self.last = clock()
        self.reported = False
        self._halt = threading.Event()

    def beat(self):
        """Call from the UI thread, often."""
        self.last = self.clock()

    def stop(self):
        self._halt.set()

    def check(self):
        stalled = self.clock() - self.last
        if stalled > self.stall_after and not self.reported:
            self.reported = True
            log.error("UI thread hasn't run for %.0fs. Stacks of every thread are in crash.log.", stalled)
            if self.log_file is not None:
                self.log_file.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} UI thread stalled {stalled:.0f}s ---\n")
                self.log_file.flush()
                faulthandler.dump_traceback(file=self.log_file, all_threads=True)
                self.log_file.flush()
        elif stalled <= self.stall_after and self.reported:
            self.reported = False
            log.warning("UI thread is running again")

    def run(self):
        while not self._halt.wait(self.poll):
            self.check()
