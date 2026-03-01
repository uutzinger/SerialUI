param(
    [string]$PythonBin = "python",
    [switch]$BuildExecutable,
    [switch]$BuildCAccelerated,
    [Alias("update-ankerl", "udate-ankerl")]
    [switch]$UpdateAnkerl,
    [string]$BuildPythonPath = "",
    [string]$CommitMsg = "",
    [switch]$Commit,
    [switch]$Tag,
    [switch]$Push,
    [switch]$Release,
    [switch]$UploadAssets,
    [switch]$Clean,
    [Alias("h")]
    [switch]$Help
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

function Show-Usage {
    $scriptName = if ($PSCommandPath) { Split-Path -Leaf $PSCommandPath } else { "release.ps1" }
    Write-Host @"
Usage:
  .\scripts\$scriptName [options]

Options:
  -PythonBin <python>          Python interpreter (default: python)
  -BuildExecutable             Build standalone app via scripts/build_executable.ps1
                               Also creates dist\SerialUI-<version>-windows-<arch>.zip
  -BuildCAccelerated           Build C-accelerated helpers, build wheel,
                               and install line_parsers into active env
  -UpdateAnkerl                Update ankerl headers used by helpers\line_parsers
                               (unordered_dense.h and companion headers such as stl.h)
                               from helpers\line_parsers\ankerl submodule
                               This does not trigger any build
  -BuildPythonPath <path>      Custom PYTHONPATH for executable build
  -CommitMsg <message>         Commit message (default: "release: <version>")
  -Commit                      Stage and commit changes
  -Tag                         Create git tag "<version>"
  -Push                        Push commit and current release tag only
  -Release                     Create GitHub release for tag "<version>" and upload compressed assets from dist\ (*.zip, *.tar.gz)
                               If tag is missing, implies build executable + tag + push
                               If tag exists, runs release-only mode unless overridden
  -UploadAssets                Upload additional dist\*.zip and dist\*.tar.gz to existing release
  -Clean                       Remove build artifacts before build
  -Help, -h                    Show this help

Notes:
  - Version/tag is read from config.py (VERSION).
  - Run from repository root.
  - GitHub actions require: gh auth login

Examples:
  .\scripts\release.ps1 -BuildExecutable
  .\scripts\release.ps1 -BuildExecutable -BuildCAccelerated
  .\scripts\release.ps1 -Commit -Tag -Push
  .\scripts\release.ps1 -Release
  .\scripts\release.ps1 -UploadAssets
"@
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

function Get-DistArchives {
    param([string]$RootDir)

    $distDir = Join-Path $RootDir "dist"
    Require-Dir $distDir
    $assets = Get-ChildItem -Path $distDir -File | Where-Object {
        $name = $_.Name.ToLowerInvariant()
        $name.EndsWith('.zip') -or $name.EndsWith('.tar.gz')
    } | Sort-Object Name

    return @($assets)
}

function Create-GitHubRelease {
    param(
        [string]$Version,
        [string]$RootDir
    )

    $tag = $Version
    Require-Command gh

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

    $assets = Get-DistArchives -RootDir $RootDir
    if (-not $assets -or $assets.Count -eq 0) {
        throw "No release assets found in dist\ (expected *.zip or *.tar.gz)."
    }

    $args = @("release", "create", $tag) + ($assets | ForEach-Object { $_.FullName }) + @("--title", $tag, "--generate-notes")
    Run gh @args

    Write-Host "Created GitHub release $tag"
    foreach ($asset in $assets) {
        Write-Host "  asset: $($asset.FullName)"
    }
}

function Upload-ReleaseAssets {
    param(
        [string]$Version,
        [string]$RootDir
    )

    $tag = $Version
    Require-Command gh

    & gh auth status *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "gh is not authenticated. Run: gh auth login"
    }

    if (-not (Test-GitHubReleaseExists -Tag $tag)) {
        throw "GitHub release $tag does not exist."
    }

    $assets = Get-DistArchives -RootDir $RootDir
    if ($assets.Count -eq 0) {
        throw "No uploadable assets found in dist/ (expected *.zip or *.tar.gz)."
    }

    $args = @("release", "upload", $tag) + ($assets | ForEach-Object { $_.FullName })
    Run gh @args
    Write-Host "Uploaded $($assets.Count) asset(s) to release $tag"
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir
$UpdateAnkerlScriptPs1 = Join-Path $ScriptDir "update_ankerl.ps1"
$UpdateAnkerlScript = Join-Path $ScriptDir "update_ankerl.sh"
Set-Location $RootDir

if ($Help) {
    Show-Usage
    exit 0
}

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

if ($UpdateAnkerl) {
    if (Test-Path -Path $UpdateAnkerlScriptPs1 -PathType Leaf) {
        & $UpdateAnkerlScriptPs1
    }
    elseif (Test-Path -Path $UpdateAnkerlScript -PathType Leaf) {
        if (-not (Get-Command bash -ErrorAction SilentlyContinue)) {
            throw "Neither scripts/update_ankerl.ps1 nor bash is available. Install Git Bash or add scripts/update_ankerl.ps1."
        }
        Run "bash" $UpdateAnkerlScript
    }
    else {
        throw "No update script found (expected scripts/update_ankerl.ps1 or scripts/update_ankerl.sh)."
    }
}

$updateOnlyMode = (
    $UpdateAnkerl -and
    (-not $BuildExecutable) -and
    (-not $BuildCAccelerated.IsPresent) -and
    (-not $Release) -and
    (-not $UploadAssets) -and
    (-not $Commit) -and
    (-not $Tag) -and
    (-not $Push)
)

if ($updateOnlyMode) {
    Write-Host "Update-only mode: skipped helper/executable build steps."
    Write-Host "Release script completed."
    exit 0
}

$doBuildHelpers = $true
if ($BuildExecutable) {
    $doBuildHelpers = $false
}
elseif ($UploadAssets -and (-not $BuildCAccelerated.IsPresent) -and (-not $Release)) {
    $doBuildHelpers = $false
}
elseif ($Release -and $releaseOnlyMode -and (-not $BuildCAccelerated.IsPresent)) {
    $doBuildHelpers = $false
}

if ($BuildExecutable) {
    $buildScript = Join-Path $ScriptDir "build_executable.ps1"
    Require-File $buildScript
    & $buildScript `
        -PythonBin $PythonBin `
        -BuildCAccelerated:$($BuildCAccelerated.IsPresent) `
        -BuildPythonPath $BuildPythonPath
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

        if ($BuildCAccelerated) {
            Run $PythonBin "-m" "pip" "install" "--force-reinstall" "--no-deps" $wheel.FullName
            Write-Host "Installed wheel into active environment: $($wheel.FullName)"
        }
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
    $currentBranch = (& git "branch" "--show-current").Trim()
    $pushRemote = (& git "config" "--get" "branch.$currentBranch.remote" 2>$null)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($pushRemote)) {
        $pushRemote = "origin"
    }
    else {
        $pushRemote = $pushRemote.Trim()
    }

    Run git "push"
    Run git "push" $pushRemote "refs/tags/$version"
}

if ($Release) {
    Create-GitHubRelease -Version $version -RootDir $RootDir
}

if ($UploadAssets) {
    Upload-ReleaseAssets -Version $version -RootDir $RootDir
}

Write-Host "Release script completed."
