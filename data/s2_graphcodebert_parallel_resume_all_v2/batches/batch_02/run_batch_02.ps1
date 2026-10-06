param(
    [string]$NpmRoot = $env:S2_NPM_ROOT,
    [string]$PypiRoot = $env:S2_PYPI_ROOT
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
if (-not $NpmRoot) { $NpmRoot = Join-Path (Split-Path $ProjectRoot -Parent) 'npm' }
if (-not $PypiRoot) { $PypiRoot = Join-Path (Split-Path $ProjectRoot -Parent) 'pypi' }
if (-not (Test-Path -LiteralPath (Join-Path $NpmRoot '.git'))) { throw "npm Git checkout not found: $NpmRoot" }
if (-not (Test-Path -LiteralPath (Join-Path $PypiRoot '.git'))) { throw "PyPI Git checkout not found: $PypiRoot" }
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) { throw "Project venv missing: $Python" }
$InputIndex = Join-Path $PSScriptRoot 'input.jsonl'
$RunId = Get-Date -Format 'yyyyMMdd_HHmmss'
$OutputDir = Join-Path $PSScriptRoot (Join-Path 'runs' $RunId)
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$RunLog = Join-Path $OutputDir 'runner.log'
"Batch 02 started: $(Get-Date -Format o)" | Tee-Object -FilePath $RunLog
"Input: $InputIndex" | Tee-Object -FilePath $RunLog -Append
"Output: $OutputDir" | Tee-Object -FilePath $RunLog -Append
"Shards: 3; parser workers: 1 per shard; archive batch size: 4" | Tee-Object -FilePath $RunLog -Append
& $Python -u -m packshield.tools.run_s2_extraction_parallel `
    --index $InputIndex `
    --npm-root $NpmRoot `
    --pypi-root $PypiRoot `
    --output-dir $OutputDir `
    --project-root $ProjectRoot `
    --workers 3 `
    --batch-size 4 `
    --poll-seconds 10 `
    --file-timeout-seconds 20 `
    --worker-startup-timeout 180 2>&1 | Tee-Object -FilePath $RunLog -Append
$ExitCode = $LASTEXITCODE
"Batch 02 finished: $(Get-Date -Format o); exit=$ExitCode" | Tee-Object -FilePath $RunLog -Append
exit $ExitCode
