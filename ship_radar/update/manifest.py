"""Parsing and verification of a release manifest. Pure Python, no GUI, no network.

Strict on purpose: a manifest that is merely odd is rejected, not interpreted.
Ported from scdb/update/manifest.py.
"""

import json
import re
from dataclasses import dataclass

from . import trust


class UpdateRejected(Exception):
    """An update was refused. The message is safe to show the user."""


_VERSION_RE = re.compile(r"^[0-9]{1,5}(\.[0-9]{1,5}){1,3}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HEX_SIG_RE = re.compile(r"^[0-9a-fA-F]{128}$")
_INSTALLER_RE = re.compile(trust.INSTALLER_NAME_PATTERN)


def parse_version(text):
    """"1.3.1" -> (1, 3, 1). Raises UpdateRejected on anything else."""
    if not isinstance(text, str) or not _VERSION_RE.match(text):
        raise UpdateRejected(f"not a version number: {text!r}")
    return tuple(int(part) for part in text.split("."))


def _clean_notes(text):
    return "".join(ch for ch in text if ch == "\n" or ch >= " ")[:2000]


def _is_int(v):
    # bool is an int in Python; `true` must not pass for 1.
    return isinstance(v, int) and not isinstance(v, bool)


@dataclass(frozen=True)
class Manifest:
    version: str
    serial: int
    file: str
    size: int
    sha256: str
    released: str = ""
    notes: str = ""

    @property
    def version_tuple(self):
        return parse_version(self.version)


def _require(condition, message):
    if not condition:
        raise UpdateRejected(message)


def parse_manifest(raw):
    _require(len(raw) <= trust.MANIFEST_MAX_BYTES, "update manifest is too large")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateRejected(f"update manifest is not valid JSON ({exc})") from exc

    _require(isinstance(data, dict), "update manifest is not a JSON object")
    schema = data.get("schema")
    _require(_is_int(schema) and schema == 1, f"unsupported manifest schema: {schema!r}")
    _require(data.get("product") == trust.PRODUCT_ID,
             f"manifest is for another product: {data.get('product')!r}")

    version = data.get("version")
    parse_version(version)

    serial = data.get("serial")
    _require(_is_int(serial) and serial >= 1, f"manifest serial is not a positive integer: {serial!r}")

    name = data.get("file")
    _require(isinstance(name, str) and bool(_INSTALLER_RE.match(name)),
             f"manifest names an unexpected installer: {name!r}")
    _require(name == trust.installer_name(version), f"installer {name!r} does not match version {version!r}")

    size = data.get("size")
    _require(_is_int(size) and 0 < size <= trust.INSTALLER_MAX_BYTES,
             f"manifest declares an implausible installer size: {size!r}")

    digest = data.get("sha256")
    _require(isinstance(digest, str) and bool(_SHA256_RE.match(digest)),
             "manifest sha256 is not a lowercase hex digest")

    released = data.get("released", "")
    _require(isinstance(released, str) and len(released) <= 40, "manifest release date is malformed")

    notes = data.get("notes", "")
    _require(isinstance(notes, str), "manifest notes are not text")

    return Manifest(version=version, serial=serial, file=name, size=size,
                    sha256=digest, released=released, notes=_clean_notes(notes))


def verify_signature(raw_manifest, raw_signature, public_key_hex=None):
    """Raise UpdateRejected unless raw_signature is ours, over the exact downloaded bytes."""
    key_hex = trust.RELEASE_PUBLIC_KEY_HEX if public_key_hex is None else public_key_hex
    _require(len(raw_signature) <= trust.SIG_MAX_BYTES, "update signature is too large")
    text = raw_signature.decode("ascii", errors="replace").strip()
    _require(bool(_HEX_SIG_RE.match(text)), "update signature is malformed")

    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(key_hex))
    except ValueError as exc:
        raise UpdateRejected(f"built-in release key is unusable ({exc})") from exc
    try:
        key.verify(bytes.fromhex(text), trust.SIGNING_CONTEXT + raw_manifest)
    except InvalidSignature:
        raise UpdateRejected("the update on the server is not signed by Jag's Ship Radar. "
                             "Nothing was downloaded.") from None


def verify_and_parse(raw_manifest, raw_signature, public_key_hex=None):
    """Signature first, then contents. The only entry point callers should use."""
    verify_signature(raw_manifest, raw_signature, public_key_hex)
    return parse_manifest(raw_manifest)


def is_newer(manifest, installed_version):
    return manifest.version_tuple > parse_version(installed_version)
