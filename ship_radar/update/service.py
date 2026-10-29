"""Check, download, hand over to the installer. Ported from scdb/update/service.py, minus Qt.

Everything here runs on a background thread; the app posts results back to the Tk thread.
"""

import json
import logging
import os
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass

from .client import UpdateClient
from .manifest import UpdateRejected, is_newer, verify_and_parse

log = logging.getLogger(__name__)

CACHE_DIR_NAME = "update-cache"
STATE_FILE_NAME = "update_state.json"


@dataclass
class UpdateCheck:
    available: bool
    message: str
    manifest: object = None
    # Could not complete (offline, server down): a background check stays quiet about these.
    failed: bool = False
    # Something was WRONG (bad signature, replayed manifest): always shown.
    rejected: bool = False


class UpdateState:
    """last_serial is the anti-rollback guard: a manifest below the highest serial seen is refused."""

    def __init__(self, path):
        self.path = path
        self.last_serial = 0
        self.last_check = 0.0
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        if isinstance(data, dict):
            serial = data.get("last_serial")
            if isinstance(serial, int) and not isinstance(serial, bool) and serial > 0:
                self.last_serial = serial
            when = data.get("last_check")
            if isinstance(when, (int, float)) and not isinstance(when, bool):
                self.last_check = float(when)

    def save(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"last_serial": self.last_serial, "last_check": self.last_check}, f, indent=2)
            os.replace(tmp, self.path)
        except OSError as exc:
            log.warning("could not save update state: %s", exc)


class UpdateService:
    def __init__(self, installed_version, data_dir, client=None):
        self.installed_version = installed_version
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.state = UpdateState(os.path.join(data_dir, STATE_FILE_NAME))
        self._client = client if client is not None else UpdateClient()

    def check(self):
        """Fetch and verify the manifest. Never raises."""
        try:
            raw, sig = self._client.fetch_manifest()
        except UpdateRejected as exc:
            return UpdateCheck(False, str(exc), failed=True)
        except Exception as exc:  # offline, DNS, TLS, timeouts
            log.info("update check could not reach the server: %s", exc)
            return UpdateCheck(False, "Could not reach the update server.", failed=True)

        try:
            manifest = verify_and_parse(raw, sig)
        except UpdateRejected as exc:
            log.error("update REJECTED: %s", exc)
            return UpdateCheck(False, str(exc), failed=True, rejected=True)
        except Exception as exc:
            log.exception("update check failed unexpectedly")
            return UpdateCheck(False, f"The update check could not run ({exc}).", failed=True)

        if manifest.serial < self.state.last_serial:
            log.error("update REJECTED: serial %s is below %s already seen", manifest.serial, self.state.last_serial)
            return UpdateCheck(False, "The update server is offering an older release than one already seen. "
                                      "Ignoring it.", failed=True, rejected=True)

        self.state.last_serial = manifest.serial
        self.state.last_check = time.time()
        self.state.save()

        if not is_newer(manifest, self.installed_version):
            return UpdateCheck(False, f"Jag's Ship Radar {self.installed_version} is up to date.", manifest=manifest)
        return UpdateCheck(True, f"Version {manifest.version} is available (you have {self.installed_version}).",
                           manifest=manifest)

    def _fresh_cache_dir(self):
        root = os.path.join(self.data_dir, CACHE_DIR_NAME)
        os.makedirs(root, exist_ok=True)
        for name in os.listdir(root):
            victim = os.path.join(root, name)
            try:
                shutil.rmtree(victim) if os.path.isdir(victim) else os.unlink(victim)
            except OSError:
                pass
        path = os.path.join(root, secrets.token_hex(8))
        os.makedirs(path)
        return path

    def download(self, manifest, progress=None):
        """Download and verify; the returned path has already matched the signed manifest."""
        if not is_newer(manifest, self.installed_version):
            raise UpdateRejected("that version is not newer than the one installed")
        target = os.path.join(self._fresh_cache_dir(), manifest.file)
        log.info("downloading update %s", manifest.version)
        return self._client.download_installer(manifest, target, progress=progress)

    # installer.iss reads this as {param:RESTARTRADAR} and starts the app again afterwards.
    RESTART_FLAG = "/RESTARTRADAR=1"

    @staticmethod
    def launch_installer(path, restart=True):
        """Start the verified installer's normal wizard (still cancellable) and return."""
        full = os.path.abspath(path)
        if not os.path.isfile(full):
            raise UpdateRejected("the downloaded installer has disappeared")
        args = [full] + ([UpdateService.RESTART_FLAG] if restart else [])
        env = {k: v for k, v in os.environ.items() if not k.startswith("_PYI") and k != "_MEIPASS2"}
        log.info("starting installer %s", full)
        subprocess.Popen(args, close_fds=True, env=env)
