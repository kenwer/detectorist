; Inno Setup script for the Detectorist Windows installer.
; The build-windows poe task compiles it with ISCC.exe and passes the values
; below as /D defines.

#ifndef AppVersion
  #error Pass /DAppVersion=<version>
#endif
#ifndef NumericVersion
  #error Pass /DNumericVersion=<a.b.c.d>
#endif
#ifndef SourceDir
  #error Pass /DSourceDir=<the Nuitka .dist folder>
#endif
#ifndef OutputDir
  #error Pass /DOutputDir=<folder for the installer>
#endif
#ifndef OutputBaseFilename
  #error Pass /DOutputBaseFilename=<installer name without .exe>
#endif
#ifndef IconFile
  #error Pass /DIconFile=<app.ico>
#endif

[Setup]
; Never change the AppId: Windows identifies the installed app by it
AppId={{4360D237-E4A1-4712-B03A-429F089F33A8}
AppName=Detectorist
AppVersion={#AppVersion}
AppPublisher=de.ken
AppPublisherURL=https://github.com/kenwer/detectorist
VersionInfoVersion={#NumericVersion}
; Per user: no admin prompt to install or to update, and {autopf} resolves
; to %LOCALAPPDATA%\Programs
PrivilegesRequired=lowest
DefaultDirName={autopf}\Detectorist
; Fixed, because [InstallDelete] empties it. A user-picked folder could
; hold other files.
DisableDirPage=yes
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\Detectorist.exe
SetupIconFile={#IconFile}
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; The Restart Manager finds a running Detectorist.exe and offers to close it,
; since its files cannot be replaced while it runs
CloseApplications=yes

[InstallDelete]
; The folder holds only the app, so an update leaves exactly the new version
Type: filesandordirs; Name: "{app}\*"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Detectorist"; Filename: "{app}\Detectorist.exe"

[Run]
Filename: "{app}\Detectorist.exe"; Description: "Launch Detectorist"; Flags: nowait postinstall skipifsilent
