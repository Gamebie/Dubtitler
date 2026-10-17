#define MyAppName "Dubtitler"
#define MyAppVersion "0.1.0"
[Setup]
AppId={{C2F9ED0C-85A5-4D5A-9080-E2CB59BB4F61}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\Dubtitler
DefaultGroupName=Dubtitler
OutputDir=output
OutputBaseFilename=Dubtitler-Setup
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
WizardStyle=modern
UninstallDisplayIcon={app}\Dubtitler.exe
[Files]
Source: "..\dist\Dubtitler\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
[Icons]
Name: "{autoprograms}\Dubtitler"; Filename: "{app}\Dubtitler.exe"
Name: "{autodesktop}\Dubtitler"; Filename: "{app}\Dubtitler.exe"; Tasks: desktopicon
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"
[Run]
Filename: "{app}\Dubtitler.exe"; Description: "Launch Dubtitler"; Flags: nowait postinstall skipifsilent
