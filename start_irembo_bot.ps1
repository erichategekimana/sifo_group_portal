# start_irembo_bot.ps1
# Service-friendly startup script for Irembo Automation Bot (Windows)

param(
    [string]$ProjectRoot = "C:\Program Files\irembo_bot",
    [int]$Port = 8000
)

# Paths
$VenvPath = Join-Path $ProjectRoot "venv"
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"
$ManagePy = Join-Path $ProjectRoot "irembo_automation\manage.py"
$LogFile = Join-Path $ProjectRoot "logs\server.log"
$ErrFile = Join-Path $ProjectRoot "logs\server_error.log"

# Ensure log directory exists
$LogDir = Split-Path $LogFile -Parent
if (!(Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

function Log($msg) { "$(Get-Date -Format o): $msg" | Out-File $LogFile -Append }
function LogError($msg) { "$(Get-Date -Format o): $msg" | Out-File $ErrFile -Append }

Log "Starting Irembo Bot service script. ProjectRoot=$ProjectRoot"

# Validate manage.py
if (!(Test-Path $ManagePy)) {
    Write-Error "manage.py not found at $ManagePy. Verify ProjectRoot or file placement."
    Log "ERROR - manage.py not found at $ManagePy"
    exit 1
}

# Validate virtualenv python
if (!(Test-Path $PythonExe)) {
    # Try alternate common names
    $alt = Join-Path $VenvPath "Scripts\python3.exe"
    if (Test-Path $alt) { $PythonExe = $alt }
}
if (!(Test-Path $PythonExe)) {
    Write-Error "Python executable not found at expected venv locations: $PythonExe"
    Log "ERROR - Python executable not found under $VenvPath"
    exit 1
}

# Detect if Django (manage.py) is already running
$pythonProcesses = Get-WmiObject Win32_Process -Filter "Name='python.exe' OR Name='python3.exe'" -ErrorAction SilentlyContinue
if ($pythonProcesses) {
    $running = $pythonProcesses | Where-Object { $_.CommandLine -and $_.CommandLine -match 'manage.py' }
    if ($running) {
        $pids = ($running | ForEach-Object { $_.ProcessId }) -join ', '
        Write-Host "Django already running (manage.py) pid(s): $pids"
        Log "Django already running: PIDs=$pids - exiting start script."
        exit 0
    }
}

# (Optional) Start PostgreSQL service if present
$PostgresServiceName = "postgresql-x64-15"
$pg = Get-Service -Name $PostgresServiceName -ErrorAction SilentlyContinue
if ($pg) {
    if ($pg.Status -ne 'Running') {
        Log "Starting PostgreSQL service $PostgresServiceName"
        try { Start-Service -Name $PostgresServiceName -ErrorAction Stop; Start-Sleep -Seconds 3; Log "PostgreSQL started" } catch { Log "WARNING - PostgreSQL could not be started: $_" }
    } else { Log "PostgreSQL already running" }
} else { Log "PostgreSQL service $PostgresServiceName not present; skip" }

# Start Django using venv python via Start-Process so NSSM can supervise this script if invoked
Write-Host "Starting Django on 0.0.0.0:$Port using $PythonExe"
Log "Starting Django on 0.0.0.0:$Port using $PythonExe"

$args = "`"$ManagePy`" runserver --noreload 0.0.0.0:$Port"
try {
    $proc = Start-Process -FilePath $PythonExe -ArgumentList $args -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput $LogFile -RedirectStandardError $ErrFile -PassThru
    Log "Django process started, PID=$($proc.Id)"
    # Wait a short while and check if process is still running
    Start-Sleep -Seconds 2
    if ($proc.HasExited) {
        Log "ERROR - Django process exited quickly with code $($proc.ExitCode)"
        Write-Error "Django process failed to start. See $LogFile"
        exit 1
    }
    # For service usage we do not wait on the process; NSSM will keep the session
} catch {
    Log "ERROR - Failed to start Django: $_"
    Write-Error "Failed to start Django: $_"
    exit 1
}

Log "start_irembo_bot.ps1 finished (Django launched)."