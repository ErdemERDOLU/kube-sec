#!/usr/bin/env bash
# Wrapper to run the PowerShell build script from bash/WSL.
# If pwsh is available this execs the PS script; otherwise it prints install instructions.

set -euo pipefail

if ! command -v pwsh >/dev/null 2>&1; then
  cat <<'EOF'
Error: pwsh (PowerShell Core) not found in PATH.
To build the Windows exe you have two simple options:

1) Install PowerShell (recommended on WSL / Ubuntu):

   DISTRO=$(lsb_release -rs)
   wget -q https://packages.microsoft.com/config/ubuntu/${DISTRO}/packages-microsoft-prod.deb
   sudo dpkg -i packages-microsoft-prod.deb
   sudo apt update
   sudo apt install -y powershell

   Then run:
     pwsh ./build-windows.ps1

2) Use GitHub Actions (Windows runner):
   - Push your changes or open the Actions tab and run the "Build Windows EXE" workflow (workflow_dispatch).

If you prefer to run PyInstaller directly from bash (not guaranteed to produce a Windows EXE), you can run:

  python -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt pyinstaller
  pyinstaller --onefile --add-data "src/web/templates:templates" --add-data "src/web/static:static" --add-data "public:public" src/main.py

EOF
  exit 1
fi

# Exec PowerShell build script (forward arguments)
exec pwsh ./build-windows.ps1 "$@"
