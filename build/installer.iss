; Inno Setup script for VoxMorph.
; Produces VoxMorph-<version>-Setup.exe - the artifact the auto-updater
; downloads and runs.
;
; Compile:  iscc /DMyAppVersion=1.0.0 build\installer.iss

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#define MyAppName "VoxMorph"
#define MyAppPublisher "VoxMorph"
#define MyAppURL "https://voxmorph.app"
#define MyAppExeName "VoxMorph.exe"

[Setup]
AppId={{8F3C1A62-7D4E-4C29-9E1B-2A6F5D0B7C31}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/support
AppUpdatesURL={#MyAppURL}/download
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist\installer
OutputBaseFilename=VoxMorph-{#MyAppVersion}-Setup
SetupIconFile=..\assets\voxmorph.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; Lets the updater replace files while the app is running
CloseApplications=yes
RestartApplications=yes
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "startup"; Description: "Start {#MyAppName} when Windows starts"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
Source: "..\dist\VoxMorph\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Leave user voices/profiles alone; only remove caches.
Type: filesandordirs; Name: "{localappdata}\VoxMorph\cache"

[Code]
// Warn the user if no virtual audio cable is present - without one, other
// applications cannot hear the converted voice.
function VirtualCableInstalled(): Boolean;
var
  Names: TArrayOfString;
  I: Integer;
begin
  Result := False;
  if RegGetSubkeyNames(HKLM, 'SYSTEM\CurrentControlSet\Services', Names) then
    for I := 0 to GetArrayLength(Names) - 1 do
      if (Pos('vbaudio', LowerCase(Names[I])) > 0)
        or (Pos('voicemeeter', LowerCase(Names[I])) > 0) then
      begin
        Result := True;
        Exit;
      end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and (not VirtualCableInstalled()) then
    MsgBox('VoxMorph works best with a virtual audio cable so apps like '
      + 'Discord, OBS and games can hear your converted voice.' + #13#10#13#10
      + 'If you have not installed one yet, get VB-CABLE (free) from'
      + #13#10 + 'https://vb-audio.com/Cable/', mbInformation, MB_OK);
end;
