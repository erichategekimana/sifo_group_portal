# start_irembo_bot.ps1
# Custom startup script for Irembo Automation Bot on Windows

# --- Configuration ---
$ProjectRoot = "C:\Windows\System32\irembo_bot\"   # Fixed: Windows\System32 (not Windows32)
$VenvPath = "$ProjectRoot\.venv"                   # Virtual environment folder
$PythonExe = "$VenvPath\Scripts\python.exe"
$ActivateVenv = "$VenvPath\Scripts\Activate.ps1"
$ManagePy = "$ProjectRoot\irembo_automation\manage.py"
$LogFile = "$ProjectRoot\logs\server.log"
$Port = 8000

# --- Ensure log directory exists ---
$LogDir = Split-Path $LogFile -Parent
if (!(Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# Log startup timestamp
"$(Get-Date): Starting Irembo Bot service..." | Out-File $LogFile -Append

# --- Ensure manage.py exists ---
if (!(Test-Path $ManagePy)) {
    Write-Error "manage.py not found at $ManagePy. Please verify the project path."
    "$(Get-Date): ERROR - manage.py not found at $ManagePy" | Out-File $LogFile -Append
    exit 1
}

# --- Step 1: Start PostgreSQL (if used) ---
# If PostgreSQL is installed as a service, it should start automatically.
# If not, start it manually or update the service name below.
$PostgresServiceName = "postgresql-x64-15"
$pgService = Get-Service -Name $PostgresServiceName -ErrorAction SilentlyContinue
if ($pgService) {
    if ($pgService.Status -ne 'Running') {
        Write-Host "Starting PostgreSQL service '$PostgresServiceName'..."
        "$(Get-Date): Starting PostgreSQL service '$PostgresServiceName'..." | Out-File $LogFile -Append
        try {
            Start-Service -Name $PostgresServiceName -ErrorAction Stop
            Start-Sleep -Seconds 5
            "$(Get-Date): PostgreSQL started successfully." | Out-File $LogFile -Append
        } catch {
            Write-Warning "Could not start PostgreSQL service '$PostgresServiceName'. Please start it manually. $_"
            "$(Get-Date): PostgreSQL startup error: $_" | Out-File $LogFile -Append
        }
    } else {
        "$(Get-Date): PostgreSQL service already running." | Out-File $LogFile -Append
    }
} else {
    Write-Warning "PostgreSQL service '$PostgresServiceName' not found. Ensure your database is running."
    "$(Get-Date): PostgreSQL service not found. Ensure database is running." | Out-File $LogFile -Append
}

# --- Step 2: Activate virtual environment and start Django ---
if (Test-Path $PythonExe) {
    Write-Host "Starting Django development server on port $Port..."
    "$(Get-Date): Starting Django development server on port $Port..." | Out-File $LogFile -Append
    Set-Location $ProjectRoot
    
    # Add venv Scripts to PATH to ensure proper activation
    $env:PATH = "$VenvPath\Scripts;$env:PATH"
    
    # Run Django server with output to log file and console
    try {
        & $PythonExe $ManagePy runserver --noreload 0.0.0.0:$Port 2>&1 | Tee-Object -FilePath $LogFile -Append
    } catch {
        Write-Error "Failed to start Django server: $_"
        "$(Get-Date): ERROR - Failed to start Django server: $_" | Out-File $LogFile -Append
        exit 1
    }
} else {
    Write-Error "Python executable not found at $PythonExe. Please create or activate the virtual environment."
    "$(Get-Date): ERROR - Python executable not found at $PythonExe" | Out-File $LogFile -Append
    exit 1
}