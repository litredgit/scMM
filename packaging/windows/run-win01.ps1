param([string]$WorkRoot)
$ErrorActionPreference = 'Stop'
if (-not [Environment]::Is64BitProcess -or $env:PROCESSOR_ARCHITECTURE -ne 'AMD64') {
    throw 'Run in 64-bit Windows PowerShell on Windows x64.'
}
if (-not $WorkRoot) {
    $WorkRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) ('scMM\win01-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
}
$work = [System.IO.Path]::GetFullPath($WorkRoot)
if ($work.StartsWith('\\')) { throw 'Choose a local NTFS folder for WorkRoot.' }
$drive = [System.IO.DriveInfo]::new([System.IO.Path]::GetPathRoot($work))
if ($drive.DriveFormat -ne 'NTFS') { throw 'WorkRoot must be on local NTFS.' }
if (Test-Path -LiteralPath $work) { throw 'WorkRoot already exists; choose a new folder.' }
$kit = $PSScriptRoot
$manifest = Get-Content -LiteralPath (Join-Path $kit 'kit.json') -Raw | ConvertFrom-Json
Write-Host 'Verifying the complete offline kit...'
foreach ($item in $manifest.files) {
    if ($item.path -match '(^[\\/]|(^|[\\/])\.\.([\\/]|$)|:)') { throw 'Invalid kit path.' }
    $path = Join-Path $kit $item.path
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item.sha256) {
        throw ('Kit checksum mismatch: ' + $item.path)
    }
}
New-Item -ItemType Directory -Path $work | Out-Null
$log = Join-Path $work 'diagnostics.txt'
$summary = @{schema=1; status='running'; kind='WIN-01 native compute and relocation; user acceptance separate'; kit_id=$manifest.kit_id}
$summary.offline_requirement = 'Disconnect Windows networking before running; Python hook does not block native DLL traffic.'
$summary.chinese_user_name = [bool]([Environment]::UserName -match '[^\x00-\x7F]')
$summary.host_tools_on_path = @{}
foreach ($name in @('python','dotnet','node','uv')) {
    $summary.host_tools_on_path[$name] = [bool](Get-Command $name -ErrorAction SilentlyContinue)
}
$saved = @{}
function Invoke-Native([string]$Executable, [string[]]$Arguments) {
    $previous = $ErrorActionPreference
    try {
        # Windows PowerShell 5 maps native stderr to error records, including ordinary logs.
        $ErrorActionPreference = 'Continue'
        & $Executable @Arguments >> $log 2>&1
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previous }
    if ($code -ne 0) { throw ('Native command failed (' + $code + '); see diagnostics.txt') }
}
try {
    foreach ($entry in Get-ChildItem Env:) {
        if ($entry.Name -match '^(PYTHON|UV_)' -or $entry.Name -in @('PATH','TEMP','TMP','MPLCONFIGDIR','NUMBA_CACHE_DIR')) {
            $saved[$entry.Name] = $entry.Value
            if ($entry.Name -ne 'PATH') { Remove-Item ('Env:' + $entry.Name) }
        }
    }
    $env:PATH = (Join-Path $kit 'tools') + ';' + $saved['PATH']
    $temp = Join-Path $work 'tmp'
    New-Item -ItemType Directory -Path $temp | Out-Null
    $env:TEMP = $temp
    $env:TMP = $temp
    $env:PYTHONNOUSERSITE = '1'
    $seed = Join-Path $work 'bootstrap'
    New-Item -ItemType Directory -Path $seed | Out-Null
    Write-Host 'Extracting the verified private Python (no system installation)...'
    Invoke-Native (Join-Path $env:SystemRoot 'System32\tar.exe') @('-xzf',(Join-Path $kit 'inputs\python.tar.gz'),'-C',$seed)
    $python = Join-Path $seed 'python\python.exe'
    $packagingWheel = Join-Path $kit $manifest.packaging_wheel
    $builder = Join-Path $kit 'scripts\build_windows.py'
    $runtime = Join-Path $work 'runtime'
    # packaging is pure Python and is imported directly from its verified wheel.
    $bootstrap = "import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); p=sys.argv.pop(1); sys.argv[0]=p; runpy.run_path(p,run_name='__main__')"
    Write-Host 'Assembling the offline scientific environment...'
    Invoke-Native $python @('-I','-c',$bootstrap,$packagingWheel,$builder,'assemble','--inputs',(Join-Path $kit 'inputs'),'--wheel',(Join-Path $kit $manifest.scmm_wheel),'--output',$runtime)
    Write-Host 'Running scientific checks in the original directory...'
    & (Join-Path $runtime 'validate-runtime.ps1') -Runtime $runtime -Report (Join-Path $work 'before.json') >> $log 2>&1
    # ASCII script source also works with Windows PowerShell 5's legacy encoding defaults.
    $relocation = Join-Path $work ([string]::Concat([char]0x4e2d,[char]0x6587,' relocation'))
    New-Item -ItemType Directory -Path $relocation | Out-Null
    $movedRuntime = Join-Path $relocation 'runtime'
    Move-Item -LiteralPath $runtime -Destination $movedRuntime
    Write-Host 'Running scientific checks after moving to a Chinese/space path...'
    & (Join-Path $movedRuntime 'validate-runtime.ps1') -Runtime $movedRuntime -Report (Join-Path $work 'after.json') >> $log 2>&1
    $summary.status = 'passed'
    $summary.runtime = $movedRuntime
    Write-Host ('Passed. Reports: ' + $work)
} catch {
    $summary.status = 'failed'
    $summary.error = $_.Exception.Message
    $_ | Out-String | Add-Content -LiteralPath $log
    Write-Host ('Failed. Keep the diagnostic folder: ' + $work)
} finally {
    foreach ($name in @('PYTHONNOUSERSITE','TEMP','TMP','MPLCONFIGDIR','NUMBA_CACHE_DIR')) {
        Remove-Item ('Env:' + $name) -ErrorAction SilentlyContinue
    }
    foreach ($entry in $saved.GetEnumerator()) { Set-Item ('Env:' + $entry.Key) $entry.Value }
    $summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $work 'session.json') -Encoding UTF8
}
if ($summary.status -ne 'passed') { throw ('WIN-01 failed; reports are in ' + $work) }
