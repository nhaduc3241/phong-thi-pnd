@echo off
chcp 65001 >nul
rem Kiem tra lich tu dong va ket qua lan chay gan nhat
cd /d "%~dp0"
echo ===== LICH TU DONG =====
powershell -NoProfile -Command "$t = Get-ScheduledTask -TaskName 'SPX WooCommerce Sync' -ErrorAction SilentlyContinue; if (-not $t) { Write-Host 'CHUA CO LICH. Bam dup install_task.bat de cai.'; exit } $i = $t | Get-ScheduledTaskInfo; $cmd = ($t.Actions | ForEach-Object { $_.Execute + ' ' + $_.Arguments }) -join '; '; Write-Host ('Trang thai     : ' + $t.State); Write-Host ('Lenh chay      : ' + $cmd); Write-Host ('Lan chay truoc : ' + $i.LastRunTime); Write-Host ('Ket qua        : ' + $i.LastTaskResult + $(if ($i.LastTaskResult -eq 0) { '  (OK)' } else { '  (LOI)' })); Write-Host ('Lan chay toi   : ' + $i.NextRunTime)"
echo.
echo ===== 15 DONG CUOI CUA sync.log =====
if exist sync.log (powershell -NoProfile -Command "Get-Content -Encoding UTF8 sync.log -Tail 15") else (echo Chua co sync.log - lich chua chay lan nao o thu muc nay)
echo.
pause
