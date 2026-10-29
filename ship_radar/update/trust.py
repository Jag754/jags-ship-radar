"""What the updater trusts, and what it deliberately does not.

Updates come from this project's GitHub Releases. GitHub, DNS and TLS are all
treated as untrusted: an update installs only if its manifest carries an
Ed25519 signature from the release key on the maintainer's PC, and the
downloaded installer's SHA-256 matches that signed manifest. So a hijacked
GitHub account or a tampered download can't push an update; only the key can.

This app is signed with the SAME key as Jag's SCDB, but under its own
SIGNING_CONTEXT and PRODUCT_ID. A signature is made over context + manifest,
so a manifest signed for scDB can never verify here, and the reverse, even
though one key signs both.
"""

# Ed25519 public key (32 bytes, hex) of the Jag's release signing key. The
# private half is %LOCALAPPDATA%\Jags-SCDB\release-signing\scdb-release.pem on
# the maintainer's PC and never leaves it. Compiled into the exe on purpose: not
# a setting, not read from disk or the network.
RELEASE_PUBLIC_KEY_HEX = "0084ce9fcbc74fc2b914a80235948a7643f5cc31714bb224c78bd833f06da1c9"

SIGNING_CONTEXT = b"jags-ship-radar/update-manifest/v1\n"
PRODUCT_ID = "jags-ship-radar"

# Hard-coded on purpose: a tampered config.json must not be able to point the
# updater elsewhere. "latest/download" serves the newest published release's files.
GITHUB_REPO = "Jag754/jags-ship-radar"
UPDATE_BASE_URL = f"https://github.com/{GITHUB_REPO}/releases/latest/download"
# GitHub redirects release downloads to its file storage; these are the only
# hosts the updater will follow a redirect to.
ALLOWED_HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")

USER_AGENT_PREFIX = "Jags-ShipRadar-updater"

MANIFEST_NAME = "latest.json"
SIGNATURE_NAME = "latest.json.sig"

MANIFEST_MAX_BYTES = 8 * 1024
SIG_MAX_BYTES = 256
# The 0.1.0 installer is about 15 MB; the build refuses anything over this.
INSTALLER_MAX_BYTES = 100 * 1024 * 1024

MANIFEST_TIMEOUT = (10, 20)
DOWNLOAD_TIMEOUT = (10, 120)

INSTALLER_PREFIX = "Jags-Ship-Radar-Setup-"
INSTALLER_NAME_PATTERN = r"^Jags-Ship-Radar-Setup-[0-9]+(\.[0-9]+){1,3}\.exe$"


def installer_name(version):
    return f"{INSTALLER_PREFIX}{version}.exe"
