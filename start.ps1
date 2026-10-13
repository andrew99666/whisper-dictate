$projectDir = $PSScriptRoot
$launcher = Join-Path $projectDir '.venv\Scripts\pythonw.exe'
$entryPoint = Join-Path $projectDir 'main.py'
if (-not (Test-Path -LiteralPath $launcher)) {
    throw 'The runtime is missing. Install requirements in .venv first.'
}
$running = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and
    $_.CommandLine -like "*$entryPoint*"
}
if ($running) {
    Write-Output 'Whisper Dictate is already running. Hold Right Ctrl to dictate.'
    exit 0
}
Start-Process -FilePath $launcher -ArgumentList @('"' + $entryPoint + '"') -WorkingDirectory $projectDir -WindowStyle Hidden
Write-Output 'Whisper Dictate launched. Hold Right Ctrl to dictate.'
