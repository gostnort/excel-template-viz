@echo off
echo Starting Excel Template Viz - Gradio Version...
echo.

REM Activate virtual environment
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Virtual environment not found
    echo Please run install.bat first
    pause
    exit /b 1
)

REM Start Gradio application
python gradio_app.py

REM If the script exits, pause to see any error messages
if errorlevel 1 (
    echo.
    echo Application exited with an error
    pause
)
