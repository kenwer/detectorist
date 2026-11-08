; Inno Setup script for the Detectorist Windows installer.
; The build-windows poe task compiles it with ISCC.exe and passes the values
; below as /D defines. The in-app updater runs the result with
; /VERYSILENT /SUPPRESSMSGBOXES /RELAUNCH right before the app exits.

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

[InstallDelete]
; The folder holds only the app, so an update leaves exactly the new version
Type: filesandordirs; Name: "{app}\*"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Detectorist"; Filename: "{app}\Detectorist.exe"

[Run]
Filename: "{app}\Detectorist.exe"; Description: "Launch Detectorist"; Flags: nowait postinstall skipifsilent
Filename: "{app}\Detectorist.exe"; Flags: nowait; Check: ShouldRelaunch

[Code]
const
  { Must match MUTEX_NAME in src/detectorist/running_mutex.py }
  RunningMutex = 'DetectoristRunning';

function ShouldRelaunch: Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), '/RELAUNCH') = 0 then
      Result := True;
end;

function InitializeSetup: Boolean;
var
  Tries: Integer;
begin
  if WizardSilent then
  begin
    { The updater starts Setup while the app is still shutting down }
    Tries := 0;
    while CheckForMutexes(RunningMutex) and (Tries < 120) do
    begin
      Sleep(500);
      Tries := Tries + 1;
    end;
  end
  else
    while CheckForMutexes(RunningMutex) do
      if MsgBox('Detectorist is running. Close it, then select Retry.', mbError, MB_RETRYCANCEL) = IDCANCEL then
        Break;
  Result := not CheckForMutexes(RunningMutex);
  if not Result then
    Log('Detectorist is still running, Setup stops');
end;

function InitializeUninstall: Boolean;
begin
  Result := not CheckForMutexes(RunningMutex);
  if not Result then
    MsgBox('Detectorist is running. Close it, then uninstall again.', mbError, MB_OK);
end;
