@echo off
rem Rapor hazırla: eklenti kayıtlarını aktar, raporu üret (Tutti verisi bu bilgisayardaki veri.db).
rem Tutti taraması "TuttiTara" zamanlanmış göreviyle bu bilgisayarda çalışır (tara.bat).
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
"C:\Users\yunus\AppData\Local\Programs\Python\Python311\python.exe" ice_aktar.py
"C:\Users\yunus\AppData\Local\Programs\Python\Python311\python.exe" rapor.py
pause
