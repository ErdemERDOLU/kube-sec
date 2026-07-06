#!/usr/bin/env pwsh
# =============================================================================
# Kube-Sec Windows Build Script
# =============================================================================
# Açıklama : PyInstaller ile Kube-Sec'i Windows masaüstü uygulaması olarak
#            paketler. Giriş noktası launcher.py'dir; pywebview native pencere
#            desteği, otomatik port bulma ve 127.0.0.1 bind davranışı dahildir.
#            macOS build_macos_app.sh ile tutarlı --add-data yolları ve
#            PyInstaller seçenekleri kullanılır.
#
# Kullanım  :
#   Windows PowerShell  : .\build-windows.ps1
#   macOS/Linux (pwsh)  : pwsh ./build-windows.ps1
#
# Gereksinimler:
#   - Python 3.9+ (PATH'te python, python3 veya py olarak erişilebilir)
#   - Proje bağımlılıkları (requirements.txt) kurulu veya venv oluşturulacak
#
# NOT: PyInstaller cross-compile desteklemez. Windows .exe üretimi ve testi
#      gerçek bir Windows ortamında (veya Windows VM) yapılmalıdır.
# =============================================================================

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Repo kökünde çalıştığımızdan emin ol
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# $IsWindows değişkenini hem Windows PowerShell hem PowerShell Core'da garantile
# (PowerShell Core 6+'da $IsWindows Global scope'ta otomatik tanımlıdır; Windows
# PowerShell 5.1'de hiç yoktur -- bu yüzden -Scope belirtmeden arıyoruz.)
if (-not (Get-Variable -Name IsWindows -ErrorAction SilentlyContinue)) {
    try {
        $IsWindows = [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
            [System.Runtime.InteropServices.OSPlatform]::Windows
        )
    } catch {
        $IsWindows = ($env:OS -eq 'Windows_NT')
    }
}

# Python yorumlayıcısını bul (python, python3, py sırasıyla dene)
$pythonCandidates = @('python', 'python3', 'py')
$PythonCmd = $null
foreach ($p in $pythonCandidates) {
    if (Get-Command $p -ErrorAction SilentlyContinue) {
        $PythonCmd = $p
        break
    }
}
if (-not $PythonCmd) {
    Write-Error "Python 3 PATH'te bulunamadı. Lütfen Python 3 kurun ve 'python' ya da 'python3' PATH'te erişilebilir olsun."
    exit 1
}
Write-Host "Python yorumlayıcısı: $PythonCmd"

# Virtual environment oluştur ve etkinleştir
if (-not (Test-Path .venv)) {
    Write-Host "Virtual environment oluşturuluyor..."
    & $PythonCmd -m venv .venv
}

if ($IsWindows) {
    $activate = Join-Path -Path ".venv" -ChildPath "Scripts\Activate.ps1"
} else {
    $activate = Join-Path -Path ".venv" -ChildPath "bin/Activate.ps1"
}

if (Test-Path $activate) {
    . $activate
} else {
    Write-Host "Uyarı: venv etkinleştirme betiği bulunamadı: $activate — venv etkinleştirmesi atlanıyor." -ForegroundColor Yellow
}

# Bağımlılıkları kur
Write-Host "Python bağımlılıkları kuruluyor..."
& $PythonCmd -m pip install --upgrade pip --quiet
& $PythonCmd -m pip install -r requirements.txt --quiet
& $PythonCmd -m pip install pyinstaller --quiet

# VERSION dosyasından versiyon oku
$versionFile = Join-Path $root "VERSION"
if (Test-Path $versionFile) {
    $appVersion = (Get-Content $versionFile -Raw).Trim()
} else {
    $appVersion = "1.0.0"
    Write-Host "Uyarı: VERSION dosyası bulunamadı, varsayılan '1.0.0' kullanılıyor." -ForegroundColor Yellow
}
Write-Host "Uygulama versiyonu: $appVersion"

# Versiyon parçalarını ayır (PyInstaller version-file için dördüzlü gerekiyor)
$vParts = $appVersion -split '\.'
$vMajor = if ($vParts.Count -ge 1) { [int]$vParts[0] } else { 1 }
$vMinor = if ($vParts.Count -ge 2) { [int]$vParts[1] } else { 0 }
$vPatch = if ($vParts.Count -ge 3) { [int]$vParts[2] } else { 0 }
$vBuild = 0

# Windows VSVersionInfo şablonunu dinamik oluştur
$versionInfoPath = Join-Path $root "build_version_info.txt"
$versionInfoContent = @"
# Kube-Sec Windows Versiyon Bilgisi
# PyInstaller tarafından --version-file parametresiyle kullanılır.
# Bu dosya build sırasında otomatik üretilir; elle düzenleme.
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($vMajor, $vMinor, $vPatch, $vBuild),
    prodvers=($vMajor, $vMinor, $vPatch, $vBuild),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          u'040904B0',
          [StringStruct(u'CompanyName', u'Kube-Sec'),
           StringStruct(u'FileDescription', u'Kube-Sec Kubernetes Guvenlik Panosu'),
           StringStruct(u'FileVersion', u'$appVersion'),
           StringStruct(u'InternalName', u'Kube-Sec'),
           StringStruct(u'LegalCopyright', u'Kube-Sec Contributors'),
           StringStruct(u'OriginalFilename', u'Kube-Sec.exe'),
           StringStruct(u'ProductName', u'Kube-Sec'),
           StringStruct(u'ProductVersion', u'$appVersion')])
      ]
    ),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"@

Set-Content -Path $versionInfoPath -Value $versionInfoContent -Encoding UTF8
Write-Host "Versiyon bilgisi dosyası oluşturuldu: $versionInfoPath"

# Önceki build çıktılarını temizle
Write-Host "Önceki build kalıntıları temizleniyor..."
if (Test-Path dist)                   { Remove-Item -Recurse -Force dist }
if (Test-Path build)                  { Remove-Item -Recurse -Force build }
if (Test-Path "Kube-Sec.spec")        { Remove-Item -Force "Kube-Sec.spec" }

# Platform ayırıcısını belirle (Windows: ';', diğer: ':')
$sep = if ($IsWindows) { ';' } else { ':' }

# --add-data eşlemeleri (build_macos_app.sh satır 109-113 ile aynı mantık)
$addDataList = @(
    "src/web/templates${sep}web/templates",
    "src/web/static${sep}web/static",
    "src${sep}src",
    "styles${sep}styles",
    "yaml${sep}yaml"
)

# PyInstaller argüman dizisini oluştur
$pyArgs = @(
    '--onedir',
    '--noconfirm',
    '--windowed',
    '--name', 'Kube-Sec',
    '--paths', 'src',
    '--hidden-import', 'webview',
    '--hidden-import', 'webview.util',
    '--hidden-import', 'webview.platforms.edgechromium',
    '--hidden-import', 'webview.platforms.mshtml',
    '--version-file', $versionInfoPath
)

foreach ($d in $addDataList) {
    $pyArgs += "--add-data=$d"
}

# İkon dosyası varsa ekle
$iconPath = Join-Path $root "icon.ico"
if (Test-Path $iconPath) {
    $pyArgs += "--icon=$iconPath"
} else {
    Write-Host "Uyarı: icon.ico bulunamadı; ikon eklenmeden paketlenecek." -ForegroundColor Yellow
}

# Giriş noktası: launcher.py
$pyArgs += 'launcher.py'

Write-Host "PyInstaller çalıştırılıyor..."
Write-Host "Argümanlar: $($pyArgs -join ' ')"
& $PythonCmd -m PyInstaller @pyArgs

if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller $LASTEXITCODE çıkış kodu ile başarısız oldu."
    exit $LASTEXITCODE
}

# Geçici versiyon dosyasını temizle
Remove-Item -Force $versionInfoPath -ErrorAction SilentlyContinue

# -----------------------------------------------------------------------
# Opsiyonel: Windows Code Signing
# SIGN_CERT veya SIGN_IDENTITY ortam değişkeni verilmişse signtool çalıştır.
# Gerçek imzalama için geçerli bir kod imzalama sertifikası gereklidir.
# -----------------------------------------------------------------------
$signCert = $env:SIGN_CERT
$signIdentity = $env:SIGN_IDENTITY
$exePath = Join-Path $root (Join-Path "dist" (Join-Path "Kube-Sec" "Kube-Sec.exe"))

if (($signCert -or $signIdentity) -and (Test-Path $exePath)) {
    Write-Host "Kod imzalama uygulanıyor..." -ForegroundColor Cyan
    $signtool = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($signtool) {
        if ($signCert) {
            & signtool.exe sign /f $signCert /fd SHA256 /t http://timestamp.digicert.com $exePath
        } elseif ($signIdentity) {
            & signtool.exe sign /n $signIdentity /fd SHA256 /t http://timestamp.digicert.com $exePath
        }
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Uyarı: Kod imzalama başarısız oldu (çıkış kodu: $LASTEXITCODE). Build devam ediyor." -ForegroundColor Yellow
        } else {
            Write-Host "Kod imzalama başarılı." -ForegroundColor Green
        }
    } else {
        Write-Host "Uyarı: signtool.exe bulunamadı. Kod imzalama atlandı." -ForegroundColor Yellow
    }
} elseif ($signCert -or $signIdentity) {
    Write-Host "Uyarı: Kod imzalama istenildi ancak çıktı exe bulunamadı: $exePath" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Build tamamlandı! Çıktı: dist\Kube-Sec\Kube-Sec.exe" -ForegroundColor Green
Write-Host "Versiyon: $appVersion" -ForegroundColor Green
