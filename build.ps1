$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Project virtual environment was not found. Install requirements first."
}

$outputRoot = Join-Path $PSScriptRoot "dist-windows"
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null

# Keep unrelated Anaconda/OpenSSL installations on the machine from being
# selected while PyInstaller resolves Python's _ssl.pyd dependencies.
$pythonRoot = & $python -c "import sys; print(sys.base_prefix)"
$pythonDlls = Join-Path $pythonRoot "DLLs"
$env:PATH = @(
    $pythonDlls,
    $pythonRoot,
    (Join-Path $env:SystemRoot "System32"),
    $env:SystemRoot,
    (Join-Path $env:SystemRoot "System32\Wbem")
) -join ";"

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name DataSheet `
    --collect-data tzdata `
    --add-binary "$pythonDlls\libssl-3-x64.dll;." `
    --add-binary "$pythonDlls\libcrypto-3-x64.dll;." `
    --distpath $outputRoot `
    --workpath (Join-Path $PSScriptRoot "build") `
    --specpath $PSScriptRoot `
    (Join-Path $PSScriptRoot "run_datasheet.py")

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}

Write-Host "Build complete: $outputRoot\DataSheet\DataSheet.exe"
