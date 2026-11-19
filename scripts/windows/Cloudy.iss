[Setup]
AppId={{D5CB94C6-675A-4F22-8A67-48356FA2B5BA}
AppName=Cloudy
AppVersion=0.1.0
DefaultDirName={localappdata}\Programs\Cloudy
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.17763
AppMutex=Local\CloudyDesktopAssistant
UninstallDisplayIcon={app}\Cloudy.exe
SetupIconFile={#Payload}\Cloudy.ico
OutputDir={#Output}
OutputBaseFilename=Cloudy-Setup-x64
WizardStyle=modern
Compression=zip/1
DiskSpanning=yes
DiskSliceSize=2000000000
SlicesPerDisk=26

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"

[Files]
Source: "{#Payload}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{autoprograms}\Cloudy"; Filename: "{app}\Cloudy.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Cloudy"; Filename: "{app}\Cloudy.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\Cloudy.exe"; Description: "{cm:LaunchProgram,Cloudy}"; Flags: nowait postinstall skipifsilent
