# Force Python unbuffered logging
$env:PYTHONUNBUFFERED = "1"
$env:PORT = "5001"

Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host "[LOG] 1. Ensuring WAHA Docker Container is Running..." -ForegroundColor Cyan
Write-Host "=====================================================" -ForegroundColor Cyan
docker start waha 2>$null
Write-Host "[LOG] Sent start signal to Docker container 'waha'."

Write-Host "[LOG] 2. Checking WAHA health on Port 3001..." -ForegroundColor Cyan
$attempts = 0
while ($true) {
    # Use native Windows curl.exe against 127.0.0.1
    $null = curl.exe -s http://127.0.0.1:3001/api/sessions
    if ($LASTEXITCODE -eq 0) {
        break
    }
    $attempts++
    Write-Host "[LOG] Waiting for WAHA container on port 3001... (Attempt: $attempts)"
    Start-Sleep -Seconds 2
    if ($attempts -ge 15) {
        Write-Host "[ERROR] WAHA on port 3001 is not responding." -ForegroundColor Red
        exit 1
    }
}

Write-Host "[LOG] WAHA Docker container is ONLINE on Port 3001!" -ForegroundColor Green

Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host "[LOG] 3. Starting Background Python Services..." -ForegroundColor Cyan
Write-Host "=====================================================" -ForegroundColor Cyan

Start-Process python -ArgumentList "-u mongo_db.py" -NoNewWindow
Start-Process python -ArgumentList "-u WAHA_INTERACT.py" -NoNewWindow
Start-process python -ArgumentList "-u WAHA_REMINDERV2.py" -NoNewWindow

Start-Sleep -Seconds 2

Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host "[LOG] 4. Starting Web Dashboard on Port $env:PORT..." -ForegroundColor Cyan
Write-Host "=====================================================" -ForegroundColor Cyan

python -u DASHBOARD.py