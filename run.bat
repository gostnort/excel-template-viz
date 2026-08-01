@echo off
echo Starting Excel Template Viz - NiceGUI...
echo.

where uv >nul 2>&1
if not errorlevel 1 (
    uv run python -m nicegui_ui.app
    goto :after_run
)

if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
    python -m nicegui_ui.app
    goto :after_run
)

echo ERROR: uv not found and .venv missing
echo Please run install.bat first
pause
exit /b 1

:after_run
if errorlevel 1 (
    echo.
    echo Application exited with an error
    pause
)
