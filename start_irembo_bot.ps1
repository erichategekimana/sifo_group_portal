# start_irembo_bot.ps1
# Service startup script for Irembo Automation Bot (Windows 11)

param(
    [string]$ProjectRoot = "C:\Program Files\irembo_bot",
    [int]$Port = 8000
)

# 1. Ensure Administrator Elevation
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Re-launching script with Administrator privileges..." -ForegroundColor Yellow
    $scriptPath = $MyInvocation.MyCommand.Path
    Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`"" -Verb RunAs
    exit
}

# 2. Paths Configuration
$VenvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"
if (!(Test-Path $VenvPython)) {
    $alt = Join-Path $ProjectRoot "venv\Scripts\python3.exe"
    if (Test-Path $alt) { $VenvPython = $alt }
}

$AutomationDir = Join-Path $ProjectRoot "irembo_automation"
$ManagePy = Join-Path $AutomationDir "manage.py"
$LogDir = Join-Path $ProjectRoot "logs"
$LogFile = Join-Path $LogDir "server.log"
$ErrFile = Join-Path $LogDir "server_error.log"

if (!(Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

# 3. Start PostgreSQL Service if present
$PostgresServiceName = "postgresql-x64-15"
$pg = Get-Service -Name $PostgresServiceName -ErrorAction SilentlyContinue
if ($pg -and $pg.Status -ne 'Running') {
    Write-Host "Starting PostgreSQL service..." -ForegroundColor Cyan
    try {
        Start-Service -Name $PostgresServiceName -ErrorAction Stop
        Start-Sleep -Seconds 2
    } catch {
        Write-Warning "Could not start PostgreSQL service automatically: $_"
    }
}

# 4. Check if Django is already running
$existing = Get-WmiObject Win32_Process -Filter "Name='python.exe' OR Name='python3.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match 'manage.py' }
if ($existing) {
    $pids = ($existing | ForEach-Object { $_.ProcessId }) -join ', '
    Write-Host "Django already running (PID: $pids). Exiting start script." -ForegroundColor Green
    exit 0
}

# 5. Move into irembo_automation directory so session_state.json and local files load natively
Set-Location $AutomationDir

# 6. Launch Django server with --noreload in the foreground interactive desktop session
Write-Host "Starting Django server on port $Port inside $AutomationDir..." -ForegroundColor Green
$args = "`"$ManagePy`" runserver --noreload 0.0.0.0:$Port"

try {
    $proc = Start-Process -FilePath $VenvPython -ArgumentList $args -WorkingDirectory $AutomationDir -WindowStyle Normal -RedirectStandardOutput $LogFile -RedirectStandardError $ErrFile -PassThru
    Start-Sleep -Seconds 2
    if ($proc.HasExited) {
        Write-Error "Django server failed to start. Check logs at: $LogFile"
        exit 1
    }
    Write-Host "Django server started successfully (PID: $($proc.Id))." -ForegroundColor Green
} catch {
    Write-Error "Failed to start Django process: $_"
    exit 1
}