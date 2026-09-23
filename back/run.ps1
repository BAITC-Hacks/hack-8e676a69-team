$ErrorActionPreference = 'Stop'
$backendRoot = $PSScriptRoot
$repositoryRoot = Split-Path -Parent $backendRoot
$pythonExecutable = Join-Path $backendRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw 'Create back/.venv and install back/requirements.txt first; see back/README.md.'
}
$launchArguments = @('-m', 'uvicorn', 'back.main:app', '--app-dir', $repositoryRoot, '--host', '127.0.0.1', '--port', '8000')
$environmentFile = Join-Path $backendRoot '.env'
if (Test-Path -LiteralPath $environmentFile) { $launchArguments += @('--env-file', $environmentFile) }
& $pythonExecutable @launchArguments @args
exit $LASTEXITCODE
