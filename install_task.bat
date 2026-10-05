@echo off
rem Tao lich Windows chay run_sync.bat moi ngay luc GIO_CHAY.
rem Neu may tat/ngu dung gio do thi se chay bu ngay khi may bat lai.
rem Chay file nay tu thu muc code that (vd C:\spx\...), KHONG chay tu ben trong file ZIP.
set GIO_CHAY=17:00
set "BAT=%~dp0run_sync.bat"

if not exist "%BAT%" (echo Khong tim thay "%BAT%". Hay giai nen ZIP truoc roi chay lai file nay trong thu muc code. & pause & exit /b 1)
echo Lich se chay: %BAT%

powershell -NoProfile -ExecutionPolicy Bypass -Command "$a = New-ScheduledTaskAction -Execute $env:ComSpec -Argument ('/c \"' + $env:BAT + '\"'); $t = New-ScheduledTaskTrigger -Daily -At $env:GIO_CHAY; $s = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 1); Register-ScheduledTask -TaskName 'SPX WooCommerce Sync' -Action $a -Trigger $t -Settings $s -Force | Out-Null"
if errorlevel 1 (echo Loi: thu chuot phai file nay ^> Run as administrator) else (echo Da tao lich: chay moi ngay luc %GIO_CHAY%. Xem ket qua trong sync.log)
pause
