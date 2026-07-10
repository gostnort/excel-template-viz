@echo off
echo ========================================
echo Excel Template Viz - Gradio Version
echo Installation Script
echo ========================================
echo.
set LLM_MODE=cpu
set SKIP_OCR=0
:parse_llm_args
if "%~1"=="" goto :llm_args_done
if /I "%~1"=="--llm" (
    set LLM_MODE=%~2
    shift
    shift
    goto :parse_llm_args
)
if /I "%~1"=="--skip-ocr" (
    set SKIP_OCR=1
    shift
    goto :parse_llm_args
)
shift
goto :parse_llm_args
:llm_args_done
echo LLM wheel mode: %LLM_MODE% (cpu default; use --llm cuda for NVIDIA)
if "%SKIP_OCR%"=="1" (
    echo OCR install: SKIPPED (--skip-ocr)
) else (
    echo OCR install: enabled by default ^(pass --skip-ocr to skip^)
)

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
echo Detecting CPU SIMD features for llama-cpp-python wheel...
set PYTHONPATH=%CD%
for /f "delims=" %%V in ('python -c "from llm_gemma4.backends.llamacpp.cpu_features import recommended_llama_cpp_version; print(recommended_llama_cpp_version())"') do set LLAMA_CPP_VERSION=%%V
echo Recommended llama-cpp-python version: %LLAMA_CPP_VERSION%
if /I "%LLM_MODE%"=="cuda" (
    echo Installing llama-cpp-python %LLAMA_CPP_VERSION% (CUDA cu124 wheel)...
    set LLAMA_CPP_CUDA_INDEX=https://abetlen.github.io/llama-cpp-python/whl/cu124
    pip install llama-cpp-python==%LLAMA_CPP_VERSION% --extra-index-url %LLAMA_CPP_CUDA_INDEX%
    if errorlevel 1 (
        echo ERROR: Failed to install llama-cpp-python CUDA wheel
        pause
        exit /b 1
    )
    echo Installing NVIDIA CUDA 12 runtime DLLs (for ggml-cuda on Windows)...
    pip install nvidia-cuda-runtime-cu12 nvidia-cublas-cu12
    if errorlevel 1 (
        echo WARNING: nvidia CUDA pip packages failed; you may need CUDA DLLs on PATH
    )
) else (
    echo Installing llama-cpp-python %LLAMA_CPP_VERSION% (CPU wheel)...
    set LLAMA_CPP_CPU_INDEX=https://abetlen.github.io/llama-cpp-python/whl/cpu
    pip install llama-cpp-python==%LLAMA_CPP_VERSION% --extra-index-url %LLAMA_CPP_CPU_INDEX%
    if errorlevel 1 (
        echo WARNING: CPU wheel index install failed; retrying from PyPI...
        pip install llama-cpp-python==%LLAMA_CPP_VERSION%
        if errorlevel 1 (
            echo ERROR: Failed to install llama-cpp-python
            echo See QUICKSTART.md for CPU / wheel compatibility.
            pause
            exit /b 1
        )
    )
)

echo.
echo Installing remaining dependencies...
echo.
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
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

echo.
echo ========================================
echo Installation completed successfully!
echo ========================================
echo.
echo To start the application, run: run.bat
echo.
pause
