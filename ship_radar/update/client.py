"""HTTPS transport for the updater. Ported from scdb/update/client.py.

1. https only: URLs are built from a validated base.
2. Redirects are followed by hand, and only to https on the hosts in trust.ALLOWED_HOSTS
   (GitHub sends release downloads through two of them).
3. Every read is bounded.
"""

import hashlib
import os
import re
from urllib.parse import urljoin, urlparse

from .. import __version__
from . import trust
from .manifest import UpdateRejected

_CHUNK = 64 * 1024
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_MAX_REDIRECTS = 5


class UpdateClient:
    """session is anything with .get(url, timeout=, stream=, headers=, allow_redirects=)."""

    def __init__(self, base_url=trust.UPDATE_BASE_URL, session=None):
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise UpdateRejected(f"update base URL is not https: {base_url!r}")
        self.base_url = base_url.rstrip("/")
        self.allowed_hosts = {parsed.hostname, *trust.ALLOWED_HOSTS}
        if session is None:
            import requests
            session = requests.Session()
        self._session = session

    def _url(self, name):
        if not _SAFE_NAME_RE.match(name or ""):
            raise UpdateRejected(f"unsafe update filename: {name!r}")
        return f"{self.base_url}/{name}"

    def _check_url(self, url, name):
        parsed = urlparse(str(url))
        if parsed.scheme != "https" or parsed.hostname not in self.allowed_hosts:
            raise UpdateRejected(f"{name} came from {url!r}, which is not an update host; refusing it")

    def _get(self, name, *, stream, timeout):
        url = self._url(name)
        for _ in range(_MAX_REDIRECTS + 1):
            resp = self._session.get(
                url,
                timeout=timeout,
                stream=stream,
                headers={"User-Agent": f"{trust.USER_AGENT_PREFIX}/{__version__}", "Cache-Control": "no-cache"},
                allow_redirects=False,
            )
            status = getattr(resp, "status_code", 0)
            if status not in (301, 302, 303, 307, 308):
                break
            location = (getattr(resp, "headers", None) or {}).get("Location")
            if not location:
                raise UpdateRejected(f"the update server redirected {name} without saying where")
            url = urljoin(url, location)
            self._check_url(url, name)
        else:
            raise UpdateRejected(f"too many redirects for {name}")
        if status != 200:
            raise UpdateRejected(f"update server returned HTTP {status} for {name}")
        final = getattr(resp, "url", None)
        if final:
            self._check_url(final, name)
        return resp

    @staticmethod
    def _bounded(resp, cap, what):
        headers = getattr(resp, "headers", None) or {}
        try:
            length = int(headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        if length > cap:
            raise UpdateRejected(f"{what} is too large ({length} bytes)")
        body = bytearray()
        for chunk in resp.iter_content(chunk_size=4096):
            if not chunk:
                continue
            body += chunk
            if len(body) > cap:
                raise UpdateRejected(f"{what} is too large (over {cap} bytes)")
        return bytes(body)

    def fetch_manifest(self):
        """(manifest_bytes, signature_bytes) exactly as served, unparsed."""
        raw = self._bounded(self._get(trust.MANIFEST_NAME, stream=True, timeout=trust.MANIFEST_TIMEOUT),
                            trust.MANIFEST_MAX_BYTES, "the update manifest")
        sig = self._bounded(self._get(trust.SIGNATURE_NAME, stream=True, timeout=trust.MANIFEST_TIMEOUT),
                            trust.SIG_MAX_BYTES, "the update signature")
        return raw, sig

    def download_installer(self, manifest, dest_path, progress=None):
        """Stream the installer to dest_path, verifying size and SHA-256. Deletes it on any failure."""
        cap = min(manifest.size, trust.INSTALLER_MAX_BYTES)
        digest = hashlib.sha256()
        done = 0
        resp = self._get(manifest.file, stream=True, timeout=trust.DOWNLOAD_TIMEOUT)
        try:
            with open(dest_path, "wb") as out:
                for chunk in resp.iter_content(chunk_size=_CHUNK):
                    if not chunk:
                        continue
                    done += len(chunk)
                    if done > cap:
                        raise UpdateRejected("the installer on the server is bigger than the signed "
                                             "manifest says; stopped downloading")
                    digest.update(chunk)
                    out.write(chunk)
                    if progress is not None:
                        progress(done, manifest.size)
            if done != manifest.size:
                raise UpdateRejected(f"the installer is {done} bytes but the signed manifest says {manifest.size}")
            if digest.hexdigest() != manifest.sha256:
                raise UpdateRejected("the downloaded installer does not match the signed checksum, "
                                     "so it was not run. It has been deleted.")
        except Exception:
            try:
                os.unlink(dest_path)
            except OSError:
                pass
            raise
        return dest_path
