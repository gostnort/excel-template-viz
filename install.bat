@echo off
setlocal EnableDelayedExpansion

echo ========================================
echo Excel Template Viz - NiceGUI
echo Installation Script (uv + Python 3.10)
echo ========================================
echo.

REM --- Check if uv already exists; only auto-install if missing ---
where uv >nul 2>&1
if %errorlevel%==1 (
    echo uv not found on PATH. Auto-installing via winget...
    where winget >nul 2>&1
    if %errorlevel%==0 (
        winget install --id astral-sh.uv -e --accept-source-agreements --accept-package-agreements
        if !errorlevel! neq 0 (
            echo WARNING: winget failed to install uv. Falling back to manual prompt.
            echo Install uv, then re-run this script:
            echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
        )
    ) else (
        echo WARNING: winget not available and uv is missing on PATH.
        echo Install uv, then re-run this script:
        echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
        pause
        exit /b 1
    )
)

echo Using uv:
uv --version
echo.

REM --- Check for Python 3.10 ---
set "PY_OK=0"
py -3.10 --version >nul 2>&1 && set "PY_OK=1"
if %PY_OK%==1 (
    echo Python 3.10 found on PATH via py -3.10.
) else (
    REM Try python3.10 as a fallback
    python3.10 --version >nul 2>&1 && set "PY_OK=1"
    if %PY_OK%==1 (
        echo Python 3.10 found on PATH via python3.10.
    ) else (
        REM Try py --list to detect available versions
        py --list >nul 2>&1 | findstr /C:"-V:3.10" >nul
        if !errorlevel!==0 set "PY_OK=1"
        if %PY_OK%==1 (
            echo Python 3.10 found via py --list.
        ) else (
            echo Python 3.10 not found on PATH. Checking for winget installation...
            where winget >nul 2>&1
            if %errorlevel%==0 (
                echo Installing Python 3.10 via winget...
                winget install --id Python.Python.3.10 -e --accept-source-agreements --accept-package-agreements
                if !errorlevel! neq 0 (
                    echo WARNING: winget failed to install Python 3.10. Falling back to manual prompt.
                    echo Please install Python 3.10 manually, then open a NEW terminal and re-run this script.
                ) else (
                    echo NOTE: Python was just installed via winget. If py -3.10 still fails in this window, please open a new terminal and re-run this script to refresh PATH.
                )
            ) else (
                echo WARNING: winget not available and Python 3.10 is missing on PATH.
                echo Please install Python 3.10 manually, then open a NEW terminal and re-run this script to refresh PATH.
            )
        )
    )
)

REM --- Final verification: py -3.10 must work before continuing ---
py -3.10 --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python 3.10 is not available after installation attempt(s).
    echo Please install Python 3.10 manually, then open a NEW terminal and re-run this script.
    pause
    exit /b 1
)

echo Using Python 3.10 for bootstrap_install.py
py -3.10 bootup\bootstrap_install.py %*

echo.
echo To start the application, run: .\run.ps1
echo LLM inference uses local LM Studio (see llm_lmstudio/user.toml.example).
echo.
pause
