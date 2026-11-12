; GluePaw 安装程序脚本（Inno Setup 6）
; 编译：ISCC.exe GluePaw.iss
; 产物：..\dist\GluePaw-1.0.0-Setup.exe

#define MyAppName "GluePaw"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "hengjunguo35-oss"
#define MyAppURL "https://github.com/hengjunguo35-oss/GluePaw"
#define MyAppExeName "GluePaw.exe"
#define MyAppExeSource "..\dist\GluePaw-1.0.0-Windows-x64.exe"

[Setup]
AppId={{8F3C2A1E-6B4D-4E7A-9C1F-2A5B7D9E3C11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=GluePaw-{#MyAppVersion}-Setup
SetupIconFile=GluePaw.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
MinVersion=10.0

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"; Flags: unchecked

[Files]
Source: "{#MyAppExeSource}"; DestDir: "{app}"; DestName: "{#MyAppExeName}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent

; 卸载时保留 %LOCALAPPDATA%\GluePaw（用户的剪贴板历史与密钥），不在此删除。
