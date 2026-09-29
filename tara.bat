@echo off
rem Tutti taraması (yerel). Görev Zamanlayıcı açılışta, uyanınca, kilit açılınca ve 2 saatte bir çalıştırır (son taramadan 60 dk geçmediyse atlar).
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
"C:\Users\yunus\AppData\Local\Programs\Python\Python311\python.exe" tutti_takip.py --otomatik >> takip.log 2>&1
