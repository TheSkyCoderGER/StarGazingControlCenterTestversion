@echo off
cd /d "%~dp0"
if not exist "star_gazing_control_center.py" (
    echo Die Programmdatei fehlt in diesem Ordner.
    echo Bitte die ZIP-Datei zuerst entpacken ^(Rechtsklick - Alle extrahieren^) und start.bat im entpackten Ordner starten.
    pause & exit /b 1
)
set PY=python
where python >nul 2>nul || (where py >nul 2>nul && set PY=py)
%PY% --version >nul 2>nul || (echo Python wurde nicht gefunden. Bitte von python.org installieren ^(Haken "Add Python to PATH"^). & pause & exit /b 1)
if not exist ".deps_v4" (
    echo Installiere Pakete ...
    %PY% -m pip install -r requirements.txt || (echo Paketinstallation fehlgeschlagen - siehe Meldungen oben. & pause & exit /b 1)
    echo ok > .deps_v4
    echo Optional: Windows-Standortdienst ...
    %PY% -m pip install winrt-runtime winrt-Windows.Devices.Geolocation winrt-Windows.Foundation >nul 2>nul || %PY% -m pip install winsdk >nul 2>nul
)
if exist "startfehler.txt" del "startfehler.txt"
if /i "%1"=="diagnose" (
    %PY% star_gazing_control_center.py
    echo.
    echo Programm beendet. Fehlermeldungen stehen oben.
    pause
    exit /b
)
where pythonw >nul 2>nul && (start "" pythonw star_gazing_control_center.py) || (start "" %PY% star_gazing_control_center.py)
