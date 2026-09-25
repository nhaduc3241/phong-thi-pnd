@echo off
rem Chay 1 luot dong bo SPX -> WooCommerce, ghi log vao sync.log
cd /d "%~dp0"
echo ===== %date% %time% =====>> sync.log
set PYTHONIOENCODING=utf-8
python sync_woo.py >> sync.log 2>&1
