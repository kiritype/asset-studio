@echo off
rem Restarts Asset Studio. Asks first when images are generating or queued, or a LoRA is training.
if exist "%~dp0launch.local.bat" call "%~dp0launch.local.bat"
if not defined STUDIO_PYTHON set "STUDIO_PYTHON=pythonw"
start "" "%STUDIO_PYTHON%" "%~dp0launch.py" restart
