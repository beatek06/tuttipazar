@echo off
rem Rapor hazırla: GitHub'daki güncel Tutti verisini indir, eklenti kayıtlarını aktar, raporu üret.
rem (Tutti taraması artık GitHub Actions'ta çalışıyor, bu bilgisayarda değil.)
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
"C:\Users\yunus\AppData\Local\Programs\Python\Python311\python.exe" veri_indir.py
"C:\Users\yunus\AppData\Local\Programs\Python\Python311\python.exe" ice_aktar.py
"C:\Users\yunus\AppData\Local\Programs\Python\Python311\python.exe" rapor.py
pause
