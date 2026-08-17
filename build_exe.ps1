$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$Release = Join-Path $Root "release"

function Assert-PathInsideRelease($PathToCheck) {
  $FullPath = [System.IO.Path]::GetFullPath($PathToCheck)
  $ReleaseFullPath = [System.IO.Path]::GetFullPath($Release)
  if (-not $FullPath.StartsWith($ReleaseFullPath, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to modify path outside release: $FullPath"
  }
  return $FullPath
}

Write-Host "Checking PyInstaller..."
$PyInstallerOk = $false
try {
  python -c "import PyInstaller" *> $null
  if ($LASTEXITCODE -eq 0) {
    $PyInstallerOk = $true
  }
} catch {
  $PyInstallerOk = $false
}

if (-not $PyInstallerOk) {
  Write-Host "PyInstaller not found. Installing it with pip..."
  python -m pip install pyinstaller
}

Write-Host "Building executable..."
python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --name ResumeQuickPaste `
  --distpath release `
  --workpath build `
  --specpath build `
  app.py

if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller build failed with exit code $LASTEXITCODE. Close release\ResumeQuickPaste.exe if it is running, then retry."
}

Write-Host "Copying editable data and docs..."
$DataDest = Assert-PathInsideRelease (Join-Path $Release "databases")
$ResumeDest = Assert-PathInsideRelease (Join-Path $Release "resumes_by_role")

if (Test-Path -LiteralPath $DataDest) {
  Remove-Item -LiteralPath $DataDest -Recurse -Force
}
if (Test-Path -LiteralPath $ResumeDest) {
  Remove-Item -LiteralPath $ResumeDest -Recurse -Force
}

New-Item -ItemType Directory -Path $DataDest -Force > $null
New-Item -ItemType Directory -Path $ResumeDest -Force > $null

Copy-Item -Path (Join-Path $Root "databases\*") -Destination $DataDest -Recurse -Force
Copy-Item -Path (Join-Path $Root "resumes_by_role\*") -Destination $ResumeDest -Recurse -Force
Copy-Item -Path "$Root\README.md" -Destination "$Release\README.md" -Force
Get-ChildItem -LiteralPath $Root -Filter "AI_PROMPT_*.txt" | ForEach-Object {
  Copy-Item -LiteralPath $_.FullName -Destination "$Release\$($_.Name)" -Force
}

Write-Host ""
Write-Host "Done. Run: release\ResumeQuickPaste.exe"
