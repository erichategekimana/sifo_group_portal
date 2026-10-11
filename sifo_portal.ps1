# sifo_portal.ps1
# Manual Interactive Launcher for SIFO Group Portal (Irembo Bot)
# Designed for Windows 11 multi-version environments (Stable / Beta / Testing)

param(
    [string]$ProjectRoot = $PSScriptRoot,
    [int]$Port = 8000
)

# If $PSScriptRoot is empty (e.g. running interactively), default to current directory
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Get-Location).Path
}

# Ensure Administrator Elevation
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Elevating to Administrator privileges..." -ForegroundColor Yellow
    $scriptPath = $MyInvocation.MyCommand.Path
    Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -ProjectRoot `"$ProjectRoot`" -Port $Port" -Verb RunAs
    exit
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "          SIFO GROUP PORTAL - MANUAL LAUNCHER             " -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Target Root: $ProjectRoot" -ForegroundColor Gray

# 1. Resolve Python (prioritize Global / System Python, then check virtual environments)
$ResolvedPython = $null

# Check Global System Python first
$sysPy = Get-Command "python.exe" -ErrorAction SilentlyContinue
if (-not $sysPy) {
    $sysPy = Get-Command "py.exe" -ErrorAction SilentlyContinue
}

if ($sysPy) {
    $ResolvedPython = $sysPy.Source
    Write-Host "[OK] Using Global System Python: $ResolvedPython" -ForegroundColor Green
} else {
    # Fallback to local virtual environments if global is not found in PATH
    $DesktopPath = [Environment]::GetFolderPath("Desktop")
    $VenvCandidates = @(
        (Join-Path $ProjectRoot "venv\Scripts\python.exe"),
        (Join-Path $ProjectRoot "venv\Scripts\python3.exe"),
        (Join-Path $ProjectRoot "..\venv\Scripts\python.exe"),
        (Join-Path $DesktopPath "SIFO GROUP PORTAL\venv\Scripts\python.exe")
    )
    foreach ($cand in $VenvCandidates) {
        if (Test-Path $cand) {
            $ResolvedPython = (Resolve-Path $cand).Path
            Write-Host "[OK] Using Local VirtualEnv Python: $ResolvedPython" -ForegroundColor Green
            break
        }
    }
}

if (-not $ResolvedPython) {
    Write-Host "[ERROR] Could not find Global Python or Virtual Environment." -ForegroundColor Red
    Write-Host "Please ensure Python 3.12+ is installed and added to PATH on this PC." -ForegroundColor Yellow
    Read-Host "Press Enter to exit..."
    exit 1
}

$VenvPython = $ResolvedPython

# 2. Locate manage.py and automation folder
$AutomationDir = Join-Path $ProjectRoot "irembo_automation"
$ManagePy = Join-Path $AutomationDir "manage.py"

if (-not (Test-Path $ManagePy)) {
    # Check if we are already inside irembo_automation directory
    if (Test-Path (Join-Path $ProjectRoot "manage.py")) {
        $AutomationDir = $ProjectRoot
        $ManagePy = Join-Path $AutomationDir "manage.py"
    } else {
        Write-Host "[ERROR] Could not find manage.py in $ProjectRoot or $AutomationDir" -ForegroundColor Red
        Read-Host "Press Enter to exit..."
        exit 1
    }
}

# 3. Check and start PostgreSQL service if needed
$PostgresServiceName = "postgresql-x64-15"
$pg = Get-Service -Name $PostgresServiceName -ErrorAction SilentlyContinue
if ($pg) {
    if ($pg.Status -ne 'Running') {
        Write-Host "[INFO] Starting PostgreSQL service ($PostgresServiceName)..." -ForegroundColor Yellow
        try {
            Start-Service -Name $PostgresServiceName -ErrorAction Stop
            Start-Sleep -Seconds 2
            Write-Host "[OK] PostgreSQL started." -ForegroundColor Green
        } catch {
            Write-Warning "Could not start PostgreSQL service automatically: $_"
        }
    } else {
        Write-Host "[OK] PostgreSQL service is running." -ForegroundColor Green
    }
}

# 4. Clean up any previous running Django instance to free Port 8000
$existing = Get-WmiObject Win32_Process -Filter "Name='python.exe' OR Name='python3.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match 'manage.py' }

if ($existing) {
    Write-Host "[INFO] Stopping previous running Django instance(s)..." -ForegroundColor Yellow
    foreach ($proc in $existing) {
        try {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Host " - Terminated process PID: $($proc.ProcessId)" -ForegroundColor Gray
        } catch {}
    }
    Start-Sleep -Seconds 1
}

# 5. Move into automation directory
Set-Location $AutomationDir

# 6. Optional: Open the browser after a brief delay in the background
$OpenBrowserJob = {
    param($url)
    Start-Sleep -Seconds 3
    Start-Process $url
}
Start-Job -ScriptBlock $OpenBrowserJob -ArgumentList "http://localhost:$Port/" | Out-Null

# 7. Apply any pending database migrations automatically
Write-Host "[INFO] Checking database migrations..." -ForegroundColor Yellow
& "$VenvPython" "$ManagePy" migrate --noinput
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Database migration check finished with code $LASTEXITCODE. Proceeding to server launch..."
} else {
    Write-Host "[OK] Database schema is up to date." -ForegroundColor Green
}

# 8. Start Django in the interactive foreground console
Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
Write-Host " Server starting at: http://localhost:$Port/              " -ForegroundColor Green
Write-Host " Press [CTRL + C] in this window anytime to STOP server. " -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Green
Write-Host ""

& "$VenvPython" "$ManagePy" runserver 0.0.0.0:$Port --noreload
