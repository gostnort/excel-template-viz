@echo off
echo ========================================
echo Excel Template Viz - Gradio Version
echo Installation Script
echo ========================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.9 or higher
    pause
    exit /b 1
)

echo Creating virtual environment...
python -m venv .venv
if errorlevel 1 (
    echo ERROR: Failed to create virtual environment
    pause
    exit /b 1
)

echo.
echo Activating virtual environment...
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment
    pause
    exit /b 1
)

echo.
echo Upgrading pip...
python -m pip install --upgrade pip

echo.
echo Installing dependencies...
echo Note: Using pre-built wheels to avoid compilation requirements
echo.
pip install -r requirements.txt --prefer-binary
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    echo.
    echo Troubleshooting:
    echo - Ensure you have Python 3.9-3.12 (llama-cpp-python wheels may not support newer versions)
    echo - Check your internet connection
    echo - Try: pip install --upgrade pip
    pause
    exit /b 1
)

echo.
echo Downloading Phi-4 GGUF model...
python scripts/download_phi4_model.py
if errorlevel 1 (
    echo WARNING: Model download failed
    echo You can try downloading manually later
)

echo.
echo ========================================
echo Installation completed successfully!
echo ========================================
echo.
echo To start the application, run: run_gradio.bat
echo.
pause
