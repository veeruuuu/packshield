param([string]$NpmRoot=$env:S2_NPM_ROOT,[string]$PypiRoot=$env:S2_PYPI_ROOT)
$ErrorActionPreference='Stop'
$ProjectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..\..')).Path
if(-not $NpmRoot){$NpmRoot=Join-Path (Split-Path $ProjectRoot -Parent) 'npm'}
if(-not $PypiRoot){$PypiRoot=Join-Path (Split-Path $ProjectRoot -Parent) 'pypi'}
if(-not(Test-Path -LiteralPath (Join-Path $PypiRoot '.git'))){throw "PyPI checkout not found: $PypiRoot"}
$Python=Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if(-not(Test-Path -LiteralPath $Python)){throw "Project venv missing: $Python"}
$InputIndex=Join-Path $PSScriptRoot 'input.jsonl'
$RunId=Get-Date -Format 'yyyyMMdd_HHmmss'
$OutputDir=Join-Path $PSScriptRoot (Join-Path 'runs' $RunId)
New-Item -ItemType Directory -Path $OutputDir -Force|Out-Null
$RunLog=Join-Path $OutputDir 'runner.log'
"PyPI batch 01 recovery started: $(Get-Date -Format o)"|Tee-Object -FilePath $RunLog
"Input: $InputIndex"|Tee-Object -FilePath $RunLog -Append
"Output: $OutputDir"|Tee-Object -FilePath $RunLog -Append
$DeferredGroupIds=@('tai-alphi_0.1.1_py3-none-any-whl', 'databricks-pypi1_0.2_py2-py3-none-any-whl', 'forecast-solar-plants-calgary_0.1.0_py3-none-any-whl', 'http3_client_1.0.0.1_zip', 'tdwtauthauthentication_1.0.8_zip', 'kac-tools_0.4.0_py3-none-any-whl', 'genesisbot_0.0.5_tar-gz', 'master-auth_0.0.1_py3-none-any-whl', 'selfsuperaded_7.36_tar-gz', 'scrapeasy-jkhjasdsad_0.12_tar-gz', 'libpywreproof_9.96_zip', 'selfcvstrpong_6.28_zip')
"Completed IDs excluded; deferred groups: $($DeferredGroupIds.Count)"|Tee-Object -FilePath $RunLog -Append
$PyArgs=@('-u','-m','packshield.tools.run_s2_extraction_parallel','--index',$InputIndex,'--npm-root',$NpmRoot,'--pypi-root',$PypiRoot,'--output-dir',$OutputDir,'--project-root',$ProjectRoot,'--workers','3','--batch-size','4','--poll-seconds','10','--file-timeout-seconds','20','--worker-startup-timeout','180')
foreach($GroupId in $DeferredGroupIds){$PyArgs+=@('--defer-group-id',$GroupId)}
& $Python @PyArgs 2>&1|Tee-Object -FilePath $RunLog -Append
$ExitCode=$LASTEXITCODE
"Recovery finished: $(Get-Date -Format o); exit=$ExitCode"|Tee-Object -FilePath $RunLog -Append
exit $ExitCode
