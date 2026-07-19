"""explorer/config.py — Konfigürasyon kaynak route'ları.

İçerik: configmaps-summary, configmap, update-configmap,
secrets-summary, secret, update-secret, delete-secret,
resource-quotas-summary, limit-ranges-summary.
"""

import json
import time
import traceback

from flask import jsonify, request
from kubernetes import client
from kubernetes.client.rest import ApiException

from web.kubeconfig_manager import load_kube_config_active
from web.audit_log import record_audit_event, _short_session_id

from web.blueprints.explorer import bp_explorer


@bp_explorer.route('/k8s-explorer/configmaps-summary')
def configmaps_summary():
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        v1 = client.CoreV1Api()
        # support optional namespace filtering via ?namespace=<name> (use 'all' for all namespaces)
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
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
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
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
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
    try:
        namespace = request.args.get('namespace')
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        v1 = client.CoreV1Api()
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
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
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
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
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
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
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


@bp_explorer.route('/k8s-explorer/resource-quotas-summary')
def resource_quotas_summary():
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
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
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
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
