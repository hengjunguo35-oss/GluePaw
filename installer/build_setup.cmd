@echo off
rem GluePaw 安装程序构建脚本
rem 前提：先用 PyInstaller 构建目录版（onedir）产物：
rem   pyinstaller --onedir --windowed --icon GluePaw.ico --name GluePaw main.py
rem   产物目录：gluepaw-dev\dist-onedir\GluePaw
setlocal
cd /d "%~dp0"

set "PAYLOAD=%~dp0payload.zip"
set "SRCDIR=..\..\gluepaw-dev\dist-onedir\GluePaw"

if not exist "%SRCDIR%\GluePaw.exe" (
    echo 未找到目录版产物：%SRCDIR%
    exit /b 1
)

echo [1/2] 压缩目录版到 payload.zip ...
powershell -NoProfile -Command "Compress-Archive -Path '%SRCDIR%\*' -DestinationPath '%PAYLOAD%' -CompressionLevel Optimal -Force"

echo [2/2] 编译安装程序 ...
"%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /target:winexe /optimize+ /out:"..\dist\GluePaw-1.0.0-Setup.exe" /win32icon:"GluePaw.ico" /resource:"%PAYLOAD%" /r:Microsoft.CSharp.dll /r:System.IO.Compression.dll /r:System.IO.Compression.FileSystem.dll "Setup.cs"

if errorlevel 1 (
    echo 编译失败
    exit /b 1
)
echo 完成：..\dist\GluePaw-1.0.0-Setup.exe
endlocal
