import hashlib
import json
import os
import tempfile
import unittest
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ship_radar.update import trust
from ship_radar.update.client import UpdateClient
from ship_radar.update.manifest import UpdateRejected, verify_and_parse
from ship_radar.update.service import UpdateService

KEY = Ed25519PrivateKey.generate()
PUB = KEY.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
INSTALLER = b"MZ fake installer bytes" * 100


def manifest(version="1.1.0", serial=2, **over):
    data = {"schema": 1, "product": trust.PRODUCT_ID, "version": version, "serial": serial,
            "released": "2026-10-28T00:00:00Z", "file": trust.installer_name(version),
            "size": len(INSTALLER), "sha256": hashlib.sha256(INSTALLER).hexdigest(), "notes": "Better radar"}
    data.update(over)
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode()


def sign(raw, context=trust.SIGNING_CONTEXT, key=KEY):
    return (key.sign(context + raw).hex() + "\n").encode()


class Resp:
    def __init__(self, body=b"", status=200, url=None, headers=None):
        self.body, self.status_code, self.url, self.headers = body, status, url, headers or {}

    def iter_content(self, chunk_size):
        for i in range(0, len(self.body), chunk_size):
            yield self.body[i:i + chunk_size]


class FakeSession:
    def __init__(self, files):
        self.files = files
        self.agents = []

    def get(self, url, timeout, stream, headers, allow_redirects):
        assert allow_redirects is False
        self.agents.append(headers["User-Agent"])
        r = self.files.get(url) or self.files.get(url.rsplit("/", 1)[1])
        return r if isinstance(r, Resp) else Resp(r, 200 if r is not None else 404)


class ManifestTests(unittest.TestCase):
    def test_good_manifest(self):
        raw = manifest()
        m = verify_and_parse(raw, sign(raw), PUB)
        self.assertEqual((m.version, m.serial), ("1.1.0", 2))

    def test_scdb_signature_is_refused(self):
        # Same key, but signed under scDB's context: must not verify here.
        raw = manifest()
        with self.assertRaises(UpdateRejected):
            verify_and_parse(raw, sign(raw, b"jags-scdb/update-manifest/v1\n"), PUB)

    def test_other_key_refused(self):
        raw = manifest()
        with self.assertRaises(UpdateRejected):
            verify_and_parse(raw, sign(raw, key=Ed25519PrivateKey.generate()), PUB)

    def test_tampered_bytes_refused(self):
        raw = manifest()
        sig = sign(raw)
        with self.assertRaises(UpdateRejected):
            verify_and_parse(raw.replace(b"Better", b"Evil!!"), sig, PUB)

    def test_strict_fields(self):
        for bad in (manifest(product="jags-scdb"), manifest(schema=True), manifest(serial=True),
                    manifest(file="Jags-Ship-Radar-Setup-9.9.9.exe"), manifest(file="../evil.exe"),
                    manifest(size=trust.INSTALLER_MAX_BYTES + 1), manifest(version="v1.1")):
            with self.assertRaises(UpdateRejected, msg=bad):
                verify_and_parse(bad, sign(bad), PUB)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        patcher = mock.patch.object(trust, "RELEASE_PUBLIC_KEY_HEX", PUB)
        patcher.start()
        self.addCleanup(patcher.stop)

    def service(self, files, version="1.0.0"):
        self.session = FakeSession(files)
        return UpdateService(version, self.dir, UpdateClient(session=self.session))

    def published(self, version="1.1.0", serial=2, body=INSTALLER):
        raw = manifest(version, serial)
        return {"latest.json": raw, "latest.json.sig": sign(raw), trust.installer_name(version): body}

    def test_update_found_downloaded_and_verified(self):
        svc = self.service(self.published())
        result = svc.check()
        self.assertTrue(result.available)
        path = svc.download(result.manifest)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), INSTALLER)
        self.assertTrue(all(a.startswith(trust.USER_AGENT_PREFIX + "/") for a in self.session.agents))

    def test_up_to_date(self):
        result = self.service(self.published("1.0.0", 1)).check()
        self.assertFalse(result.available)
        self.assertFalse(result.failed)

    def test_swapped_installer_is_deleted(self):
        svc = self.service(self.published(body=b"X" * len(INSTALLER)))
        m = svc.check().manifest
        with self.assertRaises(UpdateRejected):
            svc.download(m)
        cache = os.path.join(self.dir, "update-cache")
        self.assertEqual([f for _, _, fs in os.walk(cache) for f in fs], [])

    def test_oversized_installer_stops(self):
        svc = self.service(self.published(body=INSTALLER + b"extra"))
        with self.assertRaises(UpdateRejected):
            svc.download(svc.check().manifest)

    def test_old_serial_replay_refused(self):
        self.assertTrue(self.service(self.published("1.2.0", 5)).check().available)
        result = self.service(self.published("1.1.0", 2)).check()
        self.assertTrue(result.rejected)

    def test_bad_signature_is_rejected_not_just_failed(self):
        files = self.published()
        files["latest.json.sig"] = sign(files["latest.json"], key=Ed25519PrivateKey.generate())
        result = self.service(files).check()
        self.assertTrue(result.failed and result.rejected)

    def test_redirect_and_offline_are_quiet_failures(self):
        files = self.published()
        files["latest.json"] = Resp(status=302)
        result = self.service(files).check()
        self.assertTrue(result.failed)
        self.assertFalse(result.rejected)

    def test_follows_github_redirects_only(self):
        # How GitHub serves a release file: two hops, ending on its file storage.
        files = self.published()
        asset = "https://release-assets.githubusercontent.com/github-production-release-asset/1/abc?sig=x"
        step = "https://github.com/OWNER/r/releases/download/v1.1.0/latest.json"
        files[step] = Resp(status=302, headers={"Location": asset})
        files[asset] = Resp(files["latest.json"], url=asset)
        files["latest.json"] = Resp(status=302, headers={"Location": "/OWNER/r/releases/download/v1.1.0/latest.json"})
        self.assertTrue(self.service(files).check().available)

        for evil in ("https://evil.example/latest.json", "http://github.com/x/latest.json"):
            files["latest.json"] = Resp(status=302, headers={"Location": evil})
            result = self.service(files).check()
            self.assertTrue(result.failed and not result.available, evil)


if __name__ == "__main__":
    unittest.main()
