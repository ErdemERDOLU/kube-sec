#!/usr/bin/env bash
# Linux masaüstü paket build scripti (backlog #11)
#
# PyInstaller --onedir modu ile dist/Kube-Sec/ klasörü üretilir;
# ardından Kube-Sec-{VERSION}-linux-x86_64.tar.gz olarak arşivlenir.
#
# Kullanım:
#   bash build_linux_app.sh                    # VERSION dosyasından versiyon okur
#   APP_VERSION=1.2.3 bash build_linux_app.sh  # Versiyon dışarıdan verilir
#
# Not: PyInstaller cross-compile desteklemez. Bu script yalnızca Linux'ta
# çalıştırıldığında Linux binary'si üretir (GitHub Actions: ubuntu-latest).
set -euo pipefail

APP_NAME="Kube-Sec"
PYTHON_BIN="${PYTHON:-python3}"

# Versiyon: APP_VERSION env değişkeni varsa kullan, yoksa VERSION dosyasından oku
APP_VERSION="${APP_VERSION:-$(cat VERSION 2>/dev/null || echo 0.0.0)}"

echo "[INFO] Linux build başlıyor (version: ${APP_VERSION})..."

# PyInstaller varlık kontrolü; .venv kurulu ama sistem Python'unda yoksa otomatik geç
if ! "$PYTHON_BIN" -c "import PyInstaller" >/dev/null 2>&1; then
  if [ -x ".venv/bin/python" ] && ".venv/bin/python" -c "import PyInstaller" >/dev/null 2>&1; then
    echo "[INFO] PyInstaller sistem Python'unda bulunamadı; .venv/bin/python kullanılacak"
    PYTHON_BIN=".venv/bin/python"
  else
    echo "[ERROR] PyInstaller modülü bulunamadı. Önce: $PYTHON_BIN -m pip install pyinstaller" >&2
    exit 1
  fi
fi

echo "[INFO] Önceki dist/build artefaktları temizleniyor..."
rm -rf build dist "${APP_NAME}.spec"

# PyInstaller argüman dizisi
PYINSTALLER_ARGS=(
  --noconfirm
  --onedir
  # Linux'ta --windowed KULLANILMAZ:
  #   - GTK3 veya Qt5 sistem bağımlılığı gerektirir; PyInstaller bundle'ına dahil edilemez.
  #   - Bazı minimalist ortamlarda hata üretir.
  # Varsayılan console modu (flag yok) Linux için doğru seçimdir.
  --name "${APP_NAME}"
  # UPX sıkıştırması: CI runner'da kurulu olmayabilir; açıkça devre dışı bırakılıyor.
  --noupx
  --paths src
  # macOS/Windows build'leri ile birebir aynı --add-data eşlemeleri.
  # Linux'ta PyInstaller ayırıcısı ':' (Windows'taki ';'den farklı, macOS ile aynı).
  --add-data "src/web/templates:web/templates"
  --add-data "src/web/static:web/static"
  --add-data "src:src"
  --add-data "styles:styles"
  --add-data "yaml:yaml"
  # macOS/pywebview'a özgü modüller dışlanıyor:
  #   - webview -> ImportError tetiklenir; launcher.py'deki fallback tarayıcı moduna geçer.
  #   - objc, AppKit, Foundation, ... -> macOS Objective-C köprüsü; Linux'ta anlamsız.
  # Bu dışlama hem bundle boyutunu düşürür hem de gereksiz GTK/Qt bağımlılığını önler.
  --exclude-module webview
  --exclude-module objc
  --exclude-module AppKit
  --exclude-module Foundation
  --exclude-module WebKit
  --exclude-module Quartz
  --exclude-module CoreGraphics
  --exclude-module PyObjCTools
  --exclude-module CoreFoundation
)

# AC-7 (nice-to-have): Repo kökünde icon.png varsa --icon parametresi ekle.
# Linux'ta ikon genellikle terminal veya dosya yöneticisinde görünür; işlevsel değil, kozmetiktir.
if [[ -f "icon.png" ]]; then
  echo "[INFO] icon.png bulundu; --icon parametresi ekleniyor."
  PYINSTALLER_ARGS+=(--icon "icon.png")
else
  echo "[INFO] icon.png bulunamadı; ikon eklenmeden paketlenecek."
fi

echo "[INFO] PyInstaller çalıştırılıyor (--onedir, giriş noktası: launcher.py)..."
"$PYTHON_BIN" -m PyInstaller "${PYINSTALLER_ARGS[@]}" launcher.py

# dist/Kube-Sec/ klasörünü tar.gz olarak arşivle (klasör yapısı korunur).
# -C dist: tar'ın kaynak yolları dist/ dizininden çözülür → açıldığında Kube-Sec/ görünür.
# Çıktı dosyası (dist/${TAR_NAME}) CWD'ye göreli; upload-artifact path: dist/Kube-Sec-*.tar.gz ile eşleşir.
TAR_NAME="${APP_NAME}-${APP_VERSION}-linux-x86_64.tar.gz"
TAR_PATH="dist/${TAR_NAME}"
echo "[INFO] Arşiv oluşturuluyor: ${TAR_PATH}"
tar -C dist -czf "${TAR_PATH}" "${APP_NAME}/"

echo "[TAMAM] Linux paketi hazır: $(pwd)/${TAR_PATH}"
