@echo off
rem Zürih Haushaltsbedarf raporu: eklenti kayıtlarını aktar, kaybolan ilan analizini üret (haushalt_rapor.xlsx).
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
"C:\Users\yunus\AppData\Local\Programs\Python\Python311\python.exe" ice_aktar.py
"C:\Users\yunus\AppData\Local\Programs\Python\Python311\python.exe" haushalt.py
pause
