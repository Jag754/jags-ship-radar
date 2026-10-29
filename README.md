# Jag's Ship Radar

Pings you on screen (with a sound) when a ship loads in near you in Star Citizen. It reads the game's own
`Game.log`, so the in-game console doesn't need to be open.

## Install

Download `Jags-Ship-Radar-Setup-<version>.exe` from the [latest release](../../releases/latest) and run it.
It installs for your Windows account only (no admin prompt) and can start
with Windows. The app lives in the system tray.

**Set the game to Borderless Window** (Graphics settings). Exclusive fullscreen hides every overlay,
including this one. Sounds still play.

Because the exe isn't code-signed, Windows SmartScreen may say "Windows protected your PC" the first time.
Choose **More info → Run anyway**.

## Using it

| | |
|---|---|
| **Ctrl+Shift+F8** | Turn alerts on/off (works while the game has focus). Only claimed while Star Citizen is running, so the keys are free for other programs the rest of the time |
| Blue alert | New ship |
| Grey alert, "RE-PING ×N" | A ship you already saw loaded in again, with when you first saw it |
| Red alert | A ship on your priority list (capital ships by default) |
| Amber "Busy area" alert | Lots of ships at once (arriving at a station). It keeps grouping until it calms down; priority ships still alert immediately |

Ships you board (yours or a friend's) go quiet automatically after the crew channel joins.

Tray menu: turn alerts on/off, show a test alert, move or resize the alerts, show the nearby ships list, change the hotkey, mute or
set the volume, have ship names read out, choose Game.log by hand, open or reload settings, quit.

**Change hotkey…** opens a small window: press the new combination and click Save. It warns you if another
program already uses it, or if a plain key would need Ctrl, Alt or Shift.

**Sound** mutes the pings or sets their volume (100% down to 10%). You hear a sample ping at the new level.
Your own `sound_file` .wav files follow the volume too. Alerts still show on screen while muted.

**Sound → Speak ship names** reads ships out loud after the ping, using the voices built into Windows:
**All new ships** (the default; re-pings stay quiet unless they're priority), **Priority ships only**
(priority ships, and busy areas that include one), or **Off**. It also says "Alerts on/off" when you press the
hotkey. The voice follows the volume and goes quiet when you mute. To pick a different voice, put part of
its name in `voice` in the settings file, e.g. `"Zira"`.

**Nearby ships list** (tray, or **Ctrl+Shift+F9** in game) shows the ships that loaded in around you in
the last 10 minutes: priority ships first, then newest first, with how long ago each was seen and how many
times it re-pinged. The game log says when a ship loads in but never when it leaves, so a ship dims after a
few minutes and drops off after 10 unless it loads in again. Ships you're aboard are left out. Like the
alerts, it never takes the mouse or focus. **Move / resize nearby list…** places it, and `nearby_minutes`
changes the 10 minutes.

**Move / resize alerts…** shows a stand-in you can drag anywhere and resize from the corner grip (60–200%).
Click Done (or Enter) to save, Cancel (or Esc) to leave it as it was. Alerts stack away from the nearest corner.

## Settings

Tray → **Open settings file** (`%APPDATA%\JagsShipRadar\config.json`), edit, then tray → **Reload settings**.
The file has a `_help` section explaining every option: hotkey, corner and size, how long alerts stay,
sounds and speech, priority and ignore lists, renaming ships.

If a game patch changes the log line and alerts stop, `ship_line_regex` is the line to fix.

## What it can't do

It sees ships when the game loads them in around you (the game's loading range). That's not radar: it can't
tell who is flying or whether they're hostile, and a ship that drifts in and out of range will re-ping.

## Developing

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m ship_radar                          # run against the live log
.venv\Scripts\python -m ship_radar --replay Game.log --speed 30   # replay an old log on screen
.venv\Scripts\python -m ship_radar --replay Game.log --console    # print what it would show
.venv\Scripts\python -m unittest discover -s tests
powershell -ExecutionPolicy Bypass -File build.ps1             # exe + installer (needs Inno Setup 6)
```

## Releasing an update

1. Bump `__version__` in `ship_radar/__init__.py`.
2. `powershell -ExecutionPolicy Bypass -File build.ps1`
3. `.venv\Scripts\python.exe tools\sign_release.py --notes "What changed"`
4. `.venv\Scripts\python.exe tools\publish_github.py` (needs the GitHub CLI, signed in)

`build.ps1` stops if Windows Defender flags the new exe or installer. The exe isn't code-signed, so
Defender's machine-learning check occasionally flags a fresh build; building again gives a clean one.

Installed copies check GitHub at startup and every 6 hours, show an "Update available" alert, and install
from the tray menu. An update installs only if its `latest.json` is signed with the maintainer's release
key (Ed25519, public half in `ship_radar/update/trust.py`) and the installer matches the signed checksum,
so nobody else can publish an update, even with access to the GitHub repo. A release can't be rolled back
by re-marking an older one as latest: installed copies refuse an older serial. Fix forward instead.

App log for troubleshooting: `%APPDATA%\JagsShipRadar\app.log`.
