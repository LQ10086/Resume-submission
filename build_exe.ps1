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

Write-Host "Checking pywinpty..."
try {
  python -c "import winpty" *> $null
  if ($LASTEXITCODE -ne 0) {
    throw "pywinpty missing"
  }
} catch {
  Write-Host "pywinpty not found. Installing terminal support..."
  python -m pip install "pywinpty>=2.0.15"
  if ($LASTEXITCODE -ne 0) {
    throw "pywinpty installation failed with exit code $LASTEXITCODE."
  }
}

Write-Host "Checking pyte..."
try {
  python -c "import pyte" *> $null
  if ($LASTEXITCODE -ne 0) {
    throw "pyte missing"
  }
} catch {
  Write-Host "pyte not found. Installing terminal renderer..."
  python -m pip install "pyte>=0.8.2"
  if ($LASTEXITCODE -ne 0) {
    throw "pyte installation failed with exit code $LASTEXITCODE."
  }
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

New-Item -ItemType Directory -Path $DataDest -Force > $null
New-Item -ItemType Directory -Path $ResumeDest -Force > $null

$ExistingDataFiles = @(Get-ChildItem -LiteralPath $DataDest -Filter "*.json" -File -Force)
if ($ExistingDataFiles.Count -eq 0) {
  Get-ChildItem -LiteralPath (Join-Path $Root "databases") -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $DataDest -Recurse -Force
  }
}
$ExistingResumeFiles = @(Get-ChildItem -LiteralPath $ResumeDest -File -Force -Recurse)
if ($ExistingResumeFiles.Count -eq 0) {
  Get-ChildItem -LiteralPath (Join-Path $Root "resumes_by_role") -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $ResumeDest -Recurse -Force
  }
}
Copy-Item -Path "$Root\README.md" -Destination "$Release\README.md" -Force
if (Test-Path -LiteralPath (Join-Path $Root "UPGRADE_FOR_CODEX.md")) {
  Copy-Item -LiteralPath (Join-Path $Root "UPGRADE_FOR_CODEX.md") -Destination "$Release\UPGRADE_FOR_CODEX.md" -Force
}
Get-ChildItem -LiteralPath $Root -Filter "AI_PROMPT_*.txt" | ForEach-Object {
  Copy-Item -LiteralPath $_.FullName -Destination "$Release\$($_.Name)" -Force
}

Write-Host ""
Write-Host "Done. Run: release\ResumeQuickPaste.exe"
