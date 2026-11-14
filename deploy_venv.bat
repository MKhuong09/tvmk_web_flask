@echo off
SET VENV_NAME=venv

echo ===================================================
echo [1/3] Checking for Python installation...
echo ===================================================
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not added to your system PATH.
    echo Please install Python and try again.
    pause
    exit /b
)

echo ===================================================
echo [2/3] Creating virtual environment: %VENV_NAME%...
echo ===================================================
if exist %VENV_NAME% (
    rmdir /s /q %VENV_NAME% 2>nul
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to remove existing virtual environment. Please check permissions.
        pause
        exit /b
    )

    python -m venv %VENV_NAME%
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b
    )
    echo [SUCCESS] Virtual environment created.
)
echo ===================================================
echo [3/3] Installing requirements from requirements.txt...
echo ===================================================
if not exist requirements.txt (
    echo [ERROR] requirements.txt not found in this directory!
    echo Please place this .bat file in the same folder as requirements.txt.
    pause
    exit /b
)

call %VENV_NAME%\Scripts\python.exe -m pip install --upgrade pip
call %VENV_NAME%\Scripts\pip.exe install -r requirements.txt

if %errorlevel% eq 0 (
    echo ===================================================
    echo [SUCCESS] All dependencies installed successfully!
    echo To activate your environment in CMD, run: %VENV_NAME%\Scripts\activate.bat
    echo ===================================================
) else (
    echo [ERROR] Some installations failed. Check the error messages above.
)

pause