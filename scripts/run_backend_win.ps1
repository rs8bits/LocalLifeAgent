$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location -LiteralPath $root

$python = Join-Path $root ".venv\Scripts\python.exe"
$log = Join-Path $root "backend.log"
$errLog = Join-Path $root "backend.err.log"

Start-Process `
    -FilePath $python `
    -ArgumentList @("-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000") `
    -WorkingDirectory $root `
    -RedirectStandardOutput $log `
    -RedirectStandardError $errLog `
    -WindowStyle Hidden `
    -Wait
