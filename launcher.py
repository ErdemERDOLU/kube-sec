#!/usr/bin/env python3
"""macOS masaüstü başlatıcısı.

PyInstaller ile .app içinde paketlendiğinde:
 - src dizinini sys.path'e ekler
 - Flask uygulamasını uygun template/static yollarıyla başlatır
 - Port 8080 doluysa otomatik bir sonraki boş portu bulur
 - İlk açılışta varsayılan tarayıcıyı açar (devre dışı bırakmak için NO_AUTO_BROWSER=1)
"""
from __future__ import annotations
import os, sys, socket, time, threading, webbrowser

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
SRC_DIR = os.path.join(BASE_DIR, 'src')
# PyInstaller bundle içinde _MEIPASS altında olabilir
if getattr(sys, 'frozen', False):
    bundle_base = getattr(sys, '_MEIPASS', BASE_DIR)  # type: ignore[attr-defined]
    cand1 = os.path.join(bundle_base, 'src')
    if os.path.isdir(cand1) and cand1 not in sys.path:
        sys.path.insert(0, cand1)
if os.path.isdir(SRC_DIR) and SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

def find_port(preferred: int = 8080) -> int:
    def _is_free(p: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            return s.connect_ex(('127.0.0.1', p)) != 0
    if _is_free(preferred):
        return preferred
    for p in range(preferred+1, preferred+30):
        if _is_free(p):
            return p
    return preferred  # son çare

from web.app import app  # noqa: E402

def _open_browser(url: str):
    if os.environ.get('NO_AUTO_BROWSER') == '1':
        return
    # küçük gecikme: server ayağa kalksın
    time.sleep(1.2)
    try:
        webbrowser.open(url)
    except Exception:
        pass

def main():
    port = int(os.environ.get('APP_PORT', find_port(8080)))
    url = f"http://127.0.0.1:{port}"
    if getattr(sys, 'frozen', False):
        threading.Thread(target=_open_browser, args=(url,), daemon=True).start()
    debug = not getattr(sys, 'frozen', False)
    app.run(host='127.0.0.1', port=port, debug=debug)

if __name__ == '__main__':
    main()
