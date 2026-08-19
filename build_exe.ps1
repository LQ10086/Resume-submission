$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$Release = Join-Path $Root "release"
$RuntimePython = Join-Path $Root ".python-runtime\python.exe"
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$SetupScript = Join-Path $Root "setup_pyside6.ps1"
if (Test-Path -LiteralPath $SetupScript) {
  Write-Host "Preparing the project PySide6 environment..."
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $SetupScript
  if ($LASTEXITCODE -ne 0) {
    throw "PySide6 environment setup failed with exit code $LASTEXITCODE."
  }
}
$Python = if (Test-Path -LiteralPath $RuntimePython) {
  $RuntimePython
} elseif (Test-Path -LiteralPath $VenvPython) {
  $VenvPython
} else {
  "python"
}

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
  & $Python -c "import PyInstaller" *> $null
  if ($LASTEXITCODE -eq 0) {
    $PyInstallerOk = $true
  }
} catch {
  $PyInstallerOk = $false
}

if (-not $PyInstallerOk) {
  Write-Host "PyInstaller not found. Installing it with pip..."
  & $Python -m pip install "pyinstaller>=6.0"
}

Write-Host "Checking PySide6..."
try {
  & $Python -c "import PySide6" *> $null
  if ($LASTEXITCODE -ne 0) {
    throw "PySide6 missing"
  }
} catch {
  Write-Host "PySide6 not found. Installing Qt interface support..."
  & $Python -m pip install "PySide6==6.10.1"
  if ($LASTEXITCODE -ne 0) {
    throw "PySide6 installation failed with exit code $LASTEXITCODE."
  }
}

Write-Host "Checking pywinpty..."
try {
  & $Python -c "import winpty" *> $null
  if ($LASTEXITCODE -ne 0) {
    throw "pywinpty missing"
  }
} catch {
  Write-Host "pywinpty not found. Installing terminal support..."
  & $Python -m pip install "pywinpty>=3.0.5"
  if ($LASTEXITCODE -ne 0) {
    throw "pywinpty installation failed with exit code $LASTEXITCODE."
  }
}

Write-Host "Checking pyte..."
try {
  & $Python -c "import pyte" *> $null
  if ($LASTEXITCODE -ne 0) {
    throw "pyte missing"
  }
} catch {
  Write-Host "pyte not found. Installing terminal renderer..."
  & $Python -m pip install "pyte>=0.8.2"
  if ($LASTEXITCODE -ne 0) {
    throw "pyte installation failed with exit code $LASTEXITCODE."
  }
}

Write-Host "Building executable..."
$WinptyDir = (& $Python -c "from pathlib import Path; import winpty; print(Path(winpty.__file__).parent)").Trim()
$WinptyOpenConsole = Join-Path $WinptyDir "OpenConsole.exe"
$WinptyAgent = Join-Path $WinptyDir "winpty-agent.exe"
foreach ($RequiredWinptyFile in @($WinptyOpenConsole, $WinptyAgent)) {
  if (-not (Test-Path -LiteralPath $RequiredWinptyFile)) {
    throw "Required pywinpty helper is missing: $RequiredWinptyFile"
  }
}
$SavedPath = $env:PATH
$SavedCondaPrefix = $env:CONDA_PREFIX
$SavedQtPluginPath = $env:QT_PLUGIN_PATH
$SavedQmlImportPath = $env:QML2_IMPORT_PATH
try {
  # PyInstaller resolves DLLs by PATH.  An activated Conda environment can make
  # it bundle Conda's ICU/UCRT forwarding DLLs, which then shadow the Windows
  # system copies and make the packaged PySide6 QtCore fail on another PC.
  $RuntimeDir = Split-Path -Parent ([System.IO.Path]::GetFullPath($Python))
  $env:PATH = @(
    $RuntimeDir
    (Join-Path $env:SystemRoot "System32")
    $env:SystemRoot
    (Join-Path $env:SystemRoot "System32\Wbem")
    (Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0")
  ) -join ";"
  $env:CONDA_PREFIX = $null
  $env:QT_PLUGIN_PATH = $null
  $env:QML2_IMPORT_PATH = $null

  & $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name ResumeQuickPaste `
    --distpath release `
    --workpath build `
    --specpath build `
    --add-binary "$WinptyOpenConsole;winpty" `
    --add-binary "$WinptyAgent;winpty" `
    src\app.py
} finally {
  $env:PATH = $SavedPath
  $env:CONDA_PREFIX = $SavedCondaPrefix
  $env:QT_PLUGIN_PATH = $SavedQtPluginPath
  $env:QML2_IMPORT_PATH = $SavedQmlImportPath
}

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
