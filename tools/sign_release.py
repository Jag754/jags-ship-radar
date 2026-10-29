r"""Sign a built installer, producing the files the update server serves.

    .venv\Scripts\python.exe tools\sign_release.py --notes "What changed"

Reads   dist\Jags-Ship-Radar-Setup-<version>.exe   (built by build.ps1)
Writes  dist\release\  that installer, latest.json and latest.json.sig

Same scheme as Jag's SCDB (scripts/sign_release.py) and the same key:
%LOCALAPPDATA%\Jags-SCDB\release-signing\scdb-release.pem, unlocked with the
passphrase saved in Windows Credential Manager (or typed at the prompt). The
signature covers ship_radar's own SIGNING_CONTEXT + the manifest bytes, so it is
useless for scDB and vice versa. This app keeps its own serial counter.
"""

import argparse
import getpass
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ship_radar import __version__  # noqa: E402
from ship_radar.update import trust  # noqa: E402
from ship_radar.update.manifest import verify_and_parse  # noqa: E402

KEY_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Jags-SCDB", "release-signing")
KEY_PATH = os.path.join(KEY_DIR, "scdb-release.pem")
SERIAL_PATH = os.path.join(KEY_DIR, "ship-radar-serial.txt")
PASSPHRASE_TARGET = "Jags-SCDB release signing passphrase"


def _saved_passphrase():
    """The passphrase scDB's tooling saved in Credential Manager, or None."""
    import ctypes
    from ctypes import wintypes

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                    ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
                    ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
                    ("UserName", wintypes.LPWSTR)]

    api = ctypes.WinDLL("advapi32", use_last_error=True)
    api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                              ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    api.CredReadW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    ptr = ctypes.POINTER(CREDENTIAL)()
    if not api.CredReadW(PASSPHRASE_TARGET, 1, 0, ctypes.byref(ptr)):
        return None
    try:
        return ctypes.string_at(ptr.contents.CredentialBlob, ptr.contents.CredentialBlobSize).decode("utf-16-le")
    finally:
        api.CredFree(ptr)


def _load_private_key():
    from cryptography.hazmat.primitives import serialization

    if not os.path.exists(KEY_PATH):
        raise SystemExit(f"No signing key at {KEY_PATH} (it is made by scDB's scripts/keygen_release.py)")
    with open(KEY_PATH, "rb") as f:
        pem = f.read()
    tries = [os.environ.get("SCDB_SIGNING_PASSPHRASE"), _saved_passphrase()]
    for p in [t for t in tries if t is not None]:
        try:
            return serialization.load_pem_private_key(pem, password=p.encode("utf-8"))
        except ValueError:
            pass
    for _ in range(3):
        try:
            return serialization.load_pem_private_key(
                pem, password=getpass.getpass("Signing key passphrase: ").encode("utf-8"))
        except ValueError:
            print("  wrong passphrase")
    raise SystemExit("could not unlock the signing key")


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description="Sign a built Jag's Ship Radar installer.")
    ap.add_argument("--notes", default="", help="one to three short lines shown in the update alert")
    ap.add_argument("--serial", type=int, default=None, help="override the auto-incrementing serial")
    args = ap.parse_args()

    version = __version__
    name = trust.installer_name(version)
    installer = os.path.join(ROOT, "dist", name)
    if not os.path.isfile(installer):
        raise SystemExit(f"installer not found: {installer}\nBuild it first: build.ps1")
    size = os.path.getsize(installer)
    if size > trust.INSTALLER_MAX_BYTES:
        raise SystemExit(f"refusing to sign: {size} bytes is over trust.INSTALLER_MAX_BYTES")

    key = _load_private_key()
    try:
        with open(SERIAL_PATH, encoding="utf-8") as f:
            last = int(f.read().strip() or 0)
    except (OSError, ValueError):
        last = 0
    serial = args.serial if args.serial is not None else last + 1

    payload = {
        "schema": 1,
        "product": trust.PRODUCT_ID,
        "version": version,
        "serial": serial,
        "released": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "file": name,
        "size": size,
        "sha256": _sha256(installer),
        "notes": args.notes,
    }
    raw = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    if len(raw) > trust.MANIFEST_MAX_BYTES:
        raise SystemExit("manifest is over the size the app will read; shorten --notes")
    sig_text = (key.sign(trust.SIGNING_CONTEXT + raw).hex() + "\n").encode("ascii")

    # Prove the chain with the PUBLIC key baked into the app before writing anything.
    manifest = verify_and_parse(raw, sig_text)
    assert manifest.version == version and manifest.serial == serial

    out = os.path.join(ROOT, "dist", "release")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    with open(os.path.join(out, trust.MANIFEST_NAME), "wb") as f:
        f.write(raw)
    with open(os.path.join(out, trust.SIGNATURE_NAME), "wb") as f:
        f.write(sig_text)
    shutil.copy2(installer, os.path.join(out, name))
    with open(SERIAL_PATH, "w", encoding="utf-8") as f:
        f.write(f"{serial}\n")

    print(f"Signed Jag's Ship Radar {version} (serial {serial}), {size:,} bytes, sha256 {payload['sha256'][:16]}...")
    print("  verified against the public key in ship_radar/update/trust.py")
    print("Next: .venv\\Scripts\\python.exe tools\\publish_github.py")


if __name__ == "__main__":
    main()
