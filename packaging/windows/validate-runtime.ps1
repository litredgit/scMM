param(
    [Parameter(Mandatory=$true)][string]$Runtime,
    [Parameter(Mandatory=$true)][string]$Report
)
$ErrorActionPreference = 'Stop'
$runtimeRoot = (Resolve-Path -LiteralPath $Runtime).Path
$reportPath = [System.IO.Path]::GetFullPath($Report)
if (Test-Path -LiteralPath $reportPath) { throw 'Report already exists; choose a new path.' }
$pythonPath = Join-Path $runtimeRoot 'python\python.exe'
$scriptPath = Join-Path $runtimeRoot 'validate_windows_runtime.py'
$manifest = Get-Content -LiteralPath (Join-Path $runtimeRoot 'poc.json') -Raw | ConvertFrom-Json
if ((Get-FileHash -LiteralPath $scriptPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.validation_script_sha256) {
    throw 'Validation script checksum mismatch.'
}
$savedEnvironment = @{}
$statePath = $runtimeRoot + '-validation-state'
try {
    foreach ($entry in Get-ChildItem Env:) {
        if ($entry.Name -match '^(PYTHON|UV_)' -or $entry.Name -in @('TEMP','TMP','MPLCONFIGDIR','NUMBA_CACHE_DIR')) {
            $savedEnvironment[$entry.Name] = $entry.Value
            Remove-Item ('Env:' + $entry.Name)
        }
    }
    foreach ($item in @{TEMP='tmp'; TMP='tmp'; MPLCONFIGDIR='matplotlib'; NUMBA_CACHE_DIR='numba'}.GetEnumerator()) {
        $path = Join-Path $statePath $item.Value
        New-Item -ItemType Directory -Path $path -Force | Out-Null
        Set-Item ('Env:' + $item.Key) $path
    }
    $env:PYTHONNOUSERSITE = '1'
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $pythonPath -I $scriptPath --report $reportPath
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previous }
    if ($code -ne 0) { throw ('Scientific validation failed; inspect ' + $reportPath) }
} finally {
    foreach ($name in @('PYTHONNOUSERSITE','TEMP','TMP','MPLCONFIGDIR','NUMBA_CACHE_DIR')) {
        Remove-Item ('Env:' + $name) -ErrorAction SilentlyContinue
    }
    foreach ($entry in $savedEnvironment.GetEnumerator()) { Set-Item ('Env:' + $entry.Key) $entry.Value }
}
