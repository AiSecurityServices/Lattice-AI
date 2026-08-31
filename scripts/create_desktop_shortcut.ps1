# Creates a desktop shortcut that launches Lattice AI (local server + browser UI).
# Re-runnable: adjusts itself to wherever this project folder lives.
param(
    [string]$Python = ""
)
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot   # scripts/ -> project root
$launcher = Join-Path $projectRoot "scripts\lattice_launcher.py"

if (-not $Python) {
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $cmd) { throw "python.exe not found on PATH; pass -Python <path>" }
    $Python = $cmd.Source
}

$desktop = [Environment]::GetFolderPath("Desktop")
$lnkPath = Join-Path $desktop "Lattice AI.lnk"

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($lnkPath)
$lnk.TargetPath = $Python
$lnk.Arguments = ('"' + $launcher + '"')
$lnk.WorkingDirectory = $projectRoot
$lnk.IconLocation = "$Python,0"
$lnk.Description = "Lattice AI: start local server and open the web UI"
$lnk.Save()

Write-Output "created: $lnkPath"
Write-Output "target : $Python `"$launcher`""
