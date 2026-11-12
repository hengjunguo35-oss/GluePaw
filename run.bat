@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "libs\PySide6" (
    echo 尚未安装依赖，请先运行 install.bat
    pause
    exit /b 1
)
start "" pythonw.exe "main.py"
