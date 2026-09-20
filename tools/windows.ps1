[CmdletBinding()]
param(
    [ValidateSet('setup','doctor','init-data','chat','test')]
    [string]$Mode = 'doctor',
    [switch]$ProbeModel,
    [switch]$AdoptExisting
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root '.venv\Scripts\python.exe'
if ($Mode -eq 'setup') {
    & py -3.12 -m venv (Join-Path $Root '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required; virtual environment creation failed.' }
    & $Python -m pip install --disable-pip-version-check -r (Join-Path $Root 'requirements.lock.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    Write-Output 'Dependencies installed. Data, model weights and Windows account policy were not changed.'
    exit 0
}
if (!(Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Run tools/windows.ps1 -Mode setup first.' }
Push-Location (Join-Path $Root 'L2_CENTRAL')
try {
    if ($Mode -eq 'test') {
        & $Python -W error -m unittest discover -s (Join-Path $Root 'tests') -t $Root -v
    } else {
        $Arguments = @((Join-Path $Root 'xiyin.py'), $Mode)
        if ($ProbeModel -and $Mode -eq 'doctor') { $Arguments += '--probe-model' }
        if ($AdoptExisting -and $Mode -eq 'init-data') { $Arguments += '--adopt-existing' }
        & $Python @Arguments
    }
    $Result = $LASTEXITCODE
} finally { Pop-Location }
exit $Result
