@echo off
echo ========================================
echo Excel Template Viz - NiceGUI
echo Installation Script (uv)
echo ========================================
echo.

where uv >nul 2>&1
if errorlevel 1 (
    echo ERROR: uv is not on PATH.
    echo Install uv, then re-run this script:
    echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    echo   https://docs.astral.sh/uv/getting-started/installation/
    pause
    exit /b 1
)

echo Using uv:
uv --version
echo.
echo Options: --skip-ocr  --gpu  --cpu  --force-profile  --python 3.10  --frozen
echo Gemma 4: litert-lm via --extra llm; model downloads on first use.
echo.

set "BOOTSTRAP_ARGS=%*"
echo %* | findstr /I /C:"--python" >nul
if errorlevel 1 (
    py -3.10 --version >nul 2>&1
    if not errorlevel 1 (
        set "BOOTSTRAP_ARGS=--python 3.10 %*"
        echo Defaulting bootstrap to --python 3.10
    )
)

py -3.10 scripts\bootstrap_install.py %BOOTSTRAP_ARGS% 2>nul
if errorlevel 1 (
    python scripts\bootstrap_install.py %BOOTSTRAP_ARGS%
    if errorlevel 1 (
        echo ERROR: bootstrap_install.py failed
        pause
        exit /b 1
    )
)

echo.
echo To start the application, run: run.bat
echo Gemma 4 model (~3.66GB) downloads on first LLM/OCR use, or prefetch:
echo   uv run python -c "from llm_gemma4.hf_download import download_litert; print(download_litert())"
echo.
pause
