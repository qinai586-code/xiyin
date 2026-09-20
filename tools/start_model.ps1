param(
    [Parameter(Mandatory = $true)]
    [string]$ServerPath,
    [string]$PythonPath = "python",
    [string]$ModelPath,
    [ValidateRange(0, 999)]
    [int]$GpuLayers = 0
)

# 0 keeps inference on CPU. Positive values use the backend in the supplied
# server binary; GPU memory size alone does not establish a CUDA/NVIDIA backend.
# This script neither downloads a server nor downloads a model.
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$checker = Join-Path $PSScriptRoot "download_model.py"
if (-not (Test-Path -LiteralPath $ServerPath -PathType Leaf)) {
    throw "ServerPath must point to an existing llama-server.exe."
}
$resolvedServer = (Resolve-Path -LiteralPath $ServerPath).ProviderPath
if ([IO.Path]::GetExtension($resolvedServer) -ne ".exe") {
    throw "ServerPath must be a Windows executable."
}

$checkArguments = @($checker, "--check")
if ($ModelPath) { $checkArguments += @("--destination", $ModelPath) }
$checkOutput = & $PythonPath @checkArguments
if ($LASTEXITCODE -ne 0) {
    throw "Model verification failed. No server was started."
}
$verified = ($checkOutput -join [Environment]::NewLine) | ConvertFrom-Json
if ($verified.status -ne "verified") { throw "Unexpected model verification result." }
$settings = $verified.server
$serverArguments = @(
    "--model", [string]$verified.model_path,
    "--host", [string]$settings.host,
    "--port", [string]$settings.port,
    "--alias", [string]$settings.alias,
    "--ctx-size", [string]$settings.ctx_size,
    "--parallel", [string]$settings.parallel,
    "--n-gpu-layers", [string]$GpuLayers,
    "--jinja",
    "--chat-template-kwargs", '{"enable_thinking":false}',
    "--no-mmproj-auto"
)

function ConvertTo-WindowsArgument([string]$Value) {
    # Preserve JSON double quotes and paths with spaces on Windows PowerShell
    # 5.1 as well as PowerShell 7; no shell evaluates the resulting arguments.
    $escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
    return '"' + $escaped + '"'
}

$start = New-Object System.Diagnostics.ProcessStartInfo
$start.FileName = $resolvedServer
$start.WorkingDirectory = $projectRoot
$start.UseShellExecute = $false
$start.Arguments = ($serverArguments | ForEach-Object { ConvertTo-WindowsArgument $_ }) -join " "
Write-Host "Starting the verified local model at http://127.0.0.1:8080 (GPU layers: $GpuLayers)."
$process = New-Object System.Diagnostics.Process
$process.StartInfo = $start
try {
    if (-not $process.Start()) { throw "llama-server did not start." }
    $process.WaitForExit()
    $serverExitCode = $process.ExitCode
} finally {
    $process.Dispose()
}
exit $serverExitCode
