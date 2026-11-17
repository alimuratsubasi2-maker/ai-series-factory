@echo off
rem AI Dizi Fabrikasi: senaryo -> 5 bolum -> Telegram bildirimi -> yeni senaryo (surekli). Yayin onayla yapilir.
cd /d "%~dp0"
if exist diziler\DURDUR del diziler\DURDUR
set PYTHONIOENCODING=utf-8
set PYTHONWARNINGS=ignore
python dizi.py fabrika >> diziler\fabrika_log.txt 2>&1
