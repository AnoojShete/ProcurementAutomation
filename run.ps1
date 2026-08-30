# Windows entry point. Docker Desktop's Linux-container backend on
# Windows requires WSL2, so the actual bring-up logic stays in run.sh
# (bash) — this just re-execs it inside WSL rather than reimplementing
# run.sh's health-check polling loops in PowerShell. scripts/ensure-docker.sh
# (called from install.sh, which run.sh calls first) detects it's running
# under WSL and starts Docker Desktop on the Windows host automatically.
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)
$ErrorActionPreference = "Stop"

$wslCmd = Get-Command wsl.exe -ErrorAction SilentlyContinue
if (-not $wslCmd) {
    Write-Host "WSL2 is required to run this project on Windows." -ForegroundColor Red
    Write-Host ""
    Write-Host "Install it with:   wsl --install"
    Write-Host "Then install Docker Desktop and enable WSL integration for your distro:"
    Write-Host "  Docker Desktop > Settings > Resources > WSL Integration"
    Write-Host "  https://www.docker.com/products/docker-desktop/"
    exit 1
}

Write-Host "Running run.sh inside WSL..." -ForegroundColor Cyan
$joined = ($Args -join ' ')
# wsl.exe launched from a Windows directory starts in the WSL-translated
# equivalent of that directory (modern wsl.exe versions), so ./run.sh
# resolves to this same project folder.
wsl.exe bash -lc "./run.sh $joined"
exit $LASTEXITCODE
