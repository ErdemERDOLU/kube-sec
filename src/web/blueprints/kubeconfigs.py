"""blueprints/kubeconfigs.py — Kubeconfig yönetim route'ları.

Bu blueprint kubeconfig dosyalarını listeleme, ekleme, aktifleştirme ve silme
işlemlerini yönetir. 4 route içerir: GET/POST/DELETE /kubeconfigs ve
POST /kubeconfigs/activate.

Bağımlılık zinciri: kubeconfig_manager <- background <- bu modül <- app.py
"""

import os
import time

from flask import Blueprint, jsonify, redirect, request, session

import web.kubeconfig_manager as _kcm
import web.background as _bg
from web.kubeconfig_manager import (
    KUBECONFIG_ACTIVE_KEY,
    KUBECONFIG_UPLOAD_DIR,
    list_kubeconfigs,
)
from web.background import (
    update_pods_summary_cache,
    update_workload_stats_cache,
    update_pss_cache,
    update_netpol_coverage_cache,
)
from web.audit_log import record_audit_event, _short_session_id

bp_kubeconfigs = Blueprint('kubeconfigs', __name__)


def _sanitize_kubeconfig_name(name: str) -> tuple:
    """Kullanıcıdan gelen kubeconfig dosya adını sanitize eder ve path traversal kontrolü yapar.

    İki aşamalı savunma derinliği (defense in depth):

    1. Karakter filtresi: Yalnızca alfanumerik, tire, alt çizgi ve nokta karakterlerine izin
       verir. Bu filtre ``/`` ve ``\\`` path separator'larını, ``%`` (URL-encode prefix) ile
       diğer özel karakterleri kaldırır.
    2. realpath doğrulaması: Sonuç yolun ``KUBECONFIG_UPLOAD_DIR`` altında kaldığını
       ``os.path.commonpath`` ile doğrular. Bu, ``safe_name`` filtresinin ``..`` (iki ardışık
       nokta) gibi kenar durumlarına karşı ek bir güvenlik katmanı sağlar.

    DRY prensibi — bu fonksiyon hem POST (add) hem DELETE route'larında kullanılır (AC-8).

    :param name: Kullanıcıdan gelen ham dosya adı.
    :returns: ``(safe_name, full_path)`` tuple'ı — her ikisi de güvenli ve doğrulanmış.
    :raises ValueError: Ad sanitize sonrası boş ise veya path traversal tespit edilirse.
        Hata mesajları kasıtlı olarak genel tutulmuştur; sunucu tarafı dosya yolu içermez (AC-10).

    .. note:: Windows'ta ``os.path.realpath`` sembolik bağ çözümlemesi POSIX'ten farklı
              davranabilir ve ``os.chmod`` 0o600/0o700 semantiğini tam desteklemeyebilir.
              Bu fonksiyon POSIX (Linux/macOS) semantiği ile tasarlanmıştır (AC-12).
    """
    # Adım 1 — Karakter filtresi (safe_name): yalnızca alfanumerik, '-', '_', '.' geçer
    safe_name = ''.join([c for c in name if c.isalnum() or c in ('-', '_', '.')])
    if not safe_name:
        raise ValueError("Geçersiz kubeconfig adı")

    # Adım 2 — Path traversal doğrulaması: sonuç yol upload dizini içinde olmalı (AC-2)
    path = os.path.join(KUBECONFIG_UPLOAD_DIR, safe_name)
    real_upload_dir = os.path.realpath(KUBECONFIG_UPLOAD_DIR)
    real_path = os.path.realpath(path)
    try:
        common = os.path.commonpath([real_path, real_upload_dir])
    except ValueError:
        # Windows'ta farklı sürücüler arasında commonpath ValueError fırlatır
        raise ValueError("Dosya adı güvenlik kontrolünden geçemedi")
    if common != real_upload_dir:
        raise ValueError("Dosya adı güvenlik kontrolünden geçemedi")

    return safe_name, path


@bp_kubeconfigs.route('/kubeconfigs', methods=['GET'])
def kubeconfigs_list():
    """Kubeconfig listesini döndür.
    ---
    GET /kubeconfigs
    Returns: {items: [...], active: str|null}
    """
    # Bulgu 2 (backlog #15): Tarayıcıdan doğrudan ziyarette ham JSON (disk yolları)
    # açığa çıkmasını önlemek için Accept header kontrolü yapılır.
    # AJAX/fetch çağrıları Accept: application/json gönderir → JSON yanıt korunur.
    # Tarayıcı doğrudan ziyareti (Accept: text/html...) → /configuration'a redirect.
    if 'application/json' not in request.headers.get('Accept', ''):
        return redirect('/configuration')
    active = session.get(KUBECONFIG_ACTIVE_KEY)
    return jsonify({'items': list_kubeconfigs(), 'active': active})


@bp_kubeconfigs.route('/kubeconfigs', methods=['POST'])
def kubeconfigs_add():
    """Yeni kubeconfig ekle (diske kaydet).
    ---
    POST /kubeconfigs
    Body: {name: str, content: str (raw YAML)}
    Returns: {ok: true, name: str} veya {error: str}
    """
    try:
        data = request.get_json(force=True) or {}
        name = data.get('name')
        content = data.get('content')  # raw kubeconfig YAML
        if not name or not content:
            return jsonify({'error': 'name ve content zorunlu'}), 400
        # AC-8/AC-11: DRY yardımcı fonksiyon; POST route'unda da realpath doğrulaması yapılır.
        # Boş safe_name durumunda (tüm karakterler filtrelendi) zaman damgalı ad üretilir (UX uyumluluğu).
        # Realpath güvenlik hatası durumunda ise 400 döndürülür (path traversal girişimi).
        try:
            safe_name, path = _sanitize_kubeconfig_name(name)
        except ValueError as _ve:
            if not ''.join([c for c in name if c.isalnum() or c in ('-', '_', '.')]):
                # Tüm karakterler filtrelendi → zaman damgalı fallback ad kullan
                safe_name = f'cfg_{int(time.time())}'
                path = os.path.join(KUBECONFIG_UPLOAD_DIR, safe_name)
            else:
                # Realpath doğrulaması başarısız → güvenlik reddi
                return jsonify({'error': 'Geçersiz kubeconfig adı'}), 400
        with open(path, 'w') as f:
            f.write(content)
        # AC-3: Kubeconfig dosyası yalnızca süreç sahibi tarafından okunabilir/yazılabilir olmalı.
        # Windows notu (AC-12): Windows'ta 0o600 POSIX semantiği tam uygulanmayabilir.
        os.chmod(path, 0o600)
        record_audit_event(
            action='add',
            resource_type='Kubeconfig',
            resource_name=safe_name,
            namespace=None,
            session_id=_short_session_id(request.cookies.get('session')),
            details=f'filename={safe_name}',
        )
        return jsonify({'ok': True, 'name': safe_name})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp_kubeconfigs.route('/kubeconfigs/activate', methods=['POST'])
def kubeconfigs_activate():
    """Aktif kubeconfig'i değiştir ve tüm cache'leri tazele.
    ---
    POST /kubeconfigs/activate
    Body: {name: str}
    Returns: {ok: true, active: str} | {error: str}
    Modül referansı (_kcm) ile KUBECONFIG_ACTIVE_GLOBAL güncellenir (stale-reference bug'ından kaçınmak için).
    """
    try:
        data = request.get_json(force=True) or {}
        name = data.get('name')
        if not name:
            return jsonify({'error': 'name zorunlu'}), 400
        lst = list_kubeconfigs()
        if not any(i['name'] == name for i in lst):
            return jsonify({'error': 'bulunamadı'}), 404
        session[KUBECONFIG_ACTIVE_KEY] = name
        # Modül referansıyla güncelle; from ... import ile alınan kopya değil gerçek modül değişkeni.
        # Aynı kilit bloğunda aktivasyon sayacını ve zaman damgasını da güncelle (thread-safe).
        with _kcm._KUBECONFIG_LOCK:
            _kcm.KUBECONFIG_ACTIVE_GLOBAL = name
            _kcm._KUBECONFIG_ACTIVATION_VERSION += 1
            _kcm._KUBECONFIG_ACTIVATION_TS = time.time()
        # Yeni cluster için ardışık hata sayaçlarını sıfırla (spec R-3):
        # önceki cluster'ın hataları yeni cluster'a taşınmamalı.
        _bg._wsc_consecutive_errors = 0
        _bg._psc_consecutive_errors = 0
        _bg._msl_consecutive_errors = 0
        _bg._pss_consecutive_errors = 0
        _bg._npc_consecutive_errors = 0
        # Aktifleştirme sonrası cache'leri yeni kubeconfig ile tazele (hata yutsa da sorun yok)
        try:
            update_pods_summary_cache()
        except Exception:
            pass
        try:
            update_workload_stats_cache()
        except Exception:
            pass
        try:
            update_pss_cache()
        except Exception:
            pass
        try:
            update_netpol_coverage_cache()
        except Exception:
            pass
        record_audit_event(
            action='activate',
            resource_type='Kubeconfig',
            resource_name=name,
            namespace=None,
            session_id=_short_session_id(request.cookies.get('session')),
            details=f'name={name}',
        )
        return jsonify({'ok': True, 'active': name})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp_kubeconfigs.route('/kubeconfigs/active-info', methods=['GET'])
def kubeconfigs_active_info():
    """Aktif kubeconfig bilgilerini cluster API çağrısı yapmadan döndür.

    Cluster bağlantısı kurulmaz; yalnızca bellekteki değerler okunur.
    Bu endpoint milisaniyeler içinde yanıt verir ve frontend polling için kullanılır.

    ---
    GET /kubeconfigs/active-info
    Returns:
        200: {name: str|null, version: int, activated_at: float}
            name        — KUBECONFIG_ACTIVE_GLOBAL değeri (seçili kubeconfig adı, yoksa null)
            version     — Şimdiye kadar gerçekleşen aktivasyon sayısı (0'dan başlar)
            activated_at — Son aktivasyonun Unix epoch zamanı (ilk aktivasyondan önce 0.0)
    """
    with _kcm._KUBECONFIG_LOCK:
        name = _kcm.KUBECONFIG_ACTIVE_GLOBAL
        version = _kcm._KUBECONFIG_ACTIVATION_VERSION
        activated_at = _kcm._KUBECONFIG_ACTIVATION_TS
    return jsonify({
        'name': name,
        'version': version,
        'activated_at': activated_at,
    })


@bp_kubeconfigs.route('/kubeconfigs', methods=['DELETE'])
def kubeconfigs_delete():
    """Kubeconfig dosyasını sil.
    ---
    DELETE /kubeconfigs
    Body: {name: str}
    Returns: {ok: true} | {error: str}
    """
    try:
        data = request.get_json(force=True) or {}
        name = data.get('name') or ''
        if not name:
            return jsonify({'error': 'name zorunlu'}), 400
        # AC-1/AC-2/AC-7: safe_name filtresi + realpath doğrulaması — path traversal koruması.
        # Ham 'name' değeri doğrudan os.path.join/os.remove'a geçirilmez.
        # AC-10: Hata mesajı sunucu dosya sistemi yolunu içermez.
        try:
            safe_name, path = _sanitize_kubeconfig_name(name)
        except ValueError:
            return jsonify({'error': 'Geçersiz kubeconfig adı'}), 400
        if os.path.exists(path):
            os.remove(path)
            if session.get(KUBECONFIG_ACTIVE_KEY) == safe_name:
                session.pop(KUBECONFIG_ACTIVE_KEY, None)
                # Modül referansıyla güncelle
                with _kcm._KUBECONFIG_LOCK:
                    if _kcm.KUBECONFIG_ACTIVE_GLOBAL == safe_name:
                        _kcm.KUBECONFIG_ACTIVE_GLOBAL = None
            # AC-9: Audit log'a sanitize edilmiş ad yazılır (ham 'name' değil; log injection önlemi).
            record_audit_event(
                action='delete',
                resource_type='Kubeconfig',
                resource_name=safe_name,
                namespace=None,
                session_id=_short_session_id(request.cookies.get('session')),
            )
            return jsonify({'ok': True})
        return jsonify({'error': 'bulunamadı'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500
