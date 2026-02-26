param(
    [string]$PythonBin = "python",
    [switch]$BuildExecutable,
    [bool]$BuildCAccelerated = $false,
    [string]$BuildPythonPath = "",
    [string]$CommitMsg = "",
    [switch]$Commit,
    [switch]$Tag,
    [switch]$Push,
    [switch]$Release,
    [switch]$UploadAssets,
    [switch]$Clean
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

function Require-File {
    param([string]$Path)
    if (-not (Test-Path -Path $Path -PathType Leaf)) {
        throw "Required file missing: $Path"
    }
}

function Require-Dir {
    param([string]$Path)
    if (-not (Test-Path -Path $Path -PathType Container)) {
        throw "Required directory missing: $Path"
    }
}

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name"
    }
}

function Get-ProjectVersion {
    param([string]$Python)

    $script = @"
import ast
from pathlib import Path

config_file = Path('config.py')
module = ast.parse(config_file.read_text(encoding='utf-8'), filename=str(config_file))
for node in module.body:
    value = None
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == 'VERSION':
                value = node.value
                break
    elif isinstance(node, ast.AnnAssign):
        if isinstance(node.target, ast.Name) and node.target.id == 'VERSION':
            value = node.value

    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        print(value.value)
        raise SystemExit(0)

raise SystemExit('VERSION was not found as a string literal in config.py')
"@

    $version = & $Python -c $script
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to read VERSION from config.py"
    }
    return $version.Trim()
}

function Validate-Version {
    param([string]$Version)
    if ($Version -notmatch '^[0-9]+(\.[0-9]+){2}([a-zA-Z0-9._-]*)?$') {
        throw "config.py VERSION must provide X.Y.Z (PEP 440-compatible suffixes allowed)."
    }
}

function Test-LocalTag {
    param([string]$Tag)
    & git rev-parse -q --verify "refs/tags/$Tag" *> $null
    return ($LASTEXITCODE -eq 0)
}

function Test-GitHubReleaseExists {
    param([string]$Tag)
    & gh release view $Tag *> $null
    return ($LASTEXITCODE -eq 0)
}

function Create-GitHubRelease {
    param(
        [string]$Version,
        [string]$RootDir
    )

    $tag = $Version
    Require-Command gh
    Require-Dir (Join-Path $RootDir "dist\SerialUI")

    & gh auth status *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "gh is not authenticated. Run: gh auth login"
    }

    if (-not (Test-LocalTag -Tag $tag)) {
        throw "Tag $tag does not exist locally."
    }

    if (Test-GitHubReleaseExists -Tag $tag) {
        throw "GitHub release $tag already exists."
    }

    $arch = if ($env:PROCESSOR_ARCHITECTURE) { $env:PROCESSOR_ARCHITECTURE.ToLower() } else { "unknown" }
    $exeArchive = Join-Path $RootDir "dist\SerialUI-$Version-windows-$arch.zip"
    $srcArchive = Join-Path $RootDir "dist\SerialUI-source-$Version.zip"

    if (Test-Path $exeArchive) { Remove-Item $exeArchive -Force }
    if (Test-Path $srcArchive) { Remove-Item $srcArchive -Force }

    Compress-Archive -Path (Join-Path $RootDir "dist\SerialUI") -DestinationPath $exeArchive -Force
    Run git "archive" "--format=zip" "--output" $srcArchive $tag

    Run gh "release" "create" $tag $exeArchive $srcArchive "--title" $tag "--generate-notes"

    Write-Host "Created GitHub release $tag"
    Write-Host "  asset: $exeArchive"
    Write-Host "  asset: $srcArchive"
}

function Upload-ReleaseAssets {
    param(
        [string]$Version,
        [string]$RootDir
    )

    $tag = $Version
    Require-Command gh
    $distDir = Join-Path $RootDir "dist"
    Require-Dir $distDir

    & gh auth status *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "gh is not authenticated. Run: gh auth login"
    }

    if (-not (Test-GitHubReleaseExists -Tag $tag)) {
        throw "GitHub release $tag does not exist."
    }

    $assets = Get-ChildItem -Path $distDir -File | Where-Object {
        $name = $_.Name.ToLowerInvariant()
        $name.EndsWith('.zip') -or $name.EndsWith('.tar.gz')
    }

    if (-not $assets) {
        throw "No uploadable assets found in dist/ (expected *.zip or *.tar.gz)."
    }

    $args = @("release", "upload", $tag) + ($assets | ForEach-Object { $_.FullName }) + @("--clobber")
    Run gh @args
    Write-Host "Uploaded $($assets.Count) asset(s) to release $tag"
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir
Set-Location $RootDir

Require-File (Join-Path $RootDir "config.py")

$version = Get-ProjectVersion -Python $PythonBin
if ([string]::IsNullOrWhiteSpace($version)) {
    throw "config.py did not provide VERSION"
}
Validate-Version -Version $version
Write-Host "Release version: $version"

$userSetBuildExecutable = $PSBoundParameters.ContainsKey("BuildExecutable")
$userSetTag = $PSBoundParameters.ContainsKey("Tag")
$userSetPush = $PSBoundParameters.ContainsKey("Push")
$releaseOnlyMode = $false

if ($Release) {
    if (Test-LocalTag -Tag $version) {
        if ((-not $userSetBuildExecutable) -and (-not $userSetTag) -and (-not $userSetPush)) {
            $releaseOnlyMode = $true
            $BuildExecutable = $false
            $Tag = $false
            $Push = $false
            Write-Host "Tag $version already exists; running release-only mode."
        }
    }
    else {
        if (-not $userSetBuildExecutable) { $BuildExecutable = $true }
        if (-not $userSetTag) { $Tag = $true }
        if (-not $userSetPush) { $Push = $true }
    }
}

if ($Clean) {
    $cleanPaths = @(
        (Join-Path $RootDir "build"),
        (Join-Path $RootDir "dist"),
        (Join-Path $RootDir "*.egg-info"),
        (Join-Path $RootDir "*.egg"),
        (Join-Path $RootDir ".pytest_cache"),
        (Join-Path $RootDir "helpers\build"),
        (Join-Path $RootDir "helpers\dist"),
        (Join-Path $RootDir "helpers\*.egg-info"),
        (Join-Path $RootDir "helpers\.eggs")
    )
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $cleanPaths
}

$doBuildHelpers = $true
if ($BuildExecutable) {
    $doBuildHelpers = $false
}
elseif ($UploadAssets -and (-not $BuildCAccelerated) -and (-not $Release)) {
    $doBuildHelpers = $false
}
elseif ($Release -and $releaseOnlyMode -and (-not $BuildCAccelerated)) {
    $doBuildHelpers = $false
}

if ($BuildExecutable) {
    $buildScript = Join-Path $ScriptDir "build_executable.ps1"
    Require-File $buildScript
    & $buildScript -PythonBin $PythonBin -BuildCAccelerated:$BuildCAccelerated -BuildPythonPath $BuildPythonPath
    if ($LASTEXITCODE -ne 0) {
        throw "build_executable.ps1 failed with exit code $LASTEXITCODE"
    }
}
elseif ($doBuildHelpers -or $BuildCAccelerated) {
    $helpersDir = Join-Path $RootDir "helpers"
    Require-File (Join-Path $helpersDir "setup.py")

    Push-Location $helpersDir
    try {
        if ($BuildCAccelerated) {
            Write-Host "Building C-accelerated parser extension in helpers/..."
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "build", "*.egg-info", ".eggs"

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

        & $PythonBin -m build --help *> $null
        if ($LASTEXITCODE -ne 0) {
            throw "python build package not found. Install with: $PythonBin -m pip install build"
        }

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

        $wheel = Get-ChildItem -Path "dist" -Filter "*.whl" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if (-not $wheel) {
            throw "Build completed but no wheel found in helpers/dist/."
        }
        Write-Host "Built wheel: helpers\dist\$($wheel.Name)"
    }
    finally {
        Pop-Location
    }
}

if ($Commit) {
    if ([string]::IsNullOrWhiteSpace($CommitMsg)) {
        $CommitMsg = "release: $version"
    }
    Run git "add" "-A"
    Run git "commit" "-m" $CommitMsg
}

if ($Tag) {
    Run git "tag" $version
}

if ($Push) {
    Run git "push"
    Run git "push" "--tags"
}

if ($Release) {
    Create-GitHubRelease -Version $version -RootDir $RootDir
}

if ($UploadAssets) {
    Upload-ReleaseAssets -Version $version -RootDir $RootDir
}

Write-Host "Release script completed."
