@echo off
echo Starting Excel Template Viz 0.1 (NiceGUI)...
echo.

REM Activate virtual environment
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Virtual environment not found
    echo Please run install.bat first
    pause
    exit /b 1
)

REM Start NiceGUI application
python -m nicegui_ui.app

REM If the script exits, pause to see any error messages
if errorlevel 1 (
    echo.
    echo Application exited with an error
    pause
)
