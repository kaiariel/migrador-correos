@echo off
chcp 65001 >nul
title Migrador de correo
cd /d "%~dp0"
python app.py %*
if errorlevel 1 pause
