@echo off
echo ========================================
echo Excel Template Viz - NiceGUI
echo Installation Script
echo ========================================
echo.
set SKIP_OCR=0
:parse_args
if "%~1"=="" goto :args_done
if /I "%~1"=="--skip-ocr" (
    set SKIP_OCR=1
    shift
    goto :parse_args
)
echo WARNING: Unknown argument: %~1
shift
goto :parse_args
:args_done
if "%SKIP_OCR%"=="1" (
    echo OCR install: SKIPPED (--skip-ocr)
) else (
    echo OCR install: enabled by default ^(pass --skip-ocr to skip^)
)
echo Gemma 4: litert-lm from requirements.txt; model downloads on first use.
echo Optional LLM_PROFILE: auto ^(default^), cpu, cuda, openvino — see docs/embed_gemma4.md
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
python -m pip install --upgrade pip

echo.
echo Installing dependencies (NiceGUI, litert-lm, ...)...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)

echo.
echo Verifying litert-lm import...
python -c "import litert_lm; print('litert-lm OK')"
if errorlevel 1 (
    echo ERROR: litert-lm import failed after install
    pause
    exit /b 1
)

echo.
if not exist temp mkdir temp
if "%SKIP_OCR%"=="1" (
    echo Skipping PaddleOCR install (--skip-ocr).
    echo You can install later with:
    echo   pip install -r paddle_ocr/requirements.txt
    echo   python paddle_ocr/main.py
) else (
    echo Installing PaddleOCR platform dependencies...
    pip install -r paddle_ocr/requirements.txt >> temp\install_paddle_ocr.log 2>&1
    if errorlevel 1 (
        echo WARNING: paddle_ocr requirements failed. See temp\install_paddle_ocr.log
        echo Re-run install.bat, or continue with --skip-ocr, or install manually.
    ) else (
        echo Running OCR CLI gate (health, download, sample PaddleOcr)...
        python paddle_ocr/main.py >> temp\install_paddle_ocr.log 2>&1
        if errorlevel 1 (
            echo WARNING: OCR CLI gate failed. See temp\install_paddle_ocr.log
            echo Re-run: python paddle_ocr/main.py
        ) else (
            echo OCR CLI gate passed.
        )
    )
)

echo.
echo Creating project directories...
if not exist temp mkdir temp
if not exist exports mkdir exports
if not exist models\gemma4 mkdir models\gemma4

echo.
echo ========================================
echo Installation completed successfully!
echo ========================================
echo.
echo To start the application, run: run.bat
echo Gemma 4 model (~3.66GB) downloads on first LLM/OCR use, or prefetch:
echo   python -c "from llm_gemma4.hf_download import download_litert; print(download_litert())"
echo.
pause
