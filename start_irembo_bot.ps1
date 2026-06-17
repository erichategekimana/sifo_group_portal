# start_irembo_bot.ps1
# Custom startup script for Irembo Automation Bot on Windows

# --- Configuration ---
$ProjectRoot = "C:\irembo_automation"          # Change to your project path
$VenvPath = "$ProjectRoot\venv"                # Virtual environment folder
$PythonExe = "$VenvPath\Scripts\python.exe"
$ManagePy = "$ProjectRoot\manage.py"
$LogFile = "$ProjectRoot\logs\server.log"
$Port = 8000

# --- Ensure log directory exists ---
$LogDir = Split-Path $LogFile -Parent
if (!(Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# --- Ensure manage.py exists ---
if (!(Test-Path $ManagePy)) {
    Write-Error "manage.py not found at $ManagePy. Please verify the project path."
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
        try {
            Start-Service -Name $PostgresServiceName -ErrorAction Stop
            Start-Sleep -Seconds 5
        } catch {
            Write-Warning "Could not start PostgreSQL service '$PostgresServiceName'. Please start it manually. $_"
        }
    }
} else {
    Write-Warning "PostgreSQL service '$PostgresServiceName' not found. Ensure your database is running."
}

# --- Step 2: Activate virtual environment and start Django ---
if (Test-Path $PythonExe) {
    Write-Host "Starting Django development server on port $Port..."
    Write-Host "Log output will be written to $LogFile"
    Set-Location $ProjectRoot
    & $PythonExe $ManagePy runserver --noreload 0.0.0.0:$Port >> $LogFile 2>&1
} else {
    Write-Error "Python executable not found at $PythonExe. Please create or activate the virtual environment."
    exit 1
}