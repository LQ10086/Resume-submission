$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RuntimeDir = Join-Path $ProjectRoot ".python-runtime"
$RuntimePython = Join-Path $RuntimeDir "python.exe"
$PythonVersion = "3.13.15"
$PythonZipName = "python-$PythonVersion-embed-amd64.zip"
$PythonZipUrl = "https://www.python.org/ftp/python/$PythonVersion/$PythonZipName"
$PythonZip = Join-Path ([System.IO.Path]::GetTempPath()) $PythonZipName
$GetPip = Join-Path ([System.IO.Path]::GetTempPath()) "resume-quick-paste-get-pip.py"

function Test-Runtime {
  if (-not (Test-Path -LiteralPath $RuntimePython)) {
    return $false
  }
  & $RuntimePython -c "import pip, PySide6, winpty, pyte, wcwidth, PyInstaller; from PySide6.QtCore import qVersion" *> $null
  return $LASTEXITCODE -eq 0
}

if (Test-Runtime) {
  Write-Host "PySide6 environment is ready: $RuntimePython"
  & $RuntimePython -c "import PySide6; from PySide6.QtCore import qVersion; print(f'PySide6 {PySide6.__version__} / Qt {qVersion()}')"
  exit 0
}

if (Test-Path -LiteralPath $RuntimeDir) {
  $RuntimeFull = [System.IO.Path]::GetFullPath($RuntimeDir)
  $ProjectFull = [System.IO.Path]::GetFullPath($ProjectRoot)
  if (-not $RuntimeFull.StartsWith($ProjectFull + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to move runtime outside the project: $RuntimeFull"
  }
  $BackupDir = "$RuntimeDir-broken-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
  Move-Item -LiteralPath $RuntimeFull -Destination $BackupDir
  Write-Host "Previous incomplete runtime moved to: $BackupDir"
}

Write-Host "Downloading official portable Python $PythonVersion..."
Invoke-WebRequest -Uri $PythonZipUrl -OutFile $PythonZip
New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null
Expand-Archive -LiteralPath $PythonZip -DestinationPath $RuntimeDir -Force

$PthPath = Join-Path $RuntimeDir "python313._pth"
$PthLines = @(
  "python313.zip",
  ".",
  "..",
  "Lib\site-packages",
  "",
  "import site"
)
[System.IO.File]::WriteAllLines($PthPath, $PthLines, [System.Text.UTF8Encoding]::new($false))

Write-Host "Installing pip into the project runtime..."
Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $GetPip
& $RuntimePython $GetPip --disable-pip-version-check
if ($LASTEXITCODE -ne 0) {
  throw "pip bootstrap failed with exit code $LASTEXITCODE."
}

Write-Host "Installing PySide6 and terminal dependencies..."
& $RuntimePython -m pip install --disable-pip-version-check -r (Join-Path $ProjectRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) {
  throw "Dependency installation failed with exit code $LASTEXITCODE."
}

if (-not (Test-Runtime)) {
  throw "The PySide6 runtime was installed but failed its import verification."
}

Write-Host "Environment ready: $RuntimePython"
& $RuntimePython -c "import PySide6; from PySide6.QtCore import qVersion; print(f'PySide6 {PySide6.__version__} / Qt {qVersion()}')"
