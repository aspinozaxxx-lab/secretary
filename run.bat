@echo off
setlocal
cd /d "%~dp0"
py -3.11 main.py --config config.yaml
endlocal
