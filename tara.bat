@echo off
rem Tutti taraması (yerel). Görev Zamanlayıcı günde 2 kez çalıştırır.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
"C:\Users\yunus\AppData\Local\Programs\Python\Python311\python.exe" tutti_takip.py >> takip.log 2>&1
