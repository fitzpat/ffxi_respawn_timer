@echo off
rem Rebuilds dist\FFXIRespawnTimer.exe. Requires: py -m pip install pyinstaller
py -m PyInstaller --onefile --noconsole --name FFXIRespawnTimer ^
    --add-data "%~dp0mob_tags.json;." ^
    --distpath "%~dp0dist" --workpath "%~dp0build" --specpath "%~dp0" ^
    "%~dp0ffxi_mob_timer.py"
if errorlevel 1 exit /b %errorlevel%
rem Seed the editable file alongside the exe; preserve existing manual edits.
if not exist "%~dp0dist\mob_tags.json" copy "%~dp0mob_tags.json" "%~dp0dist\mob_tags.json" >nul
