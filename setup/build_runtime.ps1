# FieldFactor - runtime builder
# Downloads embedded CPython + all required libraries into .\runtime
# Run once per computer. Needs internet. After that the program works offline.

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root     = Split-Path -Parent $PSScriptRoot
$runtime  = Join-Path $root 'runtime'
$dl       = Join-Path $root '_завантаження'

$pyVer    = '3.12.10'
$pyUrl    = "https://www.python.org/ftp/python/$pyVer/python-$pyVer-embed-amd64.zip"
$pipUrl   = 'https://bootstrap.pypa.io/get-pip.py'

$packages = @(
  'numpy',
  'pandas',
  'scipy',
  'scikit-learn',
  'shapely',
  'pyproj',
  'pyogrio',
  'geopandas',
  'rasterio',
  'requests',
  'pystac-client',
  'planetary-computer',
  # Excel. Gospodarstva viddaiut istoriiu poliv tablytseiu, a ne bazoiu:
  # master table z rokamy, kulturamy, hibrydamy i operatsiiamy. Bez tsioho
  # paketa .xlsx ne chytaietsia vzahali.
  'openpyxl',
  'Pillow'
)

function Say($text) { Write-Host "  $text" -ForegroundColor Cyan }
function Ok($text)  { Write-Host "  $text" -ForegroundColor Green }
function Bad($text) { Write-Host "  $text" -ForegroundColor Red }

Write-Host ''
Write-Host '  FieldFactor - збірка робочого середовища' -ForegroundColor White
Write-Host '  ----------------------------------------' -ForegroundColor DarkGray
Write-Host ''

if (Test-Path (Join-Path $runtime 'python.exe')) {
    Say 'Середовище вже зібране.'
    $answer = Read-Host '  Перезібрати з нуля? (т/н)'
    if ($answer -ne 'т' -and $answer -ne 't' -and $answer -ne 'y') {
        Ok 'Нічого не змінено. Запускайте ЗАПУСК.bat'
        exit 0
    }
    Remove-Item $runtime -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $dl | Out-Null

# --- 1. embedded python -------------------------------------------------
Say "Крок 1 з 4. Завантажую Python $pyVer (~11 МБ)…"
$pyZip = Join-Path $dl "python-$pyVer-embed-amd64.zip"
if (-not (Test-Path $pyZip)) {
    Invoke-WebRequest -Uri $pyUrl -OutFile $pyZip -UseBasicParsing
}
Expand-Archive -Path $pyZip -DestinationPath $runtime -Force
Ok 'Python розпаковано.'

# --- 2. enable site-packages -------------------------------------------
Say 'Крок 2 з 4. Налаштовую середовище…'
$pth = Get-ChildItem -Path $runtime -Filter 'python*._pth' | Select-Object -First 1
if (-not $pth) { Bad 'Не знайдено файл ._pth — збірка неможлива.'; exit 1 }
@'
python312.zip
.
Lib\site-packages

import site
'@ | Set-Content -Path $pth.FullName -Encoding ascii
New-Item -ItemType Directory -Force -Path (Join-Path $runtime 'Lib\site-packages') | Out-Null
Ok 'Середовище налаштоване.'

# --- 3. pip -------------------------------------------------------------
Say 'Крок 3 з 4. Ставлю менеджер пакетів…'
$getPip = Join-Path $dl 'get-pip.py'
if (-not (Test-Path $getPip)) {
    Invoke-WebRequest -Uri $pipUrl -OutFile $getPip -UseBasicParsing
}
& (Join-Path $runtime 'python.exe') $getPip --no-warn-script-location 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Bad 'Не вдалося поставити pip.'; exit 1 }
Ok 'Менеджер пакетів готовий.'

# --- 4. libraries -------------------------------------------------------
Say 'Крок 4 з 4. Ставлю бібліотеки обробки (~500 МБ, це найдовше)…'
Write-Host ''
& (Join-Path $runtime 'python.exe') -m pip install --no-warn-script-location --disable-pip-version-check @packages
if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Bad 'Частина бібліотек не стала. Перевірте інтернет і запустіть ще раз.'
    exit 1
}

# --- перевірка ----------------------------------------------------------
Write-Host ''
Say 'Перевіряю…'
$check = & (Join-Path $runtime 'python.exe') -c "import geopandas,rasterio,sklearn,pystac_client,planetary_computer;print('OK')" 2>&1
if ($check -notmatch 'OK') {
    Bad 'Перевірка не пройшла:'
    Write-Host $check
    exit 1
}

Remove-Item $dl -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ''
Ok 'Готово. Тепер запускайте ЗАПУСК.bat'
Write-Host ''
