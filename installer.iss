; Inno Setup Script for Consiz
; Standalone Windows Installer with Custom Path Selection & Optional Ollama Offline Mode

#define MyAppName "Consiz"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Consiz AI"
#define MyAppURL "https://github.com/MeetShah0656/Consiz-Windows"
#define MyAppExeName "Consiz.exe"

[Setup]
AppId={{8B075306-DFB8-4FE2-9E86-8E3FEA22D16A}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=ConsizSetup
SetupIconFile=assets\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=force

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startup"; Description: "Start Consiz automatically when Windows boots"; GroupDescription: "System Startup:"
Name: "installollama"; Description: "Install Ollama (for Offline AI Mode)"; GroupDescription: "AI Engine (Offline Mode):"; Flags: unchecked

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\icon.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\icon.ico"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
var
  DownloadPage: TDownloadWizardPage;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  if ProgressMax <> 0 then
    Log(Format('Downloading %s: %d of %d bytes...', [FileName, Progress, ProgressMax]))
  else
    Log(Format('Downloading %s: %d bytes...', [FileName, Progress]));
  Result := True;
end;

function IsOllamaInstalled(): Boolean;
begin
  Result := FileExists(ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe')) or
            FileExists(ExpandConstant('{pf}\Ollama\ollama.exe')) or
            FileExists(ExpandConstant('{pf32}\Ollama\ollama.exe'));
end;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage(SetupMessage(msgWizardPreparing), 'Downloading dependencies...', @OnDownloadProgress);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpReady then begin
    if WizardIsTaskSelected('installollama') then begin
      if IsOllamaInstalled() then begin
        Log('Ollama is already installed on this machine.');
      end else begin
        DownloadPage.Clear;
        DownloadPage.Add('https://ollama.com/download/OllamaSetup.exe', 'OllamaSetup.exe', '');
        DownloadPage.Show;
        try
          try
            DownloadPage.Download;
          except
            if DownloadPage.AbortedByUser then
              Log('Ollama download aborted by user.')
            else
              SuppressibleMsgBox('Could not download Ollama: ' + GetExceptionMessage + #13#10#13#10 + 'You can download and install Ollama manually at https://ollama.com', mbInformation, MB_OK, IDOK);
          end;
        finally
          DownloadPage.Hide;
        end;
      end;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  OllamaInstallerPath: String;
begin
  if CurStep = ssPostInstall then begin
    if WizardIsTaskSelected('installollama') and (not IsOllamaInstalled()) then begin
      OllamaInstallerPath := ExpandConstant('{tmp}\OllamaSetup.exe');
      if FileExists(OllamaInstallerPath) then begin
        WizardForm.StatusLabel.Caption := 'Installing Ollama for Offline AI Mode...';
        Exec(OllamaInstallerPath, '/silent', '', SW_SHOW, ewWaitUntilTerminated, ResultCode);
      end;
    end;
  end;
end;
