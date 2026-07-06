"""blueprints/kubeconfigs.py — Kubeconfig yönetim route'ları.

Bu blueprint kubeconfig dosyalarını listeleme, ekleme, aktifleştirme ve silme
işlemlerini yönetir. 4 route içerir: GET/POST/DELETE /kubeconfigs ve
POST /kubeconfigs/activate.

Bağımlılık zinciri: kubeconfig_manager <- background <- bu modül <- app.py
"""

import os
import time

from flask import Blueprint, jsonify, request, session

import web.kubeconfig_manager as _kcm
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

bp_kubeconfigs = Blueprint('kubeconfigs', __name__)


@bp_kubeconfigs.route('/kubeconfigs', methods=['GET'])
def kubeconfigs_list():
    """Kubeconfig listesini döndür.
    ---
    GET /kubeconfigs
    Returns: {items: [...], active: str|null}
    """
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
        safe_name = ''.join([c for c in name if c.isalnum() or c in ('-', '_', '.')]) or f'cfg_{int(time.time())}'
        path = os.path.join(KUBECONFIG_UPLOAD_DIR, safe_name)
        with open(path, 'w') as f:
            f.write(content)
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
        # Modül referansıyla güncelle; from ... import ile alınan kopya değil gerçek modül değişkeni
        with _kcm._KUBECONFIG_LOCK:
            _kcm.KUBECONFIG_ACTIVE_GLOBAL = name
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
        return jsonify({'ok': True, 'active': name})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


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
        name = data.get('name')
        if not name:
            return jsonify({'error': 'name zorunlu'}), 400
        path = os.path.join(KUBECONFIG_UPLOAD_DIR, name)
        if os.path.exists(path):
            os.remove(path)
            if session.get(KUBECONFIG_ACTIVE_KEY) == name:
                session.pop(KUBECONFIG_ACTIVE_KEY, None)
                # Modül referansıyla güncelle
                with _kcm._KUBECONFIG_LOCK:
                    if _kcm.KUBECONFIG_ACTIVE_GLOBAL == name:
                        _kcm.KUBECONFIG_ACTIVE_GLOBAL = None
            return jsonify({'ok': True})
        return jsonify({'error': 'bulunamadı'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500
