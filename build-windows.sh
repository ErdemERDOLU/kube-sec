#!/usr/bin/env bash
# Bash'den PowerShell build betiğini çalıştırmak için sarmalayıcı.
# pwsh mevcutsa PS betiğini yürütür; yoksa kurulum talimatlarını yazdırır.

set -euo pipefail

if ! command -v pwsh >/dev/null 2>&1; then
  cat <<'EOF'
Hata: pwsh (PowerShell Core) PATH'te bulunamadı.
Windows exe'sini derlemek için iki seçenek mevcuttur:

1) PowerShell'i kur (WSL / Ubuntu için önerilen yol):

   DISTRO=$(lsb_release -rs)
   wget -q https://packages.microsoft.com/config/ubuntu/${DISTRO}/packages-microsoft-prod.deb
   sudo dpkg -i packages-microsoft-prod.deb
   sudo apt update
   sudo apt install -y powershell

   Ardından çalıştır:
     pwsh ./build-windows.ps1

2) Doğrudan Makefile hedefini kullan (pwsh kuruluysa):
     make build-windows

Eğer PyInstaller'ı doğrudan bash'den çalıştırmak istiyorsanız (Windows EXE
üretimi garanti değildir — gerçek Windows ortamında çalıştırın):

  python -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt pyinstaller
  pyinstaller --onedir --windowed --name Kube-Sec \
    --paths src \
    --hidden-import webview \
    --hidden-import webview.util \
    --hidden-import webview.platforms.edgechromium \
    --hidden-import webview.platforms.mshtml \
    --add-data "src/web/templates:web/templates" \
    --add-data "src/web/static:web/static" \
    --add-data "src:src" \
    --add-data "styles:styles" \
    --add-data "yaml:yaml" \
    --icon icon.ico \
    launcher.py

NOT: PyInstaller cross-compile desteklemez. Bu komut macOS/Linux'ta
çalıştırılırsa macOS/Linux çıktısı üretir, Windows .exe üretmez.
Windows .exe için gerçek bir Windows ortamı (veya Windows runner) gereklidir.

EOF
  exit 1
fi

# PowerShell build betiğini yürüt (argümanları aktar)
exec pwsh ./build-windows.ps1 "$@"
