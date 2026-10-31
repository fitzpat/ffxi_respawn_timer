@echo off
rem Double-click launcher: runs the timer with no console window.
rem Uses the py launcher; falls back to a stock pythonw on PATH.
where pyw >nul 2>&1
if %errorlevel%==0 (
    start "" pyw "%~dp0ffxi_mob_timer.py"
) else (
    start "" pythonw "%~dp0ffxi_mob_timer.py"
)
