param(
    [string]$PythonBin = "python"
)

$ErrorActionPreference = "Stop"

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

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir
$LegacyDir = Join-Path $RootDir "tmp\serialui-1.4.2"
$HelpersDir = Join-Path $RootDir "helpers"

if (-not (Test-Path -Path $LegacyDir -PathType Container)) {
    throw "Missing legacy folder: $LegacyDir"
}
if (-not (Test-Path -Path (Join-Path $LegacyDir "SerialUI.spec") -PathType Leaf)) {
    throw "Missing legacy spec file in: $LegacyDir"
}
if (-not (Test-Path -Path (Join-Path $LegacyDir "setup.py") -PathType Leaf)) {
    throw "Missing legacy setup.py file in: $LegacyDir"
}

Copy-Item -Force (Join-Path $LegacyDir "SerialUI.spec") (Join-Path $RootDir "SerialUI.spec")
Copy-Item -Force (Join-Path $LegacyDir "setup.py") (Join-Path $HelpersDir "setup.py")

Push-Location $HelpersDir
try {
    Write-Host "+ cleaning helpers build outputs"
    if (Test-Path -Path "build" -PathType Container) { Remove-Item -Recurse -Force "build" }
    if (Test-Path -Path ".eggs" -PathType Container) { Remove-Item -Recurse -Force ".eggs" }
    Get-ChildItem -Path . -Filter "*.egg-info" -Directory -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force

    # clean can fail when no previous build metadata exists; continue in that case
    Write-Host "+ $PythonBin setup.py clean --all"
    & $PythonBin "setup.py" "clean" "--all"
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "setup.py clean returned $LASTEXITCODE; continuing."
    }

    Run $PythonBin "setup.py" "build_ext" "--inplace" "-v"
    Run $PythonBin "-m" "pip" "install" "-e" "."
}
finally {
    Pop-Location
}

Push-Location $RootDir
try {
    Run $PythonBin "-m" "PyInstaller" "--clean" "--noconfirm" "SerialUI.spec"
}
finally {
    Pop-Location
}
