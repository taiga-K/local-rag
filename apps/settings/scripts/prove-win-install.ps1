param(
  [Parameter(Mandatory = $true)][ValidateSet("install", "check", "detect", "uninstall")][string]$Phase,
  [string]$ReleaseDir = ""
)

$ErrorActionPreference = "Stop"
$AppDirName = "kbindex settings"

function Find-InstallRoot {
  $candidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\$AppDirName"),
    (Join-Path $env:ProgramFiles $AppDirName)
  )
  foreach ($dir in $candidates) {
    if (Test-Path -LiteralPath (Join-Path $dir "$AppDirName.exe")) {
      return $dir
    }
  }
  return $null
}

function Find-Shortcut {
  $candidates = @(
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "$AppDirName.lnk"),
    (Join-Path $env:PUBLIC "Desktop\$AppDirName.lnk")
  )
  foreach ($path in $candidates) {
    if (Test-Path -LiteralPath $path) {
      return $path
    }
  }
  return $null
}

function Invoke-PhaseInstall {
  if (-not $ReleaseDir) {
    throw "ReleaseDir is required"
  }
  $setup = Get-ChildItem -Path $ReleaseDir -Filter "*.exe" |
    Where-Object { $_.Name -like "*Setup*" } |
    Select-Object -First 1
  if (-not $setup) {
    throw "setup exe not found in $ReleaseDir"
  }
  Write-Host "SETUP $($setup.FullName)"
  $proc = Start-Process -FilePath $setup.FullName -ArgumentList @("/S", "/currentuser") -PassThru
  if (-not $proc.WaitForExit(180000)) {
    throw "silent install did not exit within 180s"
  }
  Write-Host "INSTALL_EXIT $($proc.ExitCode)"
  if ($proc.ExitCode -ne 0) {
    throw "silent install exited $($proc.ExitCode)"
  }
  $dest = $null
  for ($i = 0; $i -lt 30; $i++) {
    $dest = Find-InstallRoot
    if ($dest) { break }
    Start-Sleep -Seconds 1
  }
  if (-not $dest) {
    throw "install dir not found"
  }
  $app = Join-Path $dest "$AppDirName.exe"
  $uninst = Join-Path $dest "Uninstall $AppDirName.exe"
  if (-not (Test-Path -LiteralPath $uninst)) {
    throw "uninstaller missing: $uninst"
  }
  $shortcut = $null
  for ($i = 0; $i -lt 15; $i++) {
    $shortcut = Find-Shortcut
    if ($shortcut) { break }
    Start-Sleep -Seconds 1
  }
  if (-not $shortcut) {
    $desktop = [Environment]::GetFolderPath("Desktop")
    Write-Host "DESKTOP $desktop"
    if (Test-Path -LiteralPath $desktop) {
      Get-ChildItem -LiteralPath $desktop | ForEach-Object { Write-Host "DESKTOP_ENTRY $($_.Name)" }
    }
    throw "shortcut missing"
  }
  Write-Host "INSTALL_DIR $dest"
  Write-Host "APP $app"
  Write-Host "SHORTCUT $shortcut"
}

function Invoke-PhaseCheck {
  $dest = Find-InstallRoot
  if (-not $dest) {
    throw "install dir not found"
  }
  $app = Join-Path $dest "$AppDirName.exe"
  $report = Join-Path $env:TEMP "kbindex-docker-check.txt"
  if (Test-Path -LiteralPath $report) {
    Remove-Item -LiteralPath $report
  }
  $env:KBINDEX_CHECK_REPORT = $report
  $proc = Start-Process -FilePath $app -ArgumentList "--check" -PassThru
  if (-not $proc.WaitForExit(120000)) {
    try { $proc.Kill() } catch { }
    throw "app --check did not exit within 120s"
  }
  Write-Host "APP_CHECK_EXIT $($proc.ExitCode)"
  if ($proc.ExitCode -ne 0) {
    throw "app --check exited $($proc.ExitCode)"
  }
  if (-not (Test-Path -LiteralPath $report)) {
    throw "check report missing: $report"
  }
  $line = Get-Content -LiteralPath $report -TotalCount 1
  Write-Host "APP_CHECK_REPORT"
  Get-Content -LiteralPath $report | ForEach-Object { Write-Host $_ }
  if ($line -notmatch "^docker-mode=(host|wsl|none)$") {
    throw "unexpected report: $line"
  }
}

function Write-Probe {
  param([string]$Label, [string]$File, [string[]]$ArgumentList)
  $cmd = Get-Command $File -ErrorAction SilentlyContinue
  if (-not $cmd) {
    Write-Host "DETECTION $Label missing"
    return
  }
  $out = Join-Path $env:TEMP "kbindex-probe-out.txt"
  $err = Join-Path $env:TEMP "kbindex-probe-err.txt"
  Remove-Item -LiteralPath $out, $err -ErrorAction SilentlyContinue
  $proc = Start-Process -FilePath $cmd.Source -ArgumentList $ArgumentList -PassThru -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err
  if (-not $proc.WaitForExit(20000)) {
    try { $proc.Kill() } catch { }
    Write-Host "DETECTION $Label path $($cmd.Source) timeout"
    return
  }
  Write-Host "DETECTION $Label path $($cmd.Source) exit $($proc.ExitCode)"
  if ($proc.ExitCode -ne 0 -and (Test-Path -LiteralPath $err)) {
    Get-Content -LiteralPath $err -TotalCount 3 | ForEach-Object { Write-Host "DETECTION $Label stderr $_" }
  }
}

function Invoke-PhaseDetect {
  Write-Probe "docker info" "docker" @("info")
  Write-Probe "docker compose version" "docker" @("compose", "version")
  Write-Probe "wsl.exe -e docker info" "wsl.exe" @("-e", "docker", "info")
  Write-Probe "wsl.exe -e docker compose version" "wsl.exe" @("-e", "docker", "compose", "version")
}

function Invoke-PhaseUninstall {
  $dest = Find-InstallRoot
  if (-not $dest) {
    throw "install dir not found"
  }
  $shortcut = Find-Shortcut
  $uninst = Join-Path $dest "Uninstall $AppDirName.exe"
  if (-not (Test-Path -LiteralPath $uninst)) {
    throw "uninstaller missing: $uninst"
  }
  $proc = Start-Process -FilePath $uninst -ArgumentList "/S" -PassThru
  if (-not $proc.WaitForExit(90000)) {
    throw "silent uninstall did not exit within 90s"
  }
  Write-Host "UNINSTALL_EXIT $($proc.ExitCode)"
  if ($proc.ExitCode -ne 0) {
    throw "silent uninstall exited $($proc.ExitCode)"
  }
  # NSIS copies the uninstaller to %TEMP% and the process we started exits before that copy deletes the files.
  $app = Join-Path $dest "$AppDirName.exe"
  for ($i = 0; $i -lt 60; $i++) {
    $appLeft = Test-Path -LiteralPath $app
    $uninstLeft = Test-Path -LiteralPath $uninst
    $linkLeft = $shortcut -and (Test-Path -LiteralPath $shortcut)
    if (-not $appLeft -and -not $uninstLeft -and -not $linkLeft) {
      break
    }
    Start-Sleep -Seconds 1
  }
  if (Test-Path -LiteralPath $app) {
    throw "app remains: $app"
  }
  if (Test-Path -LiteralPath $uninst) {
    throw "uninstaller remains: $uninst"
  }
  if ($shortcut -and (Test-Path -LiteralPath $shortcut)) {
    throw "shortcut remains: $shortcut"
  }
  if (Test-Path -LiteralPath $dest) {
    $left = @(Get-ChildItem -LiteralPath $dest -Force)
    foreach ($item in $left) {
      Write-Host "LEFT $($item.Name)"
    }
    if ($left.Count -gt 0) {
      throw "install dir not empty: $dest"
    }
    Remove-Item -LiteralPath $dest -Force
    Write-Host "CLEANUP removed empty install dir"
  }
  if (Test-Path -LiteralPath $dest) {
    throw "install dir remains: $dest"
  }
  Write-Host "CLEANUP app files and shortcut are gone"
}

switch ($Phase) {
  "install" { Invoke-PhaseInstall }
  "check" { Invoke-PhaseCheck }
  "detect" { Invoke-PhaseDetect }
  "uninstall" { Invoke-PhaseUninstall }
  default { throw "unknown phase $Phase" }
}
