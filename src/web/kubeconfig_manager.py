"""kubeconfig_manager.py — Kubeconfig global state ve yardımcı fonksiyonlar.

Bu modül Flask'a bağımlı değildir (session erişimi try/except ile korunmuştur).
Import zinciri:  kubeconfig_manager  <-  background.py  <-  blueprint'ler  <-  app.py
"""

import os
import sys
from threading import Lock as _Lock

from kubernetes import config

# ---- Kubeconfig Manager (in-memory + optional directory) ----
KUBECONFIG_STORE = {}
KUBECONFIG_ACTIVE_KEY = 'active_kubeconfig'
KUBECONFIG_UPLOAD_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'kubeconfigs')
os.makedirs(KUBECONFIG_UPLOAD_DIR, exist_ok=True)

# Global (thread-safe) aktif kubeconfig adı; arka plan thread'leri session'a erişemezse bunu kullanır
KUBECONFIG_ACTIVE_GLOBAL = None  # Seçilen kubeconfig adı
KUBECONFIG_LAST_PATH = None      # Son başarılı yüklenen kubeconfig dosya yolu
_KUBECONFIG_LOCK = _Lock()


def list_kubeconfigs():
    result = []
    # in-memory
    for name, path in KUBECONFIG_STORE.items():
        result.append({'name': name, 'path': path, 'source': 'memory'})
    # directory (files ending with .yaml or .yml or no ext)
    try:
        for fn in os.listdir(KUBECONFIG_UPLOAD_DIR):
            fp = os.path.join(KUBECONFIG_UPLOAD_DIR, fn)
            if os.path.isfile(fp):
                result.append({'name': fn, 'path': fp, 'source': 'disk'})
    except Exception:
        pass
    # deduplicate by name (memory overrides)
    dedup = {}
    for r in result:
        dedup[r['name']] = r
    return list(dedup.values())


def get_active_kubeconfig_path():
    """Aktif kubeconfig dosya yolunu döndür.
    Öncelik: (varsa) request session -> global değişken -> env KUBECONFIG -> None.
    Arka plan thread'lerinde session erişimi RuntimeError verdiği için güvenli try/except kullanılır.
    """
    global KUBECONFIG_ACTIVE_GLOBAL, KUBECONFIG_LAST_PATH
    active_name = None
    try:
        # flask import'u burada yapılır: circular import'tan kaçınmak için lazy import
        from flask import session
        # request context varsa session'dan al
        active_name = session.get(KUBECONFIG_ACTIVE_KEY)
        if active_name is not None:
            # aynı zamanda global'i güncel tut (yarış koşulu önemli değil; kilit ile koruyalım)
            with _KUBECONFIG_LOCK:
                KUBECONFIG_ACTIVE_GLOBAL = active_name
    except Exception:
        # request context yok; global'i kullan
        active_name = KUBECONFIG_ACTIVE_GLOBAL
    # Eğer hâlâ yoksa ve sistemde yalnızca tek kubeconfig dosyası varsa onu otomatik seç
    if not active_name:
        lst_single = list_kubeconfigs()
        if len(lst_single) == 1:
            active_name = lst_single[0]['name']
            with _KUBECONFIG_LOCK:
                KUBECONFIG_ACTIVE_GLOBAL = active_name
    if active_name:
        lst = list_kubeconfigs()
        for item in lst:
            if item['name'] == active_name:
                return item['path']
    # Son başarılı çalışmış konfig yolu varsa ve dosya mevcutsa onu dön (fallback)
    if KUBECONFIG_LAST_PATH and os.path.exists(KUBECONFIG_LAST_PATH):
        return KUBECONFIG_LAST_PATH
    env_path = os.environ.get('KUBECONFIG')
    if env_path and os.path.exists(env_path):
        return env_path
    return None


def load_kube_config_active():
    path = get_active_kubeconfig_path()
    if path:
        config.load_kube_config(config_file=path)
        # Başarılı yolu kaydet
        global KUBECONFIG_LAST_PATH
        with _KUBECONFIG_LOCK:
            KUBECONFIG_LAST_PATH = path
    else:
        # Fallback: session'da aktif yoksa normal kubeconfig yükle
        config.load_kube_config()
    try:
        # Debug amaçlı (isteğe bağlı: prod'da kaldırılabilir)
        print(f"[load_kube_config_active] aktif kubeconfig: {path or 'DEFAULT'}", file=sys.stderr)
    except Exception:
        pass
