# Builds dist\JagsShipRadar\JagsShipRadar.exe, then dist\Jags-Ship-Radar-Setup-<version>.exe.
# Release:  build.ps1  ->  tools\sign_release.py --notes "..."  ->  tools\publish_github.py
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) { python -m venv .venv }
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install -q -r requirements.txt pyinstaller==6.11.1

& $py -m unittest discover -s tests
if ($LASTEXITCODE -ne 0) { throw "Tests failed" }

$version = & $py -c "import ship_radar; print(ship_radar.__version__)"
& $py tools\make_icon.py build\icon.ico
& $py -m PyInstaller --noconfirm --clean --windowed --name JagsShipRadar --icon build\icon.ico `
    --hidden-import pystray._win32 jagsshipradar.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# The exe isn't code-signed, so Defender's machine-learning check now and then flags a fresh build
# (0.4.2 was quarantined as Trojan:Win32/Bearfoos.A!ml). A rebuild gets a new fingerprint; never ship a flagged one.
function Assert-DefenderClean($path) {
    $mp = "$env:ProgramFiles\Windows Defender\MpCmdRun.exe"
    if (-not (Test-Path $mp)) { Write-Warning "Defender isn't available; $path was not scanned."; return }
    $out = & $mp -Scan -ScanType 3 -File (Resolve-Path $path).Path -DisableRemediation | Out-String
    if ($LASTEXITCODE -ne 0) { throw "Defender flags ${path}:`n$out`nRun build.ps1 again for a fresh build." }
    Write-Host "Defender: $path is clean"
}
Assert-DefenderClean dist\JagsShipRadar\JagsShipRadar.exe

$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found. The app is in dist\JagsShipRadar\." }
& $iscc /Q "/DAppVersion=$version" installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

$setup = "dist\Jags-Ship-Radar-Setup-$version.exe"
Assert-DefenderClean $setup
$max = [int64](& $py -c "from ship_radar.update import trust; print(trust.INSTALLER_MAX_BYTES)")
$size = (Get-Item $setup).Length
if ($size -gt $max) { throw "$setup is $size bytes, over the $max the updater will download (trust.INSTALLER_MAX_BYTES)." }
Write-Host ("Built {0} ({1:N1} MB)" -f $setup, ($size / 1MB))
