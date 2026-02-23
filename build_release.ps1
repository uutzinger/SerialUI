param(
    [string]$PythonBin = "python"
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
        [string]$Exe,
        [string[]]$Args
    )
    Write-Host "+ $Exe $($Args -join ' ')"
    & $Exe @Args
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE: $Exe $($Args -join ' ')"
    }
}

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SpecFile = Join-Path $RootDir "SerialUI.spec"

if (-not (Test-Path -Path $SpecFile -PathType Leaf)) {
    throw "Missing spec file: $SpecFile"
}

Log "Installing/upgrading PyInstaller tooling"
Run $PythonBin @("-m", "pip", "install", "--upgrade", "pip", "pyinstaller")

Log "Building standalone executable with PyInstaller"
Push-Location $RootDir
try {
    $oldNoUserSite = $env:PYTHONNOUSERSITE
    $env:PYTHONNOUSERSITE = "1"
    try {
        Run $PythonBin @("-m", "PyInstaller", "--clean", "--noconfirm", "SerialUI.spec")
    }
    finally {
        if ($null -eq $oldNoUserSite) {
            Remove-Item Env:PYTHONNOUSERSITE -ErrorAction SilentlyContinue
        } else {
            $env:PYTHONNOUSERSITE = $oldNoUserSite
        }
    }

    Get-ChildItem -Path "dist" | Format-Table -AutoSize
}
finally {
    Pop-Location
}

Log "Done"
Write-Host "Standalone app:  $RootDir\dist\SerialUI"
