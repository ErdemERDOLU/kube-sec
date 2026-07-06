#!/usr/bin/env python3
"""macOS masaüstü başlatıcısı.

PyInstaller ile .app içinde paketlendiğinde:
 - src dizinini sys.path'e ekler
 - Flask uygulamasını uygun template/static yollarıyla başlatır
 - Port 8080 doluysa otomatik bir sonraki boş portu bulur
 - İlk açılışta varsayılan tarayıcıyı açar (devre dışı bırakmak için NO_AUTO_BROWSER=1)
 - USE_PYWEBVIEW=1 ile native pywebview penceresi açılır (tarayıcı yerine)
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

def _run_flask_server(host: str, port: int, debug: bool):
    """Flask sunucusunu çalıştır. pywebview modunda ayrı thread'den çağrılır."""
    app.run(host=host, port=port, debug=debug, use_reloader=False)

def _wait_for_server(host: str, port: int, timeout: float = 5.0):
    """Flask sunucusunun hazır olmasını bekle."""
    import socket as _socket
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with _socket.create_connection((host, port), timeout=0.3):
                return
        except OSError:
            time.sleep(0.1)

def _start_with_pywebview(url: str, host: str, port: int, debug: bool):
    """pywebview ile native pencere aç. Ana thread'i bloklar (pywebview gereksinimi)."""
    import webview  # lazy import -- sadece bu dalda gerekli

    # Flask'i daemon thread'de başlat
    server_thread = threading.Thread(
        target=_run_flask_server,
        args=(host, port, debug),
        daemon=True
    )
    server_thread.start()

    # Flask'in ayağa kalkmasını bekle (port açılana kadar, maks ~5sn)
    _wait_for_server(host, port, timeout=5.0)

    # Native pencere oluştur
    window = webview.create_window('Kube-Sec', url)

    def _on_closed():
        """Pencere kapanınca process'i sonlandır."""
        os._exit(0)

    window.events.closed += _on_closed

    # pywebview ana döngüsü -- bu satır pencere kapanana kadar bloklar
    webview.start()

def main():
    port = int(os.environ.get('APP_PORT', find_port(8080)))
    host = '127.0.0.1'
    url = f"http://{host}:{port}"
    debug = not getattr(sys, 'frozen', False)

    use_pywebview = os.environ.get('USE_PYWEBVIEW', '').strip() == '1'

    if use_pywebview:
        _start_with_pywebview(url, host, port, debug)
    else:
        # Eski davranış -- AYNEN KORUNUYOR
        if getattr(sys, 'frozen', False):
            threading.Thread(target=_open_browser, args=(url,), daemon=True).start()
        app.run(host=host, port=port, debug=debug)

if __name__ == '__main__':
    main()
