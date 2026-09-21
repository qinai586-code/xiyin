[CmdletBinding()]
param(
    [ValidateSet('setup','doctor','init-data','chat','serve','verify','test')]
    [string]$Mode = 'doctor',
    [switch]$ProbeModel,
    [switch]$AdoptExisting
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root '.venv\Scripts\python.exe'
if ($Mode -eq 'setup') {
    # Prefer the newest interpreter this repository's CI actually tests. A bare
    # `python` was how an acceptance run ended up on 3.11 and lost a whole pass
    # to one mysterious failure, so the version used is named explicitly here.
    $Created = $false
    foreach ($Version in @('3.13', '3.12')) {
        & py "-$Version" -m venv (Join-Path $Root '.venv') 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Output "Created the virtual environment with Python $Version."
            $Created = $true
            break
        }
    }
    if (-not $Created) { throw 'Python 3.12 or 3.13 is required; virtual environment creation failed.' }
    & $Python -m pip install --disable-pip-version-check -r (Join-Path $Root 'requirements.lock.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    Write-Output 'Dependencies installed. Data, model weights and Windows account policy were not changed.'
    exit 0
}
if (!(Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Run tools/windows.ps1 -Mode setup first.' }
Push-Location $Root
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
