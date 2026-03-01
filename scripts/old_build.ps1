param(
    [string]$PythonBin = "python",
    [string]$LegacyTag = "1.4.2"
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

function Remove-IfExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )
    if (Test-Path -Path $Path) {
        try {
            Remove-Item -Recurse -Force -ErrorAction Stop $Path
        }
        catch {
            throw "Failed to remove '$Path'. Close SerialUI/Explorer windows that may lock dist files, then retry. Error: $($_.Exception.Message)"
        }
    }
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir
$HelpersDir = Join-Path $RootDir "helpers"

Push-Location $RootDir
try {
    # Validate that the requested tag/commit exists.
    & git rev-parse --verify "$LegacyTag`^{commit}" *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Legacy tag/commit not found: $LegacyTag"
    }

    Write-Host "+ git restore --source $LegacyTag -- SerialUI.spec helpers/setup.py"
    & git restore --source $LegacyTag -- "SerialUI.spec" "helpers/setup.py"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to restore legacy build files from tag/commit: $LegacyTag"
    }
}
finally {
    Pop-Location
}

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
    Write-Host "+ cleaning root build outputs"
    Remove-IfExists (Join-Path $RootDir "build")
    Remove-IfExists (Join-Path $RootDir "dist")

    Run $PythonBin "-m" "PyInstaller" "--clean" "--noconfirm" "SerialUI.spec"
}
finally {
    Pop-Location
}
