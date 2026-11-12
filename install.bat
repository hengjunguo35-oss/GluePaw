@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在把依赖安装到项目内的 libs 目录...
python -m pip install --target libs -r requirements.txt
if errorlevel 1 (
    echo 安装失败，请检查 Python 是否已安装并加入 PATH。
    pause
    exit /b 1
)
echo.
echo 安装完成。双击 run.bat 启动。
pause
