r"""Publish a signed release to this project's GitHub Releases.

    .venv\Scripts\python.exe tools\publish_github.py

Uploads dist\release\ (the installer, latest.json, latest.json.sig) as release
v<version>, marked latest. Installed copies check
github.com/<repo>/releases/latest/download/latest.json, so publishing is what
makes an update available. Needs the GitHub CLI, signed in (gh auth login).

A published release can't be "rolled back" by re-marking an older one as latest:
installed copies refuse a manifest whose serial is below one they've seen. Fix
forward with a new version instead.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ship_radar.update import trust  # noqa: E402
from ship_radar.update.manifest import verify_and_parse  # noqa: E402

WINGET_GH = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"
                               r"\GitHub.cli_Microsoft.Winget.Source_8wekyb3d8bbwe\bin\gh.exe")


def gh(*args, capture=False):
    exe = shutil.which("gh") or (WINGET_GH if os.path.exists(WINGET_GH) else None)
    if not exe:
        raise SystemExit("GitHub CLI not found. Install it: winget install GitHub.cli")
    return subprocess.run([exe, *args], text=True, capture_output=capture)


def verify_local(release_dir):
    with open(os.path.join(release_dir, trust.MANIFEST_NAME), "rb") as f:
        raw = f.read()
    with open(os.path.join(release_dir, trust.SIGNATURE_NAME), "rb") as f:
        sig = f.read()
    m = verify_and_parse(raw, sig)
    h = hashlib.sha256()
    with open(os.path.join(release_dir, m.file), "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != m.sha256:
        raise SystemExit("the installer in dist/release does not match its signed manifest; re-run sign_release.py")
    print(f"  verified locally: {m.version} serial {m.serial}, {m.size:,} bytes")
    return m


def verify_published(m):
    """Fetch what the world now sees, as the app does, and check it end to end."""
    from ship_radar.update.client import UpdateClient

    for _ in range(6):
        try:
            live = verify_and_parse(*UpdateClient().fetch_manifest())
            if (live.version, live.serial) == (m.version, m.serial):
                break
        except Exception as e:  # GitHub can take a moment to serve a new release
            print(f"  waiting for GitHub: {e}")
        time.sleep(5)
    else:
        print("  ! GitHub is not serving this release as latest yet")
        return 1
    print(f"  live manifest verifies: {live.version} serial {live.serial}")
    return 0


def main():
    release_dir = os.path.join(ROOT, "dist", "release")
    if not os.path.isdir(release_dir):
        raise SystemExit("nothing to publish; run tools\\sign_release.py first")
    m = verify_local(release_dir)
    tag = f"v{m.version}"

    if gh("release", "view", tag, "--repo", trust.GITHUB_REPO, capture=True).returncode == 0:
        raise SystemExit(f"{tag} is already on GitHub. Bump the version for a new release.")

    print(f"\nPublishing {tag} to github.com/{trust.GITHUB_REPO}")
    files = [os.path.join(release_dir, n) for n in (m.file, trust.MANIFEST_NAME, trust.SIGNATURE_NAME)]
    if gh("release", "create", tag, *files, "--repo", trust.GITHUB_REPO, "--title", f"Jag's Ship Radar {m.version}",
          "--notes", m.notes or f"Jag's Ship Radar {m.version}", "--latest").returncode:
        print("  ! gh release create failed; nothing new is live")
        return 1

    print("\nChecking what GitHub actually serves...")
    return verify_published(m)


if __name__ == "__main__":
    raise SystemExit(main())
