@echo off
setlocal EnableDelayedExpansion

echo ========================================
echo Excel Template Viz - NiceGUI
echo Installation Script (uv + Python 3.10)
echo ========================================
echo.

REM --- Check for winget and auto-install uv ---
where winget >nul 2>&1
if %errorlevel%==0 (
    echo Installing uv via winget...
    winget install --id astral-sh.uv -e --accept-source-agreements --accept-package-agreements
    if !errorlevel! neq 0 (
        echo WARNING: winget failed to install uv. Falling back to manual prompt.
        echo Install uv, then re-run this script:
        echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    )
)

echo Checking for uv on PATH...
where uv >nul 2>&1
if %errorlevel%==1 (
    echo ERROR: uv is not installed or not on PATH.
    echo Install uv, then re-run this script:
    echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    pause
    exit /b 1
)

echo Using uv:
uv --version
echo.

REM --- Check for Python 3.10 and auto-install via winget if missing ---
set "PY_VERSION="
py -3.10 --version >nul 2>&1
if %errorlevel%==0 (
    echo Python 3.10 found on PATH.
) else (
    py --list-versions >nul 2>&1 | findstr /C:"3.10" >nul
    if !errorlevel! neq 0 (
        echo Python 3.10 not found on PATH. Checking for winget installation...
        where winget >nul 2>&1
        if %errorlevel%==0 (
            echo Installing Python 3.10 via winget...
            winget install --id Python.Python.3.10 -e --accept-source-agreements --accept-package-agreements
            if !errorlevel! neq 0 (
                echo WARNING: winget failed to install Python 3.10. Falling back to manual prompt.
                echo Please install Python 3.10 manually, then re-run this script.
            )
        ) else (
            echo WARNING: winget not available and Python 3.10 is missing.
            echo Please install Python 3.10 manually, then re-run this script.
        )
    )
)

echo Using Python 3.10 for bootstrap_install.py
py -3.10 bootup\bootstrap_install.py %*

echo.
echo To start the application, run: .\run.ps1
echo Gemma 4 model (~3.66GB) downloads on first LLM/OCR use, or prefetch:
echo   uv run --project bootup python -c "from llm_gemma4.hf_download import download_litert; print(download_litert())"
echo.
pause
