param(
    [string]$DatasetRoot = 'C:\Users\Veeresh\Desktop\MalwareBench',
    [string]$IndexPath = '',
    [string]$ModelCacheHub = '',
    [string]$OutputDirectory = '',
    [int]$PerLabel = 13,
    [int]$Seed = 20261004,
    [string]$MemoryLimit = '4g',
    [int]$CpuLimit = 2
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not $IndexPath) {
    $IndexPath = Join-Path $projectRoot 'data\s2_malwarebench_index.jsonl'
}
if (-not $ModelCacheHub) {
    $ModelCacheHub = Join-Path $env:USERPROFILE '.cache\huggingface\hub'
}
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $projectRoot 'data\s2_docker_pilot'
}

$npmGit = Join-Path $DatasetRoot 'npm\.git'
$pypiGit = Join-Path $DatasetRoot 'pypi\.git'
$modelSnapshot = Join-Path $ModelCacheHub 'models--microsoft--graphcodebert-base'

foreach ($requiredPath in @($IndexPath, $npmGit, $pypiGit, $modelSnapshot)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required S2 input is missing: $requiredPath"
    }
}
if ($PerLabel -lt 1 -or $CpuLimit -lt 1) {
    throw 'PerLabel and CpuLimit must be positive.'
}

$docker = Get-Command docker.exe -ErrorAction SilentlyContinue
if (-not $docker) {
    throw 'Docker Desktop is not installed or docker.exe is not on PATH.'
}
& $docker.Source version --format '{{.Server.Version}}' *> $null
if ($LASTEXITCODE -ne 0) {
    throw 'Docker Desktop is not running. Start it, wait for the Linux/WSL2 engine, then retry.'
}

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$image = 'packshield-s2-prep:local'
$dockerfile = Join-Path $PSScriptRoot 'Dockerfile'
$context = Join-Path $projectRoot 'packshield'

# This build has trusted S2 code and dependencies only. Dataset repositories,
# the metadata index, and the model cache are not exposed to the build process.
& $docker.Source build --network default --file $dockerfile --tag $image $context
if ($LASTEXITCODE -ne 0) {
    throw "S2 worker image build failed with exit code $LASTEXITCODE."
}

$summaryOutput = Join-Path $OutputDirectory 'pilot_summary.json'
$featuresOutput = Join-Path $OutputDirectory 'pilot_features.jsonl.gz'
$dockerArgs = @(
    'run', '--rm', '--init',
    '--network', 'none',
    '--read-only',
    '--user', '10001:10001',
    '--cap-drop', 'ALL',
    '--security-opt', 'no-new-privileges:true',
    '--pids-limit', '128',
    '--memory', $MemoryLimit,
    '--cpus', "$CpuLimit",
    '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=256m',
    '--env', 'HF_HOME=/hf-cache',
    '--env', 'HF_HUB_CACHE=/hf-cache/hub',
    '--env', 'HF_HUB_OFFLINE=1',
    '--env', 'TRANSFORMERS_OFFLINE=1',
    '--env', 'HF_HUB_DISABLE_TELEMETRY=1',
    '--env', 'DO_NOT_TRACK=1',
    '--env', 'PYTHONDONTWRITEBYTECODE=1',
    '--mount', "type=bind,source=$IndexPath,target=/input/index.jsonl,readonly",
    '--mount', "type=bind,source=$npmGit,target=/inputs/npm/.git,readonly",
    '--mount', "type=bind,source=$pypiGit,target=/inputs/pypi/.git,readonly",
    '--mount', "type=bind,source=$ModelCacheHub,target=/hf-cache/hub,readonly",
    '--mount', "type=bind,source=$OutputDirectory,target=/out",
    $image,
    '--index', '/input/index.jsonl',
    '--npm-root', '/inputs/npm',
    '--pypi-root', '/inputs/pypi',
    '--output', '/out/pilot_summary.json',
    '--features-output', '/out/pilot_features.jsonl.gz',
    '--per-label', "$PerLabel",
    '--seed', "$Seed"
)

& $docker.Source @dockerArgs
if ($LASTEXITCODE -ne 0) {
    throw "S2 isolated pilot failed with exit code $LASTEXITCODE. See the Docker output above."
}
Write-Output "Pilot summary: $summaryOutput"
Write-Output "Feature output: $featuresOutput"
