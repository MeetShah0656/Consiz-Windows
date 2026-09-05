# Launches Consiz with Administrator privileges from PowerShell
Set-Location $PSScriptRoot
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if ($isAdmin) {
    Write-Host "[OK] Running with Administrator privileges" -ForegroundColor Green
    python main.py
} else {
    Write-Host "[INFO] Requesting Administrator elevation..." -ForegroundColor Yellow
    Start-Process powershell -WorkingDirectory $PSScriptRoot -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", "python main.py" -Verb RunAs
}
