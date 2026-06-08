@echo off
chcp 65001 >nul
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"

set "PORT=8501"

if not exist ".venv\Scripts\python.exe" (
    echo 未找到虚拟环境，请先双击运行 install.bat。
    exit /b 1
)

rem 检测端口是否已有服务在监听
netstat -ano | findstr ":%PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    if exist ".run.pid" (
        for /f %%P in (.run.pid) do set "OLD_PID=%%P"
        if defined OLD_PID (
            echo 端口 %PORT% 已有服务运行，正在停止旧进程 %OLD_PID%...
            taskkill /PID %OLD_PID% /T /F >nul 2>&1
            ping -n 2 127.0.0.1 >nul
        )
    ) else (
        echo 端口 %PORT% 已有服务运行，但未找到 PID 文件。
        echo 请先在应用侧边栏点击 [关闭应用]，或手动结束占用端口的进程。
        start "" "http://localhost:%PORT%/"
        exit /b 0
    )
)

echo 正在后台启动 Streamlit（端口 %PORT%）...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$root = '%ROOT%';" ^
  "$py = Join-Path $root '.venv\Scripts\python.exe';" ^
  "$app = Join-Path $root 'streamlit_app.py';" ^
  "$pidFile = Join-Path $root '.run.pid';" ^
  "if (-not (Test-Path $app)) { Write-Host '入口文件 streamlit_app.py 不存在。'; exit 1 }" ^
  "$args = @('-m','streamlit','run',$app,'--server.port','%PORT%','--server.headless','true');" ^
  "$p = Start-Process -FilePath $py -ArgumentList $args -WindowStyle Hidden -WorkingDirectory $root -PassThru;" ^
  "$p.Id | Out-File -Encoding ascii $pidFile;" ^
  "Write-Host ('已启动，PID=' + $p.Id)"

echo 等待服务就绪...
ping -n 4 127.0.0.1 >nul

start "" "http://localhost:%PORT%/"

echo.
echo 应用已在后台运行（端口 %PORT%）。
echo 关闭此窗口不会停止服务；在应用侧边栏点击 [关闭应用] 可停止。
exit /b 0
