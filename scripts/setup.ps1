param(
    [string]$VenvDir = "$HOME\Python\serialui"
)

$ErrorActionPreference = "Stop"

function Get-PythonCommand {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return @("py", "-3")
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @("python")
    }
    throw "Python was not found. Install Python 3 and ensure 'py' or 'python' is on PATH."
}

function Invoke-Python {
    param(
        [string[]]$PyCmd,
        [string[]]$Args
    )
    $exe = $PyCmd[0]
    $preArgs = @()
    if ($PyCmd.Length -gt 1) {
        $preArgs = $PyCmd[1..($PyCmd.Length - 1)]
    }
    & $exe @preArgs @Args
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE: $($PyCmd -join ' ') $($Args -join ' ')"
    }
}

$pythonCmd = Get-PythonCommand

$venvParent = Split-Path -Parent $VenvDir
if (-not (Test-Path -Path $venvParent -PathType Container)) {
    New-Item -ItemType Directory -Path $venvParent -Force | Out-Null
}

if (-not (Test-Path -Path $VenvDir -PathType Container)) {
    Invoke-Python -PyCmd $pythonCmd -Args @("-m", "venv", $VenvDir)
}

$activateScript = Join-Path $VenvDir "Scripts\Activate.ps1"
if (-not (Test-Path -Path $activateScript -PathType Leaf)) {
    throw "Activation script not found: $activateScript"
}

# Activate in this script scope for package install.
. $activateScript

Invoke-Python -PyCmd @("python") -Args @("-m", "pip", "install", "--upgrade", "pip")

$commonPackages = @(
    "pyqt6",
    "pyqtgraph",
    "markdown",
    "bleak",
    "numpy",
    "scipy",
    "numba",
    "fastplotlib",
    "PyOpenGL",
    "pybind11",
    "setuptools",
    "cobs",
    "tamp"
)

$osPackages = @("wmi")

$installArgs = @("-m", "pip", "install") + $commonPackages + $osPackages
Invoke-Python -PyCmd @("python") -Args $installArgs

Write-Host ""
Write-Host "Virtual environment ready: $VenvDir"
Write-Host "Python: $((Get-Command python).Source)"

# If dot-sourced, keep activation in current session.
if ($MyInvocation.InvocationName -eq ".") {
    Write-Host "Virtual environment activated in current PowerShell session."
    return
}

if ($env:VIRTUAL_ENV_DISABLE_PROMPT -and $env:VIRTUAL_ENV_DISABLE_PROMPT -ne "0") {
    Write-Host "Note: VIRTUAL_ENV_DISABLE_PROMPT is set; prompt prefix may be hidden."
}

Write-Host "Opening a new PowerShell session with the virtual environment activated..."
$escapedActivate = $activateScript.Replace("'", "''")
$escapedCwd = (Get-Location).Path.Replace("'", "''")
$command = ". '$escapedActivate'; Set-Location '$escapedCwd'"

if (Get-Command pwsh -ErrorAction SilentlyContinue) {
    & pwsh -NoExit -Command $command
}
else {
    & powershell -NoExit -Command $command
}
