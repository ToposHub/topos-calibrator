; Topos Calibrator Windows Installer Script
; ==========================================
; 
; NSIS (Nullsoft Scriptable Install System) 安装器脚本
; 创建 Windows 安装程序 (.exe)
;
; 使用方法:
;   makensis packaging/windows/installer.nsi
;
; 需要安装 NSIS: https://nsis.sourceforge.io/

!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"

; ========== 应用信息 ==========
!define APP_NAME "Topos Calibrator"
!define APP_VERSION "0.1.0-preview"
!define APP_PUBLISHER "Topos Calibrator Team"
!define APP_URL "https://toposcalibrator.com"
!define APP_GUID "com.toposcalibrator.app"

; ========== 安装信息 ==========
!define INSTALL_DIR "$PROGRAMFILES64\${APP_NAME}"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
!define REG_ROOT "HKLM"

; ========== UI 设置 ==========
!define MUI_ICON "packaging\windows\ToposCalibrator.ico"
!define MUI_UNICON "packaging\windows\ToposCalibrator.ico"
!define MUI_ABORTWARNING

; ========== 输出文件 ==========
Name "${APP_NAME}"
OutFile "dist\ToposCalibrator-${APP_VERSION}-Setup.exe"
InstallDir "${INSTALL_DIR}"
RequestExecutionLevel admin

; ========== 页面顺序 ==========
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "LICENSE"
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\Topos Calibrator.exe"
!define MUI_FINISHPAGE_RUN_TEXT "启动 Topos Calibrator"
!define MUI_FINISHPAGE_LINK "访问官网获取更多信息"
!define MUI_FINISHPAGE_LINK_LOCATION "${APP_URL}"
!insertmacro MUI_PAGE_FINISH

; ========== 卸载页面 ==========
!insertmacro MUI_UNPAGE_WELCOME
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

; ========== 语言 ==========
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "SimpChinese"

; ========== 安装组件 ==========
Section "!${APP_NAME} (必需)" SecMain
    SectionIn RO
    
    SetOutPath "$INSTDIR"
    
    ; 复制主程序
    File /r "dist\Topos Calibrator\*"
    
    ; 创建卸载器
    WriteUninstaller "$INSTDIR\Uninstall.exe"
    
    ; 注册安装信息
    WriteRegStr ${REG_ROOT} "${UNINSTALL_KEY}" "DisplayName" "${APP_NAME}"
    WriteRegStr ${REG_ROOT} "${UNINSTALL_KEY}" "DisplayVersion" "${APP_VERSION}"
    WriteRegStr ${REG_ROOT} "${UNINSTALL_KEY}" "Publisher" "${APP_PUBLISHER}"
    WriteRegStr ${REG_ROOT} "${UNINSTALL_KEY}" "UninstallString" "$INSTDIR\Uninstall.exe"
    WriteRegStr ${REG_ROOT} "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
    WriteRegStr ${REG_ROOT} "${UNINSTALL_KEY}" "URLInfoAbout" "${APP_URL}"
    WriteRegDWORD ${REG_ROOT} "${UNINSTALL_KEY}" "NoModify" 1
    WriteRegDWORD ${REG_ROOT} "${UNINSTALL_KEY}" "NoRepair" 1
    
    ; 计算安装大小
    ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
    IntFmt $0 "0x%08X" $0
    WriteRegDWORD ${REG_ROOT} "${UNINSTALL_KEY}" "EstimatedSize" "$0"
    
    ; 创建快捷方式
    CreateDirectory "$SMPROGRAMS\${APP_NAME}"
    CreateShortCut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\Topos Calibrator.exe"
    CreateShortCut "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
    
    ; 创建桌面快捷方式
    CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\Topos Calibrator.exe"
SectionEnd

Section "修正文件 (CCSS/CCMX)" SecCorrections
    SetOutPath "$INSTDIR\corrections"
    
    IfFileExists "dist\Topos Calibrator\corrections\*" +2 0
    Return
    
    File /r "dist\Topos Calibrator\corrections\*"
SectionEnd

Section "文档和示例" SecDocs
    SetOutPath "$INSTDIR\docs"
    File /r "docs\*"

    ; 示例数据是可选目录，存在时才复制，避免空项目无法编译安装器。
    !ifexist "measurements\examples"
        SetOutPath "$INSTDIR\measurements\examples"
        File /r "measurements\examples\*"
    !endif
SectionEnd

; ========== 组件描述 ==========
LangString DESC_SecMain ${LANG_ENGLISH} "Topos Calibrator 主程序 (必需)"
LangString DESC_SecMain ${LANG_SIMPCHINESE} "Topos Calibrator 主程序 (必需)"
LangString DESC_SecCorrections ${LANG_ENGLISH} "Colorimeter correction files (CCSS/CCMX)"
LangString DESC_SecCorrections ${LANG_SIMPCHINESE} "色度计修正文件 (CCSS/CCMX)"
LangString DESC_SecDocs ${LANG_ENGLISH} "Documentation and example measurements"
LangString DESC_SecDocs ${LANG_SIMPCHINESE} "文档和示例测量数据"

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
    !insertmacro MUI_DESCRIPTION_TEXT ${SecMain} $(DESC_SecMain)
    !insertmacro MUI_DESCRIPTION_TEXT ${SecCorrections} $(DESC_SecCorrections)
    !insertmacro MUI_DESCRIPTION_TEXT ${SecDocs} $(DESC_SecDocs)
!insertmacro MUI_FUNCTION_DESCRIPTION_END

; ========== 安装后操作 ==========
Function .onInstSuccess
    ; 提示用户设置权限
    MessageBox MB_YESNO "安装完成！$\n$\nTopos Calibrator 需要以下权限:$\n1. USB 设备访问 (校色仪)$\n2. 显示器控制 (DDC/CI)$\n$\n是否立即打开权限设置指南？" IDNO +2
        ExecShell "open" "$INSTDIR\docs\windows_permissions.md"
FunctionEnd

; ========== 卸载程序 ==========
Section "Uninstall"
    ; 删除安装文件
    RMDir /r "$INSTDIR"
    
    ; 删除快捷方式
    Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
    Delete "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk"
    RMDir "$SMPROGRAMS\${APP_NAME}"
    Delete "$DESKTOP\${APP_NAME}.lnk"
    
    ; 删除注册信息
    DeleteRegKey ${REG_ROOT} "${UNINSTALL_KEY}"
    
    ; 删除用户数据（可选）
    MessageBox MB_YESNO "是否删除用户测量数据?$\n位置: $APPDATA\${APP_NAME}" IDNO +3
        RMDir /r "$APPDATA\${APP_NAME}"
        MessageBox MB_OK "用户数据已删除"
SectionEnd

; ========== 安装前检查 ==========
Function .onInit
    ; 检查 Windows 版本
    ${If} ${AtLeastWin10}
        ; Windows 10+ 支持 HDR 和 ACM
    ${Else}
        MessageBox MB_OK "警告: Topos Calibrator 在 Windows 10 或更高版本上运行最佳。$\n$\n当前系统版本较低，某些功能可能受限。"
    ${EndIf}
    
    ; 检查是否已安装
    ReadRegStr $0 ${REG_ROOT} "${UNINSTALL_KEY}" "UninstallString"
    ${If} $0 != ""
        MessageBox MB_YESNO "检测到已安装 ${APP_NAME}。$\n$\n是否卸载旧版本后继续安装?" IDNO +2
            ExecWait '"$0"'
    ${EndIf}
FunctionEnd
