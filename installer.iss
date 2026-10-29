; Inno Setup 6 script. Build with build.ps1, which passes /DAppVersion from ship_radar/__init__.py.
#define AppName "Jag's Ship Radar"
#ifndef AppVersion
  #error Build with build.ps1 so the version comes from ship_radar/__init__.py
#endif
#define AppExe "JagsShipRadar.exe"

[Setup]
AppId={{6C1F3E0A-5B7D-4C59-9E2B-2E8B7A4D6F11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Jag
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Installs for the current user only, so no admin prompt.
PrivilegesRequired=lowest
OutputDir=dist
; The updater only accepts exactly this name (ship_radar/update/trust.py).
OutputBaseFilename=Jags-Ship-Radar-Setup-{#AppVersion}
SetupIconFile=build\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "startup"; Description: "Start {#AppName} when Windows starts"; GroupDescription: "Options:"
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Options:"; Flags: unchecked

[Files]
Source: "dist\JagsShipRadar\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; A new build replaces the old bundle completely, so no stale library from an older version is loaded.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: startup

[Run]
; Started by the app's own updater: bring the app back without asking.
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: RestartRequested
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName} now"; Flags: nowait postinstall skipifsilent; Check: not RestartRequested

[Code]
function RestartRequested: Boolean;
begin
  Result := ExpandConstant('{param:RESTARTRADAR|0}') = '1';
end;
