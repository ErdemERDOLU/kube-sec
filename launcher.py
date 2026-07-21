#!/usr/bin/env python3
"""Masaüstü başlatıcısı (macOS/Windows).

PyInstaller ile paketlendiğinde:
 - src dizinini sys.path'e ekler
 - Flask uygulamasını uygun template/static yollarıyla başlatır
 - Port 8080 doluysa otomatik bir sonraki boş portu bulur
 - İlk açılışta varsayılan tarayıcıyı açar (devre dışı bırakmak için NO_AUTO_BROWSER=1)
 - Paketlenmiş modda (frozen) varsayılan olarak native pywebview penceresi açılır
 - USE_PYWEBVIEW=0 ile tarayıcı moduna dönülebilir; geliştirme modunda varsayılan tarayıcıdır
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

class CsvExportApi:
    """pywebview js_api köprüsü: JavaScript'ten CSV dosyası kaydetmek için kullanılır.

    JS erişim noktası: ``window.pywebview.api.save_csv(filename, csvContent)``

    Dönüş sözleşmesi (JS tarafı bu dict'i Promise olarak alır):

    - ``{"success": True, "path": str}``  -- dosya başarıyla yazıldı
    - ``{"cancelled": True}``             -- kullanıcı native diyaloğu iptal etti
    - ``{"error": str}``                  -- yazma veya diyalog hatası; exception asla üste fırlatılmaz
    """

    def __init__(self) -> None:
        # _start_with_pywebview tarafından create_window'dan sonra atanır
        self._window = None

    def save_csv(self, filename: str, csv_content: str) -> dict:
        """Native 'Farklı Kaydet' diyaloğu açar ve CSV içeriğini seçilen yola yazar.

        Args:
            filename:    Varsayılan dosya adı (örn. 'nodes.csv').
            csv_content: Yazılacak CSV içeriği. BOM (``\\xEF\\xBB\\xBF``) çağıran
                         tarafça eklenmiş olmalıdır; bu metod ekstra BOM eklemez.

        Returns:
            dict: ``{"success": True, "path": str}`` | ``{"cancelled": True}`` | ``{"error": str}``
        """
        import webview as _webview  # modül bu noktada zaten yüklü; lazy referans

        try:
            result = self._window.create_file_dialog(
                _webview.SAVE_DIALOG,
                save_filename=filename,
                file_types=('CSV Dosyaları (*.csv)', 'Tüm Dosyalar (*.*)')
            )
            # pywebview sürümüne göre None veya boş tuple/liste dönebilir (iptal durumu)
            if not result:
                return {"cancelled": True}
            # SAVE_DIALOG genellikle tek elemanlı tuple döner
            path = result[0] if isinstance(result, (tuple, list)) else str(result)
            if not path:
                return {"cancelled": True}
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write(csv_content)
            return {"success": True, "path": path}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}


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

    # js_api köprüsü: JavaScript'e window.pywebview.api.save_csv() erişimi sağlar
    api = CsvExportApi()

    # Native pencere oluştur; js_api parametresiyle API köprüsünü create_window'a geçir
    window = webview.create_window('Kube-Sec', url, js_api=api)

    # API'ye pencere referansını ver -- create_file_dialog bu referans üzerinden çağrılır
    api._window = window

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

    use_pywebview = os.environ.get('USE_PYWEBVIEW', '1' if getattr(sys, 'frozen', False) else '0').strip() == '1'

    if use_pywebview:
        try:
            _start_with_pywebview(url, host, port, debug)
        except ImportError:
            # pywebview bundle'a dahil edilmemiş (ör. EXCLUDE_PYWEBVIEW=1 ile derlendi)
            # ya da USE_PYWEBVIEW=1 set edilmiş ama webview kurulu değil.
            # Uygulama çökmemeli; eski tarayıcı-açma moduna otomatik olarak dönülüyor.
            print("[UYARI] pywebview modülü bulunamadı; tarayıcı moduna dönülüyor.")
            if getattr(sys, 'frozen', False):
                threading.Thread(target=_open_browser, args=(url,), daemon=True).start()
            app.run(host=host, port=port, debug=debug)
    else:
        # Eski davranış -- AYNEN KORUNUYOR
        if getattr(sys, 'frozen', False):
            threading.Thread(target=_open_browser, args=(url,), daemon=True).start()
        app.run(host=host, port=port, debug=debug)

if __name__ == '__main__':
    main()
