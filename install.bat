@echo off
echo ========================================
echo Excel Template Viz - Gradio Version
echo Installation Script
echo ========================================
echo.

REM Check Python version and recommend Python 3.10 for best compatibility
echo Checking Python version...
python --version >nul 2>&1
if errorlevel 1 (
    py -3.10 --version >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Python is not installed or not in PATH
        echo Please install Python 3.10 (recommended for best wheel support)
        pause
        exit /b 1
    ) else (
        echo Found Python 3.10 via 'py' launcher
        echo Using Python 3.10 (recommended)
        set PYTHON_CMD=py -3.10
        goto :python_found
    )
)

REM Check if current Python is 3.10 or 3.11 (best wheel support)
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo Current Python version: %PYTHON_VERSION%

echo %PYTHON_VERSION% | findstr /R "3\.1[01]\." >nul
if errorlevel 1 (
    echo.
    echo WARNING: Python %PYTHON_VERSION% may have limited pre-built wheel support
    echo Recommended: Python 3.10 or 3.11 for best compatibility
    echo.
    py -3.10 --version >nul 2>&1
    if not errorlevel 1 (
        echo Found Python 3.10 installed (via 'py -3.10')
        echo.
        choice /C YN /N /M "Switch to Python 3.10 for installation? (Y/N): "
        if not errorlevel 2 (
            set PYTHON_CMD=py -3.10
            echo Switching to Python 3.10...
            goto :python_found
        )
    )
)

set PYTHON_CMD=python

:python_found
echo Using: %PYTHON_CMD%
%PYTHON_CMD% --version
echo.

echo Creating virtual environment...
%PYTHON_CMD% -m venv .venv
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
%PYTHON_CMD% -m pip install --upgrade pip

echo.
echo Installing dependencies (pure Python, no compilation)...
echo.
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)

echo.
echo ========================================
echo Installation completed successfully!
echo ========================================
echo.
echo To start the application, run: run.bat
echo.
pause
