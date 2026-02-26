param(
    [string]$PythonBin = "python",
    [switch]$BuildCAccelerated,
    [string]$BuildPythonPath = "",
    [switch]$NoZip
)

$ErrorActionPreference = "Stop"

function Log {
    param([string]$Message)
    $ts = Get-Date -Format "HH:mm:ss"
    Write-Host ""
    Write-Host "[$ts] $Message"
}

function Run {
    param(
        [Parameter(Mandatory = $true, Position = 0)]
        [string]$Exe,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$CmdArgs
    )
    Write-Host "+ $Exe $($CmdArgs -join ' ')"
    & $Exe @CmdArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Exe $($CmdArgs -join ' ')"
    }
}

function Require-Dir {
    param([string]$Path)
    if (-not (Test-Path -Path $Path -PathType Container)) {
        throw "Required directory does not exist: $Path"
    }
}

function Require-File {
    param([string]$Path)
    if (-not (Test-Path -Path $Path -PathType Leaf)) {
        throw "Required file does not exist: $Path"
    }
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir
$HelpersDir = Join-Path $RootDir "helpers"
$SpecFile = Join-Path $RootDir "SerialUI.spec"
$HelpersSetup = Join-Path $HelpersDir "setup.py"

Require-Dir $HelpersDir
Require-File $SpecFile
Require-File $HelpersSetup

Log "Checking Python environment isolation"
$usesSystemSite = & $PythonBin -c "import sys; p=[x for x in sys.path if 'site-packages' in x or 'dist-packages' in x]; print('1' if any(x.startswith('/usr/lib') or x.startswith('/usr/local/lib') for x in p) else '0')"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to check Python environment isolation using $PythonBin"
}
if ($usesSystemSite.Trim() -eq "1") {
    Write-Host "WARNING: Python environment includes system site-packages."
    Write-Host "         This can make PyInstaller bundles very large by pulling unrelated packages."
    Write-Host "         Recommended: build in a clean venv with include-system-site-packages = false."
}

Log "Installing/upgrading build tools"
Run $PythonBin "-m" "pip" "install" "--upgrade" "pip" "build" "pyinstaller" "pybind11" "setuptools" "wheel"

Log "Preparing helpers package"
Push-Location $HelpersDir
try {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "build", "dist", "*.egg-info", ".eggs"

    if ($BuildCAccelerated) {
        Log "Building C-accelerated parsers"
        $oldWarnings = $env:PYTHONWARNINGS
        $env:PYTHONWARNINGS = if ([string]::IsNullOrWhiteSpace($oldWarnings)) { "ignore::FutureWarning" } else { $oldWarnings }
        try {
            Run $PythonBin "setup.py" "build_ext" "--inplace" "-v"
        }
        finally {
            if ($null -eq $oldWarnings) {
                Remove-Item Env:PYTHONWARNINGS -ErrorAction SilentlyContinue
            } else {
                $env:PYTHONWARNINGS = $oldWarnings
            }
        }
    }
    else {
        Log "Skipping in-place C-accelerated parser build (BuildCAccelerated=$($BuildCAccelerated.IsPresent))"
    }

    Log "Building wheel and source distribution"
    $oldWarnings = $env:PYTHONWARNINGS
    $env:PYTHONWARNINGS = if ([string]::IsNullOrWhiteSpace($oldWarnings)) { "ignore::FutureWarning" } else { $oldWarnings }
    try {
        Run $PythonBin "-m" "build" "--no-isolation"
    }
    finally {
        if ($null -eq $oldWarnings) {
            Remove-Item Env:PYTHONWARNINGS -ErrorAction SilentlyContinue
        } else {
            $env:PYTHONWARNINGS = $oldWarnings
        }
    }

    Get-ChildItem -Path "dist" | Format-Table -AutoSize
}
finally {
    Pop-Location
}

Log "Building standalone executable with PyInstaller"
Push-Location $RootDir
try {
    $oldNoUserSite = $env:PYTHONNOUSERSITE
    $oldPythonPath = $env:PYTHONPATH
    $env:PYTHONNOUSERSITE = "1"

    if ([string]::IsNullOrWhiteSpace($BuildPythonPath)) {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    }
    else {
        Log "Using custom PYTHONPATH for PyInstaller build"
        $env:PYTHONPATH = $BuildPythonPath
    }

    try {
        Run $PythonBin "-m" "PyInstaller" "--clean" "--noconfirm" "SerialUI.spec"
    }
    finally {
        if ($null -eq $oldNoUserSite) {
            Remove-Item Env:PYTHONNOUSERSITE -ErrorAction SilentlyContinue
        } else {
            $env:PYTHONNOUSERSITE = $oldNoUserSite
        }

        if ($null -eq $oldPythonPath) {
            Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        } else {
            $env:PYTHONPATH = $oldPythonPath
        }
    }

    Get-ChildItem -Path "dist" | Format-Table -AutoSize
}
finally {
    Pop-Location
}

if (-not $NoZip) {
    $bundleDir = Join-Path $RootDir "dist\SerialUI"
    Require-Dir $bundleDir
    $zipPath = Join-Path $RootDir "dist\SerialUI.zip"
    if (Test-Path -Path $zipPath -PathType Leaf) {
        Remove-Item -Force $zipPath
    }
    Log "Creating executable zip archive"
    Compress-Archive -Path $bundleDir -DestinationPath $zipPath -Force
    Write-Host "Executable zip: $zipPath"
}

Log "Done"
Write-Host "Wheel artifacts: $HelpersDir\dist"
Write-Host "Standalone app:  $RootDir\dist\SerialUI"
