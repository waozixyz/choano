; Choano's per-user Windows installer. scripts/desktop_release.py passes
; VERSION, STAGE (the program, its font and assets), ICON and OUTFILE.
Unicode true
SetCompressor /SOLID lzma
RequestExecutionLevel user

!define APP "Choano"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\Choano"

Name "${APP}"
OutFile "${OUTFILE}"
Icon "${ICON}"
UninstallIcon "${ICON}"
; Installs for the current player only, so it never asks for administrator rights.
InstallDir "$LOCALAPPDATA\Programs\${APP}"
InstallDirRegKey HKCU "${UNINSTALL_KEY}" "InstallLocation"
BrandingText "${APP} ${VERSION}"
VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${APP}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "FileDescription" "${APP} installer"
VIAddVersionKey "CompanyName" "Waozi"
VIAddVersionKey "LegalCopyright" "Waozi"

Page directory
Page instfiles
UninstPage uninstConfirm
UninstPage instfiles

Section "Install"
    SetShellVarContext current
    ; A reinstall replaces the old assets rather than mixing them.
    RMDir /r "$INSTDIR\assets"
    SetOutPath "$INSTDIR"
    File /r "${STAGE}\*.*"
    WriteUninstaller "$INSTDIR\Uninstall.exe"
    ; Shortcuts start in the program folder, beside its assets.
    CreateShortCut "$SMPROGRAMS\${APP}.lnk" "$INSTDIR\Choano.exe" "" "$INSTDIR\Choano.exe" 0
    CreateShortCut "$DESKTOP\${APP}.lnk" "$INSTDIR\Choano.exe" "" "$INSTDIR\Choano.exe" 0
    WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "${APP}"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "${VERSION}"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "Publisher" "Waozi"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\Choano.exe"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "URLInfoAbout" "https://waozi.xyz"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
    WriteRegStr HKCU "${UNINSTALL_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
    WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
    WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 1
SectionEnd

; Settings in Local AppData\Choano are the player's and stay.
Section "Uninstall"
    SetShellVarContext current
    Delete "$SMPROGRAMS\${APP}.lnk"
    Delete "$DESKTOP\${APP}.lnk"
    RMDir /r "$INSTDIR\assets"
    Delete "$INSTDIR\Choano.exe"
    Delete "$INSTDIR\kryon-font.ttf"
    Delete "$INSTDIR\Uninstall.exe"
    RMDir "$INSTDIR"
    DeleteRegKey HKCU "${UNINSTALL_KEY}"
SectionEnd
