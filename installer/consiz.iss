; Consiz installer (Inno Setup 6.3 or newer). Build with:  python scripts/build_installer.py
; (that script runs `python build_exe.py` first if needed, then calls ISCC with /DAppVersion=<version>).
;
; Per-user install: no administrator rights, no UAC prompt, files go to %LOCALAPPDATA%\Programs\Consiz.
; Settings and sign-in live in the user's profile (~/.consiz) and are NOT removed on uninstall.
;
; CODE SIGNING: until the team buys a certificate, Windows shows "Windows protected your PC" (SmartScreen).
; When a certificate exists, add SignTool=... under [Setup] (see Inno Setup docs: "SignTool") and sign Consiz.exe too.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; Never change this GUID: Windows uses it to recognise an older install and update it in place.
AppId={{CAC98BE1-3362-4791-884B-D84D77265706}
AppName=Consiz
AppVersion={#AppVersion}
AppVerName=Consiz {#AppVersion}
AppPublisher=Consiz
DefaultDirName={autopf}\Consiz
DefaultGroupName=Consiz
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Consiz-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\Consiz.exe
UninstallDisplayName=Consiz
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Consiz keeps one instance running (this is the named mutex main.py creates). Setup asks the user to close it first,
; and an update installs over the old files cleanly.
AppMutex=ConsizSingleInstanceMutex
CloseApplications=yes
RestartApplications=no
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "autostart"; Description: "Start Consiz when I sign in to Windows"; GroupDescription: "Options:"

[Files]
Source: "..\dist\Consiz\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Consiz"; Filename: "{app}\Consiz.exe"

[Registry]
; The same key the tray's "Start on Windows Boot" switch uses, so the two never fight (and never start two copies).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Consiz"; ValueData: """{app}\Consiz.exe"""; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\Consiz.exe"; Description: "Start Consiz now"; Flags: nowait postinstall skipifsilent
