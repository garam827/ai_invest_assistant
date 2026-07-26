@echo off
setlocal

cd /d "%~dp0"

echo === Checking for Python ===
where py >nul 2>nul
if errorlevel 1 goto no_launcher

py -3.11 -V >nul 2>nul
if errorlevel 1 (
    echo Python 3.11 not found via the py launcher. Attempting install via winget...
    call :install_python
    if errorlevel 1 exit /b 1
)
set PY_CMD=py -3.11
goto have_python

:no_launcher
where python >nul 2>nul
if errorlevel 1 (
    echo Python not found. Attempting install via winget...
    call :install_python
    if errorlevel 1 exit /b 1
)
set PY_CMD=python

:have_python
echo Using: %PY_CMD%

if not exist venv (
    echo.
    echo === Creating virtual environment (venv\) ===
    %PY_CMD% -m venv venv
    if errorlevel 1 (
        echo Failed to create the virtual environment.
        exit /b 1
    )
) else (
    echo.
    echo === venv\ already exists, reusing it ===
)

call venv\Scripts\activate.bat

echo.
echo === Upgrading pip ===
python -m pip install --upgrade pip

echo.
echo === Installing requirements.txt + requirements-dev.txt (Jupyter/ML extras) ===
pip install -r requirements-dev.txt
if errorlevel 1 (
    echo Package installation failed.
    exit /b 1
)

echo.
echo === Registering Jupyter kernel ===
python -m ipykernel install --user --name ai_invest_assistant --display-name "AI Invest Assistant (venv)"

echo.
echo === Setup complete ===
echo Activate the venv in a new shell with:   venv\Scripts\activate.bat
echo Run the app with:                        streamlit run app.py
echo Launch Jupyter with:                     jupyter lab

exit /b 0

:install_python
where winget >nul 2>nul
if errorlevel 1 (
    echo winget was not found. Install Python 3.11+ manually from https://www.python.org/downloads/
    echo and re-run this script.
    exit /b 1
)
winget install -e --id Python.Python.3.11 --source winget
if errorlevel 1 (
    echo winget install failed. Install Python 3.11+ manually from https://www.python.org/downloads/
    echo and re-run this script.
    exit /b 1
)
echo Python installed. If this script still can't find it, close and reopen this terminal
echo (PATH changes need a fresh shell) and re-run setup.bat.
exit /b 0
