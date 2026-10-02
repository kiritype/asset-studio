@echo off
rem Starts Asset Studio. Put machine-specific settings (e.g. STUDIO_PYTHON) in launch.local.bat.
if exist "%~dp0launch.local.bat" call "%~dp0launch.local.bat"
if not defined STUDIO_PYTHON set "STUDIO_PYTHON=pythonw"
start "" "%STUDIO_PYTHON%" "%~dp0launch.py"
