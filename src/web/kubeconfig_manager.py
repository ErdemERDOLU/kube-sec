"""kubeconfig_manager.py — Kubeconfig global state ve yardımcı fonksiyonlar.

Bu modül Flask'a bağımlı değildir (session erişimi try/except ile korunmuştur).
Import zinciri:  kubeconfig_manager  <-  background.py  <-  blueprint'ler  <-  app.py
"""

import os
import sys
from threading import Lock as _Lock

from kubernetes import client, config

# ---- Kubeconfig Manager (in-memory + optional directory) ----
KUBECONFIG_STORE = {}
KUBECONFIG_ACTIVE_KEY = 'active_kubeconfig'
KUBECONFIG_UPLOAD_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'kubeconfigs')
os.makedirs(KUBECONFIG_UPLOAD_DIR, exist_ok=True)

# Global (thread-safe) aktif kubeconfig adı; arka plan thread'leri session'a erişemezse bunu kullanır
KUBECONFIG_ACTIVE_GLOBAL = None  # Seçilen kubeconfig adı
KUBECONFIG_LAST_PATH = None      # Son başarılı yüklenen kubeconfig dosya yolu
_KUBECONFIG_LOCK = _Lock()

# Aktivasyon sayacı: her kubeconfig değişiminde 1 artar; frontend bunu polling ile izler.
# _KUBECONFIG_LOCK ile korunur.
_KUBECONFIG_ACTIVATION_VERSION: int = 0   # Her aktivasyonda 1 artar
_KUBECONFIG_ACTIVATION_TS: float = 0.0    # Son aktivasyon zamanı (Unix epoch, time.time())


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


def configure_kube_client():
    """Aktif kubeconfig'i yükler ve K8s client SSL/hostname konfigürasyonunu ayarlar.

    1. load_kube_config_active() çağrılır (session -> global -> env -> fallback).
    2. verify_ssl ve assert_hostname ayarları ortam değişkenine göre set edilir.
    3. client.Configuration.set_default() ile varsayılan konfigürasyona atanır.

    Ortam değişkeni: KUBESEC_VERIFY_SSL
      - Ayarlanmadıysa veya boş string ise: verify_ssl = False (mevcut davranış korunur)
      - "1", "true", "yes", "on" (büyük/küçük harf farkız): verify_ssl = True
      - Diğer tüm değerler: verify_ssl = False

    Not: assert_hostname değeri verify_ssl ile aynı değer alır — SSL doğrulama
    açıksa hostname doğrulama da açık olmalıdır; tersi durumda da kapalı olmalıdır.

    :raises: Exception — kubeconfig yüklenemezse (load_kube_config_active hatası)
    """
    load_kube_config_active()
    c = client.Configuration.get_default_copy()
    _raw = os.environ.get('KUBESEC_VERIFY_SSL', '')
    _verify = _raw.strip().lower() in ('1', 'true', 'yes', 'on')
    c.verify_ssl = _verify
    c.assert_hostname = _verify
    client.Configuration.set_default(c)
