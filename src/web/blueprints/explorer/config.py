"""explorer/config.py — Konfigürasyon kaynak route'ları.

İçerik: configmaps-summary, configmap, update-configmap,
secrets-summary, secret, update-secret, delete-secret,
resource-quotas-summary, limit-ranges-summary,
delete-resource-quota, delete-limit-range.
"""

import json
import time
import traceback

from flask import jsonify, request
from kubernetes import client
from kubernetes.client.rest import ApiException

from web.kubeconfig_manager import configure_kube_client
from web.audit_log import record_audit_event, _short_session_id
from web.confirmation import require_confirm_name

from web.blueprints.explorer import bp_explorer
from web.blueprints.explorer._pagination import paginate_list


@bp_explorer.route('/k8s-explorer/configmaps-summary')
def configmaps_summary():
    """ConfigMap listesini döndürür.

    Query parametreleri:
        namespace (str, opsiyonel): Belirtilirse yalnızca o namespace filtrelenir
                                    ('all' veya parametre yoksa tüm namespace'ler).
                                    Mevcut filtre korunur — AC-8.
        page      (int, opsiyonel): Sayfa numarası (1-tabanlı). Gönderilmezse
                                    tüm liste eski formatta döner (geriye dönük uyumluluk).
        per_page  (int, opsiyonel): Sayfa başına kayıt (varsayılan: 50, max: 500).

    Not: Namespace filtresi önce uygulanır, sayfalama sonra gelir (AC-8).

    Yanıt (sayfalama KAPALI — page parametresi yok):
        {"configmaps": [...]}

    Yanıt (sayfalama AÇIK — page parametresi var):
        {"items": [...], "page": N, "per_page": M, "total": T, "total_pages": P}

    Hatalar:
        400: Geçersiz sayfalama parametresi.
    """
    try:
        configure_kube_client()
        v1 = client.CoreV1Api()
        # Mevcut namespace filtresi korunur — AC-8 (önce filtrele, sonra dilimle)
        namespace = request.args.get('namespace')
        if namespace and namespace != 'all':
            configmaps = v1.list_namespaced_config_map(namespace).items
        else:
            configmaps = v1.list_config_map_for_all_namespaces().items
        result = []
        for cm in configmaps:
            data_count = len(cm.data) if cm.data else 0
            creation_timestamp = getattr(cm.metadata, 'creation_timestamp', None)
            result.append({
                'namespace': cm.metadata.namespace,
                'name': cm.metadata.name,
                'data_count': data_count,
                'creation_timestamp': creation_timestamp.isoformat() if creation_timestamp else None
            })
        # Sayfalama desteği — AC-1 (sayfalama), AC-2 (geriye dönük uyumluluk), AC-7 (doğrulama)
        try:
            paginated, is_paginated = paginate_list(result, request.args)
        except ValueError as ve:
            return jsonify({'error': str(ve)}), 400
        if is_paginated:
            return jsonify(paginated)
        # page parametresi yoksa eski format (geriye dönük uyumluluk — loadOverviewData() etkilenmez)
        return jsonify({'configmaps': result})
    except Exception as e:
        return jsonify({'configmaps': [], 'error': str(e)})


@bp_explorer.route('/k8s-explorer/configmap')
def get_configmap():
    name = request.args.get('name')
    namespace = request.args.get('namespace')
    if not name or not namespace:
        return jsonify({'error': 'name and namespace required'}), 400
    try:
        configure_kube_client()
        v1 = client.CoreV1Api()
        cm = v1.read_namespaced_config_map(name, namespace)
        data = getattr(cm, 'data', {}) or {}
        return jsonify({'configmap': {'namespace': namespace, 'name': name, 'data': data}})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp_explorer.route('/k8s-explorer/update-configmap', methods=['POST'])
def update_configmap():
    try:
        payload = request.get_json() or {}
        name = payload.get('name')
        namespace = payload.get('namespace')
        data = payload.get('data')
        if not name or not namespace or data is None:
            return jsonify({'error': 'name, namespace and data are required'}), 400
        configure_kube_client()
        v1 = client.CoreV1Api()
        # fetch existing, replace data and update resource so deletions are persisted
        # Try replace with retry on 409 Conflict
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                cm = v1.read_namespaced_config_map(name, namespace)
                cm.data = data if isinstance(data, dict) else {}
                v1.replace_namespaced_config_map(name, namespace, cm)
                break
            except ApiException as ae:
                if ae.status == 409 and attempt < max_retries:
                    # conflict: resourceVersion mismatch, retry after short sleep
                    time.sleep(0.2 * attempt)
                    continue
                # re-raise for outer handler
                raise
        # Refresh server side caches if any
        record_audit_event(
            action='update',
            resource_type='ConfigMap',
            resource_name=name,
            namespace=namespace,
            session_id=_short_session_id(request.cookies.get('session')),
        )
        return jsonify({'status': 'ok'})
    except ApiException as ae:
        # Return API exception details (status and body) to help debug conflicts
        parsed_body = None
        try:
            if getattr(ae, 'body', None):
                parsed_body = json.loads(ae.body)
        except Exception:
            parsed_body = getattr(ae, 'body', None)
        # Use the ApiException HTTP status code when available
        status_code = getattr(ae, 'status', 500)
        return jsonify({'error': str(ae), 'status': status_code, 'body': parsed_body}), status_code
    except Exception as e:
        # Log full traceback for server-side diagnosis and return generic error
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp_explorer.route('/k8s-explorer/secrets-summary')
def secrets_summary():
    """Secret listesini döndürür.

    Query parametreleri:
        namespace (str, opsiyonel): Belirtilirse yalnızca o namespace filtrelenir
                                    ('all' veya parametre yoksa tüm namespace'ler).
                                    Mevcut filtre korunur — AC-3.
        page      (int, opsiyonel): Sayfa numarası (1-tabanlı). Gönderilmezse
                                    tüm liste eski formatta döner (geriye dönük uyumluluk).
        per_page  (int, opsiyonel): Sayfa başına kayıt (varsayılan: 50, max: 500).

    Not: Namespace filtresi önce uygulanır, sayfalama sonra gelir (AC-3).

    Yanıt (sayfalama KAPALI — page parametresi yok):
        {"secrets": [...]}

    Yanıt (sayfalama AÇIK — page parametresi var):
        {"items": [...], "page": N, "per_page": M, "total": T, "total_pages": P}

    Hatalar:
        400: Geçersiz sayfalama parametresi.
    """
    try:
        configure_kube_client()
        v1 = client.CoreV1Api()
        namespace = request.args.get('namespace')
        if namespace and namespace != 'all':
            secrets = v1.list_namespaced_secret(namespace).items
        else:
            secrets = v1.list_secret_for_all_namespaces().items
        result = []
        for secret in secrets:
            data_count = len(secret.data) if secret.data else 0
            secret_type = secret.type if secret.type else 'Opaque'
            creation_timestamp = getattr(secret.metadata, 'creation_timestamp', None)
            result.append({
                'namespace': secret.metadata.namespace,
                'name': secret.metadata.name,
                'type': secret_type,
                'data_count': data_count,
                'creation_timestamp': creation_timestamp.isoformat() if creation_timestamp else None
            })
        # Sayfalama desteği — AC-1 (sayfalama), AC-2 (geriye dönük uyumluluk), AC-10 (doğrulama)
        try:
            paginated, is_paginated = paginate_list(result, request.args)
        except ValueError as ve:
            return jsonify({'error': str(ve)}), 400
        if is_paginated:
            return jsonify(paginated)
        # page parametresi yoksa eski format (geriye dönük uyumluluk — loadOverviewData() etkilenmez)
        return jsonify({'secrets': result})
    except Exception as e:
        return jsonify({'secrets': [], 'error': str(e)})


@bp_explorer.route('/k8s-explorer/secret')
def get_secret():
    name = request.args.get('name')
    namespace = request.args.get('namespace')
    if not name or not namespace:
        return jsonify({'error': 'name and namespace required'}), 400
    try:
        configure_kube_client()
        v1 = client.CoreV1Api()
        sec = v1.read_namespaced_secret(name, namespace)
        data = getattr(sec, 'data', {}) or {}
        # return metadata and data (note: secret.data may be base64-encoded strings)
        return jsonify({'secret': {'namespace': namespace, 'name': name, 'data': data}})
    except ApiException as ae:
        try:
            body = json.loads(ae.body) if getattr(ae, 'body', None) else None
        except Exception:
            body = getattr(ae, 'body', None)
        return jsonify({'error': str(ae), 'status': getattr(ae, 'status', 500), 'body': body}), getattr(ae, 'status', 500)
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp_explorer.route('/k8s-explorer/update-secret', methods=['POST'])
def update_secret():
    try:
        payload = request.get_json() or {}
        name = payload.get('name')
        namespace = payload.get('namespace')
        data = payload.get('data')
        if not name or not namespace or data is None:
            return jsonify({'error': 'name, namespace and data are required'}), 400
        configure_kube_client()
        v1 = client.CoreV1Api()
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                sec = v1.read_namespaced_secret(name, namespace)
                sec.data = data if isinstance(data, dict) else {}
                v1.replace_namespaced_secret(name, namespace, sec)
                break
            except ApiException as ae:
                if ae.status == 409 and attempt < max_retries:
                    time.sleep(0.2 * attempt)
                    continue
                raise
        record_audit_event(
            action='update',
            resource_type='Secret',
            resource_name=name,
            namespace=namespace,
            session_id=_short_session_id(request.cookies.get('session')),
            details=f'{len(data) if isinstance(data, dict) else "?"} adet anahtar güncellendi',
        )
        return jsonify({'status': 'ok'})
    except ApiException as ae:
        parsed_body = None
        try:
            if getattr(ae, 'body', None):
                parsed_body = json.loads(ae.body)
        except Exception:
            parsed_body = getattr(ae, 'body', None)
        status_code = getattr(ae, 'status', 500)
        return jsonify({'error': str(ae), 'status': status_code, 'body': parsed_body}), status_code
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp_explorer.route('/k8s-explorer/delete-secret', methods=['POST'])
def delete_secret():
    try:
        payload = request.get_json() or {}
        name = payload.get('name')
        namespace = payload.get('namespace')
        if not name or not namespace:
            return jsonify({'error': 'name and namespace required'}), 400
        err = require_confirm_name(payload)
        if err:
            return err
        configure_kube_client()
        v1 = client.CoreV1Api()
        v1.delete_namespaced_secret(name, namespace)
        record_audit_event(
            action='delete',
            resource_type='Secret',
            resource_name=name,
            namespace=namespace,
            session_id=_short_session_id(request.cookies.get('session')),
        )
        return jsonify({'status': 'ok'})
    except ApiException as ae:
        parsed_body = None
        try:
            if getattr(ae, 'body', None):
                parsed_body = json.loads(ae.body)
        except Exception:
            parsed_body = getattr(ae, 'body', None)
        status_code = getattr(ae, 'status', 500)
        return jsonify({'error': str(ae), 'status': status_code, 'body': parsed_body}), status_code
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp_explorer.route('/k8s-explorer/delete-configmap', methods=['POST'])
def delete_configmap():
    """ConfigMap siler.

    Method: POST
    Path:   /k8s-explorer/delete-configmap

    Body (JSON):
        name         (str): Silinecek ConfigMap adı.
        namespace    (str): ConfigMap'in namespace'i.
        confirm_name (str): Sunucu tarafı onay — name ile eşleşmeli.

    Yanıt (200):
        {"status": "ok"}

    Hatalar:
        400: name/namespace eksik ya da confirm_name doğrulaması başarısız.
        ApiException HTTP kodu: Kubernetes API hatası.
        500: Beklenmedik sunucu hatası.
    """
    try:
        payload = request.get_json() or {}
        name = payload.get('name')
        namespace = payload.get('namespace')
        if not name or not namespace:
            return jsonify({'error': 'name and namespace required'}), 400
        err = require_confirm_name(payload)
        if err:
            return err
        configure_kube_client()
        v1 = client.CoreV1Api()
        v1.delete_namespaced_config_map(name, namespace)
        record_audit_event(
            action='delete',
            resource_type='ConfigMap',
            resource_name=name,
            namespace=namespace,
            session_id=_short_session_id(request.cookies.get('session')),
        )
        return jsonify({'status': 'ok'})
    except ApiException as ae:
        parsed_body = None
        try:
            if getattr(ae, 'body', None):
                parsed_body = json.loads(ae.body)
        except Exception:
            parsed_body = getattr(ae, 'body', None)
        status_code = getattr(ae, 'status', 500)
        return jsonify({'error': str(ae), 'status': status_code, 'body': parsed_body}), status_code
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp_explorer.route('/k8s-explorer/resource-quotas-summary')
def resource_quotas_summary():
    try:
        configure_kube_client()
        v1 = client.CoreV1Api()
        quotas = v1.list_resource_quota_for_all_namespaces().items
        result = []
        for quota in quotas:
            hard = quota.status.hard if quota.status and quota.status.hard else {}
            used = quota.status.used if quota.status and quota.status.used else {}
            creation_timestamp = getattr(quota.metadata, 'creation_timestamp', None)
            result.append({
                'namespace': quota.metadata.namespace,
                'name': quota.metadata.name,
                'hard': dict(hard),
                'used': dict(used),
                'creation_timestamp': creation_timestamp.isoformat() if creation_timestamp else None
            })
        return jsonify({'resource_quotas': result})
    except Exception as e:
        return jsonify({'resource_quotas': [], 'error': str(e)})


@bp_explorer.route('/k8s-explorer/limit-ranges-summary')
def limit_ranges_summary():
    try:
        configure_kube_client()
        v1 = client.CoreV1Api()
        limit_ranges = v1.list_limit_range_for_all_namespaces().items
        result = []
        for lr in limit_ranges:
            limits_count = len(lr.spec.limits) if lr.spec and lr.spec.limits else 0
            creation_timestamp = getattr(lr.metadata, 'creation_timestamp', None)
            result.append({
                'namespace': lr.metadata.namespace,
                'name': lr.metadata.name,
                'limits_count': limits_count,
                'creation_timestamp': creation_timestamp.isoformat() if creation_timestamp else None
            })
        return jsonify({'limit_ranges': result})
    except Exception as e:
        return jsonify({'limit_ranges': [], 'error': str(e)})


@bp_explorer.route('/k8s-explorer/create-configmap', methods=['POST'])
def create_configmap():
    """Yeni bir ConfigMap oluşturur.

    Method: POST
    Path:   /k8s-explorer/create-configmap

    Body (JSON):
        name      (str):       Oluşturulacak ConfigMap adı (zorunlu).
        namespace (str):       Hedef namespace (zorunlu).
        data      (dict):      Key-value çiftleri (opsiyonel, boş ConfigMap oluşturulabilir).

    Yanıt (201):
        {"status": "ok"}

    Hatalar:
        400: name veya namespace eksik.
        ApiException HTTP kodu: Kubernetes API hatası.
        500: Beklenmedik sunucu hatası.
    """
    try:
        payload = request.get_json() or {}
        name = payload.get('name')
        namespace = payload.get('namespace')
        if not name or not namespace:
            return jsonify({'error': 'name and namespace required'}), 400
        configure_kube_client()
        v1 = client.CoreV1Api()
        cm_data = payload.get('data') or {}
        v1.create_namespaced_config_map(
            namespace,
            client.V1ConfigMap(
                metadata=client.V1ObjectMeta(name=name, namespace=namespace),
                data=cm_data
            )
        )
        record_audit_event(
            action='create',
            resource_type='ConfigMap',
            resource_name=name,
            namespace=namespace,
            session_id=_short_session_id(request.cookies.get('session')),
        )
        return jsonify({'status': 'ok'}), 201
    except ApiException as ae:
        parsed_body = None
        try:
            if getattr(ae, 'body', None):
                parsed_body = json.loads(ae.body)
        except Exception:
            parsed_body = getattr(ae, 'body', None)
        status_code = getattr(ae, 'status', 500)
        return jsonify({'error': str(ae), 'status': status_code, 'body': parsed_body}), status_code
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp_explorer.route('/k8s-explorer/create-secret', methods=['POST'])
def create_secret():
    """Yeni bir Secret oluşturur.

    Method: POST
    Path:   /k8s-explorer/create-secret

    Body (JSON):
        name      (str):       Oluşturulacak Secret adı (zorunlu).
        namespace (str):       Hedef namespace (zorunlu).
        type      (str):       Secret türü (varsayılan: "Opaque").
        data      (dict):      Key-value çiftleri — değerler frontend tarafından
                               base64'e çevrilmiş olarak gelir (opsiyonel).

    Yanıt (201):
        {"status": "ok"}

    Hatalar:
        400: name veya namespace eksik.
        ApiException HTTP kodu: Kubernetes API hatası.
        500: Beklenmedik sunucu hatası.
    """
    try:
        payload = request.get_json() or {}
        name = payload.get('name')
        namespace = payload.get('namespace')
        if not name or not namespace:
            return jsonify({'error': 'name and namespace required'}), 400
        configure_kube_client()
        v1 = client.CoreV1Api()
        secret_type = payload.get('type') or 'Opaque'
        secret_data = payload.get('data') or {}
        v1.create_namespaced_secret(
            namespace,
            client.V1Secret(
                metadata=client.V1ObjectMeta(name=name, namespace=namespace),
                type=secret_type,
                data=secret_data
            )
        )
        record_audit_event(
            action='create',
            resource_type='Secret',
            resource_name=name,
            namespace=namespace,
            session_id=_short_session_id(request.cookies.get('session')),
        )
        return jsonify({'status': 'ok'}), 201
    except ApiException as ae:
        parsed_body = None
        try:
            if getattr(ae, 'body', None):
                parsed_body = json.loads(ae.body)
        except Exception:
            parsed_body = getattr(ae, 'body', None)
        status_code = getattr(ae, 'status', 500)
        return jsonify({'error': str(ae), 'status': status_code, 'body': parsed_body}), status_code
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp_explorer.route('/k8s-explorer/create-resource-quota', methods=['POST'])
def create_resource_quota():
    """Yeni bir ResourceQuota oluşturur.

    Method: POST
    Path:   /k8s-explorer/create-resource-quota

    Body (JSON):
        name      (str):  Oluşturulacak ResourceQuota adı (zorunlu).
        namespace (str):  Hedef namespace (zorunlu).
        hard      (dict): Hard limit sözlüğü — örn. {"requests.cpu": "1", "pods": "10"}.
                          En az bir alan zorunludur; boş sözlük ise 400 döner.

    Yanıt (201):
        {"status": "ok"}

    Hatalar:
        400: name/namespace eksik veya hard sözlüğü boş.
        ApiException HTTP kodu: Kubernetes API hatası.
        500: Beklenmedik sunucu hatası.
    """
    try:
        payload = request.get_json() or {}
        name = payload.get('name')
        namespace = payload.get('namespace')
        hard = payload.get('hard') or {}
        if not name or not namespace:
            return jsonify({'error': 'name and namespace required'}), 400
        if not hard:
            return jsonify({'error': 'en az bir hard limit alani gereklidir'}), 400
        configure_kube_client()
        v1 = client.CoreV1Api()
        v1.create_namespaced_resource_quota(
            namespace,
            client.V1ResourceQuota(
                metadata=client.V1ObjectMeta(name=name, namespace=namespace),
                spec=client.V1ResourceQuotaSpec(hard=hard)
            )
        )
        record_audit_event(
            action='create',
            resource_type='ResourceQuota',
            resource_name=name,
            namespace=namespace,
            session_id=_short_session_id(request.cookies.get('session')),
        )
        return jsonify({'status': 'ok'}), 201
    except ApiException as ae:
        parsed_body = None
        try:
            if getattr(ae, 'body', None):
                parsed_body = json.loads(ae.body)
        except Exception:
            parsed_body = getattr(ae, 'body', None)
        status_code = getattr(ae, 'status', 500)
        return jsonify({'error': str(ae), 'status': status_code, 'body': parsed_body}), status_code
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp_explorer.route('/k8s-explorer/create-limit-range', methods=['POST'])
def create_limit_range():
    """Yeni bir LimitRange oluşturur (MVP: tek Container limit item).

    Method: POST
    Path:   /k8s-explorer/create-limit-range

    Body (JSON):
        name                 (str): Oluşturulacak LimitRange adı (zorunlu).
        namespace            (str): Hedef namespace (zorunlu).
        default_cpu          (str): Default CPU limiti (opsiyonel).
        default_memory       (str): Default bellek limiti (opsiyonel).
        default_request_cpu  (str): Default CPU request (opsiyonel).
        default_request_memory (str): Default bellek request (opsiyonel).
        max_cpu              (str): Maksimum CPU (opsiyonel).
        max_memory           (str): Maksimum bellek (opsiyonel).
        min_cpu              (str): Minimum CPU (opsiyonel).
        min_memory           (str): Minimum bellek (opsiyonel).

    En az bir limit alanı doldurulmalı; aksi halde 400 döner.

    Yanıt (201):
        {"status": "ok"}

    Hatalar:
        400: name/namespace eksik veya hiçbir limit alanı doldurulmamış.
        ApiException HTTP kodu: Kubernetes API hatası.
        500: Beklenmedik sunucu hatası.
    """
    try:
        payload = request.get_json() or {}
        name = payload.get('name')
        namespace = payload.get('namespace')
        if not name or not namespace:
            return jsonify({'error': 'name and namespace required'}), 400

        # Doldurulmuş alanlardan default/max/min sözlüklerini oluştur
        default = {}
        if payload.get('default_cpu'):
            default['cpu'] = payload['default_cpu']
        if payload.get('default_memory'):
            default['memory'] = payload['default_memory']

        default_request = {}
        if payload.get('default_request_cpu'):
            default_request['cpu'] = payload['default_request_cpu']
        if payload.get('default_request_memory'):
            default_request['memory'] = payload['default_request_memory']

        max_limit = {}
        if payload.get('max_cpu'):
            max_limit['cpu'] = payload['max_cpu']
        if payload.get('max_memory'):
            max_limit['memory'] = payload['max_memory']

        min_limit = {}
        if payload.get('min_cpu'):
            min_limit['cpu'] = payload['min_cpu']
        if payload.get('min_memory'):
            min_limit['memory'] = payload['min_memory']

        if not any([default, default_request, max_limit, min_limit]):
            return jsonify({'error': 'en az bir limit alani gereklidir'}), 400

        item = client.V1LimitRangeItem(
            type='Container',
            default=default or None,
            default_request=default_request or None,
            max=max_limit or None,
            min=min_limit or None,
        )
        configure_kube_client()
        v1 = client.CoreV1Api()
        v1.create_namespaced_limit_range(
            namespace,
            client.V1LimitRange(
                metadata=client.V1ObjectMeta(name=name, namespace=namespace),
                spec=client.V1LimitRangeSpec(limits=[item])
            )
        )
        record_audit_event(
            action='create',
            resource_type='LimitRange',
            resource_name=name,
            namespace=namespace,
            session_id=_short_session_id(request.cookies.get('session')),
        )
        return jsonify({'status': 'ok'}), 201
    except ApiException as ae:
        parsed_body = None
        try:
            if getattr(ae, 'body', None):
                parsed_body = json.loads(ae.body)
        except Exception:
            parsed_body = getattr(ae, 'body', None)
        status_code = getattr(ae, 'status', 500)
        return jsonify({'error': str(ae), 'status': status_code, 'body': parsed_body}), status_code
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp_explorer.route('/k8s-explorer/delete-resource-quota', methods=['POST'])
def delete_resource_quota():
    """ResourceQuota siler.

    Method: POST
    Path:   /k8s-explorer/delete-resource-quota

    Body (JSON):
        name         (str): Silinecek ResourceQuota adı.
        namespace    (str): ResourceQuota'nın namespace'i.
        confirm_name (str): Sunucu tarafı onay — name ile eşleşmeli.

    Yanıt (200):
        {"status": "ok"}

    Hatalar:
        400: name/namespace eksik ya da confirm_name doğrulaması başarısız.
        ApiException HTTP kodu: Kubernetes API hatası.
        500: Beklenmedik sunucu hatası.
    """
    try:
        payload = request.get_json() or {}
        name = payload.get('name')
        namespace = payload.get('namespace')
        if not name or not namespace:
            return jsonify({'error': 'name and namespace required'}), 400
        err = require_confirm_name(payload)
        if err:
            return err
        configure_kube_client()
        v1 = client.CoreV1Api()
        v1.delete_namespaced_resource_quota(name, namespace)
        record_audit_event(
            action='delete',
            resource_type='ResourceQuota',
            resource_name=name,
            namespace=namespace,
            session_id=_short_session_id(request.cookies.get('session')),
        )
        return jsonify({'status': 'ok'})
    except ApiException as ae:
        parsed_body = None
        try:
            if getattr(ae, 'body', None):
                parsed_body = json.loads(ae.body)
        except Exception:
            parsed_body = getattr(ae, 'body', None)
        status_code = getattr(ae, 'status', 500)
        return jsonify({'error': str(ae), 'status': status_code, 'body': parsed_body}), status_code
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp_explorer.route('/k8s-explorer/delete-limit-range', methods=['POST'])
def delete_limit_range():
    """LimitRange siler.

    Method: POST
    Path:   /k8s-explorer/delete-limit-range

    Body (JSON):
        name         (str): Silinecek LimitRange adı.
        namespace    (str): LimitRange'in namespace'i.
        confirm_name (str): Sunucu tarafı onay — name ile eşleşmeli.

    Yanıt (200):
        {"status": "ok"}

    Hatalar:
        400: name/namespace eksik ya da confirm_name doğrulaması başarısız.
        ApiException HTTP kodu: Kubernetes API hatası.
        500: Beklenmedik sunucu hatası.
    """
    try:
        payload = request.get_json() or {}
        name = payload.get('name')
        namespace = payload.get('namespace')
        if not name or not namespace:
            return jsonify({'error': 'name and namespace required'}), 400
        err = require_confirm_name(payload)
        if err:
            return err
        configure_kube_client()
        v1 = client.CoreV1Api()
        v1.delete_namespaced_limit_range(name, namespace)
        record_audit_event(
            action='delete',
            resource_type='LimitRange',
            resource_name=name,
            namespace=namespace,
            session_id=_short_session_id(request.cookies.get('session')),
        )
        return jsonify({'status': 'ok'})
    except ApiException as ae:
        parsed_body = None
        try:
            if getattr(ae, 'body', None):
                parsed_body = json.loads(ae.body)
        except Exception:
            parsed_body = getattr(ae, 'body', None)
        status_code = getattr(ae, 'status', 500)
        return jsonify({'error': str(ae), 'status': status_code, 'body': parsed_body}), status_code
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp_explorer.route('/k8s-explorer/create-lease', methods=['POST'])
def create_lease():
    """Yeni bir Lease oluşturur.

    Method: POST
    Path:   /k8s-explorer/create-lease

    Body (JSON):
        name                   (str): Oluşturulacak Lease adı (zorunlu).
        namespace              (str): Hedef namespace (zorunlu).
        lease_duration_seconds (int): Lease süresi saniye cinsinden (zorunlu).
        holder_identity        (str): Lease sahibi kimliği (opsiyonel; boş string ise None olarak işlenir).

    Yanıt (201):
        {"status": "ok"}

    Hatalar:
        400: name, namespace veya lease_duration_seconds eksik.
        ApiException HTTP kodu: Kubernetes API hatası.
        500: Beklenmedik sunucu hatası.
    """
    try:
        payload = request.get_json() or {}
        name = payload.get('name')
        namespace = payload.get('namespace')
        lease_duration_seconds = payload.get('lease_duration_seconds')
        if not name or not namespace:
            return jsonify({'error': 'name and namespace required'}), 400
        if lease_duration_seconds is None:
            return jsonify({'error': 'lease_duration_seconds required'}), 400
        try:
            lease_duration_seconds = int(lease_duration_seconds)
        except (ValueError, TypeError):
            return jsonify({'error': 'lease_duration_seconds must be an integer'}), 400
        # holder_identity boş string gelebilir — opsiyonel alan, None olarak ilet
        holder_identity = payload.get('holder_identity') or None
        configure_kube_client()
        coord_v1 = client.CoordinationV1Api()
        coord_v1.create_namespaced_lease(
            namespace,
            client.V1Lease(
                metadata=client.V1ObjectMeta(name=name, namespace=namespace),
                spec=client.V1LeaseSpec(
                    holder_identity=holder_identity,
                    lease_duration_seconds=lease_duration_seconds
                )
            )
        )
        record_audit_event(
            action='create',
            resource_type='Lease',
            resource_name=name,
            namespace=namespace,
            session_id=_short_session_id(request.cookies.get('session')),
        )
        return jsonify({'status': 'ok'}), 201
    except ApiException as ae:
        parsed_body = None
        try:
            if getattr(ae, 'body', None):
                parsed_body = json.loads(ae.body)
        except Exception:
            parsed_body = getattr(ae, 'body', None)
        status_code = getattr(ae, 'status', 500)
        return jsonify({'error': str(ae), 'status': status_code, 'body': parsed_body}), status_code
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
