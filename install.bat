@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ========================================
echo   Excel 模板可视化 - 环境安装
echo ========================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [1/2] 正在创建虚拟环境 .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo 错误：无法创建虚拟环境，请确认已安装 Python 3.10 或更高版本。
        exit /b 1
    )
    echo       虚拟环境创建完成。
) else (
    echo [1/2] 虚拟环境 .venv 已存在，跳过创建。
)

echo.
echo [2/2] 正在安装/更新依赖（requirements.txt）...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>&1
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo 错误：依赖安装失败，请检查网络或 requirements.txt。
    exit /b 1
)

echo.
echo 安装完成！请运行 run.bat 启动应用。
echo Google 连接请在应用内「数据源」Tab 按页面指引操作。
exit /b 0
