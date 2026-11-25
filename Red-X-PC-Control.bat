@echo off
REM Red-X PC Control - ekbar double-click korlei hobe.
REM Python/Tailscale na thakle nije install kore nebe, tarpor agent chalabe.
cd /d "%~dp0"

REM --- Python khujo, na pele install koro ---
set "PY=python"
python --version >nul 2>&1
if errorlevel 1 (
  echo Python pawa jay ni - install korchi, ektu somoy lagbe...
  winget install Python.Python.3.12 --accept-source-agreements --accept-package-agreements
  for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\python.exe" set "PY=%%D\python.exe"
)
%PY% --version >nul 2>&1
if errorlevel 1 (
  echo.
  echo Python install hoy ni. https://www.python.org theke install kore abar chalao.
  echo Install-er somoy "Add python.exe to PATH"-e tick dite hobe.
  pause
  exit /b 1
)

REM --- Tailscale khujo, na pele install koro ---
set "TS=tailscale"
where tailscale >nul 2>&1
if errorlevel 1 if exist "%ProgramFiles%\Tailscale\tailscale.exe" set "TS=%ProgramFiles%\Tailscale\tailscale.exe"
where tailscale >nul 2>&1
if errorlevel 1 (
  if not exist "%ProgramFiles%\Tailscale\tailscale.exe" (
    echo Tailscale pawa jay ni - install korchi...
    winget install Tailscale.Tailscale --accept-source-agreements --accept-package-agreements
    if exist "%ProgramFiles%\Tailscale\tailscale.exe" set "TS=%ProgramFiles%\Tailscale\tailscale.exe"
  )
)
"%TS%" status >nul 2>&1
if errorlevel 1 (
  echo Tailscale-e login korte hobe - browser khulbe, Google diye sign in koro...
  "%TS%" up
)

REM --- dorkari library na thakle install koro ---
%PY% -c "import pyautogui, PIL" >nul 2>&1
if errorlevel 1 (
  echo Dorkari jinish install korchi...
  %PY% -m pip install -r requirements.txt
)

echo.
echo Agent chalu hochhe - window bondho koro na.
%PY% agent.py
pause
