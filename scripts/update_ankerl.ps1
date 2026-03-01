param()

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

function FilesEqual {
    param(
        [Parameter(Mandatory = $true)][string]$Left,
        [Parameter(Mandatory = $true)][string]$Right
    )
    if (-not (Test-Path -Path $Left -PathType Leaf)) { return $false }
    if (-not (Test-Path -Path $Right -PathType Leaf)) { return $false }

    $leftHash = (Get-FileHash -Path $Left -Algorithm SHA256).Hash
    $rightHash = (Get-FileHash -Path $Right -Algorithm SHA256).Hash
    return ($leftHash -eq $rightHash)
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir
$SubmodulePath = "helpers/line_parsers/ankerl"
$SrcBaseRel = Join-Path $SubmodulePath "include/ankerl"
$DstBaseRel = "helpers/line_parsers"
$RequiredHeaders = @("unordered_dense.h")
$OptionalHeaders = @("stl.h")

Set-Location $RootDir

Write-Host "Syncing ankerl header..."
Write-Host "Updating ankerl submodule from upstream..."
Run "git" "-C" $RootDir "submodule" "sync" "--" $SubmodulePath

try {
    Run "git" "-C" $RootDir "submodule" "update" "--init" "--remote" "--depth" "1" "--" $SubmodulePath
}
catch {
    Write-Warning "Remote submodule refresh failed; using local submodule state if available."
    & git -C $RootDir submodule update --init --depth 1 -- $SubmodulePath
}

$updated = $false

foreach ($header in $RequiredHeaders) {
    $srcRel = Join-Path $SrcBaseRel $header
    $dstRel = Join-Path $DstBaseRel $header
    $src = Join-Path $RootDir $srcRel
    $dst = Join-Path $RootDir $dstRel

    if (-not (Test-Path -Path $src -PathType Leaf)) {
        throw "Source header missing after submodule update: $srcRel"
    }

    $dstDir = Split-Path -Parent $dst
    if (-not (Test-Path -Path $dstDir -PathType Container)) {
        New-Item -ItemType Directory -Path $dstDir -Force | Out-Null
    }

    if (FilesEqual -Left $src -Right $dst) {
        Write-Host "$header already up to date."
        continue
    }

    Copy-Item -Path $src -Destination $dst -Force
    Write-Host "Updated: $dstRel"
    $updated = $true
}

foreach ($header in $OptionalHeaders) {
    $srcRel = Join-Path $SrcBaseRel $header
    $dstRel = Join-Path $DstBaseRel $header
    $src = Join-Path $RootDir $srcRel
    $dst = Join-Path $RootDir $dstRel

    if (-not (Test-Path -Path $src -PathType Leaf)) {
        Write-Host "Optional header not present in current ankerl version: $srcRel"
        continue
    }

    $dstDir = Split-Path -Parent $dst
    if (-not (Test-Path -Path $dstDir -PathType Container)) {
        New-Item -ItemType Directory -Path $dstDir -Force | Out-Null
    }

    if (FilesEqual -Left $src -Right $dst) {
        Write-Host "$header already up to date."
        continue
    }

    Copy-Item -Path $src -Destination $dst -Force
    Write-Host "Updated: $dstRel"
    $updated = $true
}

if (-not $updated) {
    Write-Host "All synced ankerl headers already up to date."
}

