@echo off
rem Tao lich Windows chay run_sync.bat moi 30 phut
schtasks /Create /SC MINUTE /MO 30 /TN "SPX WooCommerce Sync" /TR "\"%~dp0run_sync.bat\"" /F
if errorlevel 1 (echo Loi: thu chuot phai file nay ^> Run as administrator) else (echo Da tao lich: chay moi 30 phut. Xem ket qua trong sync.log)
pause
