@echo off
rem Tao lich Windows chay run_sync.bat moi ngay luc GIO_CHAY.
rem Neu may tat/ngu dung gio do thi se chay bu ngay khi may bat lai.
set GIO_CHAY=17:00

powershell -NoProfile -ExecutionPolicy Bypass -Command "$a = New-ScheduledTaskAction -Execute '%~dp0run_sync.bat' -WorkingDirectory '%~dp0'; $t = New-ScheduledTaskTrigger -Daily -At '%GIO_CHAY%'; $s = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 1); Register-ScheduledTask -TaskName 'SPX WooCommerce Sync' -Action $a -Trigger $t -Settings $s -Force | Out-Null"
if errorlevel 1 (echo Loi: thu chuot phai file nay ^> Run as administrator) else (echo Da tao lich: chay moi ngay luc %GIO_CHAY%. Xem ket qua trong sync.log)
pause
