"""version_check.py — Güncelleme kontrolü modülü (AC-5).

GitHub Releases API üzerinden yeni sürüm kontrolü yapar.
TÜM hata durumlarında (ağ hatası, 404, rate limit, parse) sessizce
``{"update_available": false, "error": null}`` döner; asla exception fırlatmaz.
Sonuç 1 saat boyunca bellekte cache'lenir.

Ortam değişkenleri:
    KUBESEC_UPDATE_CHECK_URL  : Sorgulanacak URL (varsayılan: GitHub Releases API)
    KUBESEC_DISABLE_UPDATE_CHECK : "1" / "true" / "yes" ise kontrol tamamen atlanır (AC-9)
"""

import os
import sys
import time
from typing import Optional

import requests

# Mevcut uygulama sürümü
try:
    from version import __version__ as _CURRENT_VERSION
except Exception:
    _CURRENT_VERSION = '0.0.0'

# Ortam değişkeni konfigürasyonu (AC-7)
UPDATE_CHECK_URL: str = os.environ.get(
    'KUBESEC_UPDATE_CHECK_URL',
    'https://api.github.com/repos/ErdemERDOLU/kube-sec/releases/latest',
)

DISABLE_UPDATE_CHECK: bool = os.environ.get(
    'KUBESEC_DISABLE_UPDATE_CHECK', ''
).strip().lower() in ('1', 'true', 'yes')

VERSION_CACHE_TTL: int = 3600  # 1 saat

# Bellek cache (tek süreç içinde paylaşılır)
_version_cache: Optional[dict] = None
_version_cache_time: float = 0.0


def _parse_version(v: str) -> tuple:
    """Basit semver tuple parse eder.

    ``'v1.2.3'`` veya ``'1.2.3'`` -> ``(1, 2, 3)``.
    Pre-release etiketleri atlanır (stable-only karşılaştırma).

    :param v: Sürüm dizesi.
    :returns: Tamsayı tuple'ı.
    """
    v = v.lstrip('v').strip()
    # Pre-release / build metadata kısımlarını at
    v = v.split('-')[0].split('+')[0]
    parts = v.split('.')
    result = []
    for p in parts:
        try:
            result.append(int(p))
        except ValueError:
            result.append(0)
    # En az 3 bileşenli olmasını garantile
    while len(result) < 3:
        result.append(0)
    return tuple(result)


def check_latest_version() -> dict:
    """GitHub Releases API'den en son sürümü sorgular (AC-5).

    Tüm hata durumlarında (ağ hatası, 404 — henüz release yok, rate limit,
    parse hatası) sessizce ``{"update_available": false, "error": null}`` döner.
    Asla exception fırlatmaz ve asla 500 üretmez.

    :returns: Sürüm kontrol sonucu dict'i.
    """
    if DISABLE_UPDATE_CHECK:
        return {'update_available': False, 'disabled': True}

    try:
        resp = requests.get(
            UPDATE_CHECK_URL,
            timeout=5,
            headers={
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': 'kube-sec-version-check/1.0',
            },
        )
        if resp.status_code == 404:
            # Henüz hiç release yayınlanmamış — sessizce başarısız (doğrulanmış senaryo)
            return {'update_available': False, 'error': None}
        if resp.status_code != 200:
            # 403 (rate limit), 5xx vb. — sessizce başarısız
            return {'update_available': False, 'error': None}

        data = resp.json()
        latest_tag = (data.get('tag_name') or '').strip()
        release_url = (data.get('html_url') or '').strip()

        if not latest_tag:
            return {'update_available': False, 'error': None}

        current_tuple = _parse_version(_CURRENT_VERSION)
        latest_tuple = _parse_version(latest_tag)
        update_available = latest_tuple > current_tuple

        return {
            'update_available': update_available,
            'current_version': _CURRENT_VERSION,
            'latest_version': latest_tag.lstrip('v'),
            'release_url': release_url,
            'error': None,
        }
    except Exception:
        # Ağ hatası, JSON parse hatası, timeout vb. — sessizce başarısız
        return {'update_available': False, 'error': None}


def get_cached_version_info() -> dict:
    """Cache'den sürüm bilgisini döner; TTL dolmuşsa GitHub API'yi yeniden sorgular.

    Uygulama oturumu boyunca tekrarlanan istekler GitHub API'yi tekrar çağırmaz
    (TTL: 1 saat).

    :returns: Sürüm kontrol sonucu dict'i.
    """
    global _version_cache, _version_cache_time

    if DISABLE_UPDATE_CHECK:
        return {'update_available': False, 'disabled': True}

    now = time.time()
    if _version_cache is not None and (now - _version_cache_time) < VERSION_CACHE_TTL:
        return _version_cache

    result = check_latest_version()
    _version_cache = result
    _version_cache_time = now
    return result
