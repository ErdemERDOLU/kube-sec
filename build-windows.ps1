#!/usr/bin/env pwsh
# Builds a single-file Windows exe using PyInstaller
# Run this on Windows with an activated Python venv that has the project's requirements installed
# Usage (Windows PowerShell): .\build-windows.ps1
# Usage (Linux/WSL with PowerShell Core): pwsh ./build-windows.ps1

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Ensure running in repo root
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# Ensure $IsWindows exists in both Windows PowerShell and PowerShell Core
if (-not (Get-Variable -Name IsWindows -Scope Script -ErrorAction SilentlyContinue)) {
    try {
        # Prefer RuntimeInformation when available
        $IsWindows = [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([System.Runtime.InteropServices.OSPlatform]::Windows)
    } catch {
        # Fallback to environment variable which exists on Windows
        $IsWindows = ($env:OS -eq 'Windows_NT')
    }
}

# Detect python executable (try python, python3, py)
$pythonCandidates = @('python','python3','py')
$PythonCmd = $null
foreach ($p in $pythonCandidates) {
    if (Get-Command $p -ErrorAction SilentlyContinue) {
        $PythonCmd = $p
        break
    }
}
if (-not $PythonCmd) {
    Write-Error "Python 3 is not found in PATH. Please install Python 3 and ensure 'python' or 'python3' is available in PATH."
    Write-Host "On Ubuntu/WLS you can run: sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
    exit 1
}

Write-Host "Using Python executable: $PythonCmd"

# Create venv and install deps (optional)
if (-not (Test-Path .venv)) {
    & $PythonCmd -m venv .venv
}

# Activate venv using the appropriate script for PowerShell
if ($IsWindows) {
    $activate = Join-Path -Path ".venv" -ChildPath "Scripts\Activate.ps1"
} else {
    $activate = Join-Path -Path ".venv" -ChildPath "bin/Activate.ps1"
}

if (Test-Path $activate) {
    . $activate
} else {
    Write-Host "Warning: Activation script not found: $activate - continuing without venv activation" -ForegroundColor Yellow
}

Write-Host "Installing Python dependencies..."
& $PythonCmd -m pip install --upgrade pip
& $PythonCmd -m pip install -r requirements.txt
& $PythonCmd -m pip install pyinstaller

# Cleanup previous builds
if (Test-Path dist) { Remove-Item -Recurse -Force dist }
if (Test-Path build) { Remove-Item -Recurse -Force build }
if (Test-Path kube-sec.spec) { Remove-Item -Force kube-sec.spec }

Write-Host "Running PyInstaller..."
# Use platform-appropriate separator for add-data (Windows uses ';', Linux/WSL uses ':')
$sep = if ($IsWindows) { ';' } else { ':' }
$addDataList = @(
    "src/web/templates${sep}templates",
    "src/web/static${sep}static",
    "public${sep}public"
)

# Build argument array for PyInstaller
$pyArgs = @('--onefile','--noconfirm','--name','kube-sec')
foreach ($d in $addDataList) { $pyArgs += "--add-data=$d" }
$pyArgs += 'src/main.py'

# Run PyInstaller through the detected Python interpreter to avoid relying on a PATH entry
& $PythonCmd -m PyInstaller @pyArgs

if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "Build complete. Output executable: dist\kube-sec.exe" -ForegroundColor Green
