"""explorer/core.py — Genel /k8s-explorer route'ları.

İçerik: app-health, health, namespaces, namespace-children, describe,
yaml (GET+PATCH), delete (POST+DELETE), logs, workload-stats, k8s-explorer (sayfa).
"""

import os
import time
import traceback
import yaml

from flask import jsonify, render_template, request
from kubernetes import client, config
from kubernetes.client.rest import ApiException

from version import __version__ as APP_VERSION
import web.background as _bg
import web.kubeconfig_manager as _kcm
from web.background import (
    update_pods_summary_cache,
    update_workload_stats_cache,
)
from web.kubeconfig_manager import (
    get_active_kubeconfig_path,
    load_kube_config_active,
)
from web.audit_log import record_audit_event, _short_session_id

from web.blueprints.explorer import bp_explorer


@bp_explorer.route('/k8s-explorer/app-health')
def app_health():
    """Kubeconfig gerektirmeyen basit uygulama canlılık kontrolü.
    ---
    tags:
      - health
    responses:
      200:
        description: Application is running
        schema:
          type: object
          properties:
            status:
              type: string
              example: ok
            version:
              type: string
              example: 1.0.0
    """
    return jsonify({
        "status": "ok",
        "version": APP_VERSION
    })


@bp_explorer.route('/k8s-explorer/health')
def k8s_explorer_health():
    """Lightweight health check returning: connectivity ok flag, active kube context name, error (if any).

    We now derive the context name from the *active* kubeconfig path selected via session / global fallback
    instead of whatever the default KUBECONFIG env might point to. This matches the cluster actually used
    by backend requests (load_kube_config_active()).
    """
    current_context_name = None
    ok = False
    error = None
    try:
        # Ensure active kubeconfig is loaded (this sets default client configuration)
        load_kube_config_active()
    except Exception as e:
        # NOT: load_kube_config_active() başarısız olsa bile AŞAĞIDAKİ AC-4 bloğu
        # (background_caches/degraded) HER ZAMAN hesaplanmalı -- tam da cluster
        # erişilemezken health endpoint'inin en bilgilendirici olması gerektiği an.
        # Bu yüzden burada erken return YAPILMAZ, sadece ok/error set edilir.
        error = str(e)
    else:
        # After loading, try to list contexts from the same file path to get current context name
        try:
            active_path = get_active_kubeconfig_path()
            if active_path and os.path.exists(active_path):
                try:
                    contexts, current_context = config.list_kube_config_contexts(config_file=active_path)
                except TypeError:
                    # Older client versions use different parameter name (config_filename)
                    contexts, current_context = config.list_kube_config_contexts(config_filename=active_path)  # type: ignore
                if isinstance(current_context, dict):
                    current_context_name = current_context.get('name') or current_context.get('context', {}).get('cluster')
                elif isinstance(current_context, str):
                    current_context_name = current_context
        except Exception:
            current_context_name = None

        # Lightweight API call to verify connectivity
        try:
            c = client.Configuration.get_default_copy()
            c.verify_ssl = False
            c.assert_hostname = False
            client.Configuration.set_default(c)
            core_v1 = client.CoreV1Api()
            try:
                core_v1.list_namespace(_request_timeout=5)
                ok = True
                error = None
            except Exception as api_exc:
                ok = False
                error = str(api_exc)
        except Exception as e:
            ok = False
            error = str(e)

    try:
        # --- AC-4: Arka plan cache durumlarını ekle ---
        now = time.time()

        def _cache_info(last_error, consecutive_errors, last_success_time):
            """Tek bir cache için durum dict'i oluşturur."""
            age = None
            if last_success_time and last_success_time > 0:
                age = int(now - last_success_time)
            return {
                'consecutive_errors': consecutive_errors,
                'last_error': last_error,
                'last_success_age_sec': age,
            }

        background_caches = {
            'workload_stats': _cache_info(
                _bg._wsc_last_error,
                _bg._wsc_consecutive_errors,
                _bg.workload_stats_cache_time,
            ),
            'pods_summary': _cache_info(
                _bg._psc_last_error,
                _bg._psc_consecutive_errors,
                _bg.pods_summary_cache_time,
            ),
            'metrics_sampler': _cache_info(
                _bg._msl_last_error,
                _bg._msl_consecutive_errors,
                _bg._msl_last_success_time,
            ),
            'pss': _cache_info(
                _bg._pss_last_error,
                _bg._pss_consecutive_errors,
                _bg.pss_cache_time,
            ),
            'netpol_coverage': _cache_info(
                _bg._npc_last_error,
                _bg._npc_consecutive_errors,
                _bg.netpol_coverage_cache_time,
            ),
        }
        degraded = any(
            info['consecutive_errors'] >= _bg.MAX_CONSECUTIVE_ERRORS
            for info in background_caches.values()
        )
        return jsonify({
            'ok': ok,
            'context': current_context_name,
            'error': error,
            'background_caches': background_caches,
            'degraded': degraded,
            'activation_version': _kcm._KUBECONFIG_ACTIVATION_VERSION,
        })
    except Exception as e:
        return jsonify({'ok': False, 'context': None, 'error': str(e)}), 500


# Namespace listesini döndüren endpoint
@bp_explorer.route('/k8s-explorer/namespaces')
def k8s_explorer_namespaces():
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        core_v1 = client.CoreV1Api()
        namespaces = [ns.metadata.name for ns in core_v1.list_namespace().items]
        return jsonify({'namespaces': namespaces})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Namespace altında önce ingress varsa onu, yoksa service'leri döndüren endpoint
@bp_explorer.route('/k8s-explorer/namespace-children')
def k8s_explorer_namespace_children():
    namespace = request.args.get('namespace')
    if not namespace:
        return jsonify({'error': 'namespace zorunlu'}), 400
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        networking_v1 = client.NetworkingV1Api()
        core_v1 = client.CoreV1Api()
        # Önce ingressleri al
        ingresses = networking_v1.list_namespaced_ingress(namespace=namespace).items
        if ingresses:
            result = [{'type': 'ingress', 'name': i.metadata.name, 'namespace': namespace} for i in ingresses]
            return jsonify({'children': result, 'resource_type': 'ingress'})
        # Yoksa service'leri al
        services = core_v1.list_namespaced_service(namespace=namespace).items
        result = [{'type': 'service', 'name': s.metadata.name, 'namespace': namespace} for s in services]
        return jsonify({'children': result, 'resource_type': 'service'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp_explorer.route('/k8s-explorer/describe')
def k8s_explorer_describe():
    import subprocess
    obj_type = request.args.get('type')
    namespace = request.args.get('namespace')
    name = request.args.get('name')
    if not obj_type or not namespace or not name:
        return jsonify({'error': 'type, namespace ve name zorunlu'}), 400
    if obj_type not in ['pod', 'deployment']:
        return jsonify({'error': 'Sadece pod veya deployment destekleniyor'}), 400
    try:
        kubeconfig = os.environ.get('KUBECONFIG')
        cmd = ["kubectl", "describe", obj_type, name, "-n", namespace]
        if kubeconfig:
            cmd = ["kubectl", "--kubeconfig", kubeconfig] + cmd[1:]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
        if result.returncode == 0:
            return jsonify({'describe': result.stdout})
        else:
            return jsonify({'error': result.stderr or 'Describe alınamadı.'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp_explorer.route('/k8s-explorer/yaml', methods=['GET', 'PATCH'])
def k8s_explorer_yaml():
    try:
        if request.method == 'GET':
            obj_type = request.args.get('type')
            namespace = request.args.get('namespace')
            name = request.args.get('name')
            if not obj_type or not name:
                return 'type ve name zorunlu', 400
            load_kube_config_active()
            c = client.Configuration.get_default_copy()
            c.verify_ssl = False
            c.assert_hostname = False
            client.Configuration.set_default(c)
            kube_client = type('KubeClient', (), {})()
            if obj_type == 'ingress':
                kube_client.networking_v1 = client.NetworkingV1Api()
                obj = kube_client.networking_v1.read_namespaced_ingress(name, namespace, _preload_content=False)
            elif obj_type == 'service':
                kube_client.core_v1 = client.CoreV1Api()
                obj = kube_client.core_v1.read_namespaced_service(name, namespace, _preload_content=False)
            elif obj_type == 'endpoints':
                kube_client.core_v1 = client.CoreV1Api()
                obj = kube_client.core_v1.read_namespaced_endpoints(name, namespace, _preload_content=False)
            elif obj_type == 'deployment':
                kube_client.apps_v1 = client.AppsV1Api()
                obj = kube_client.apps_v1.read_namespaced_deployment(name, namespace, _preload_content=False)
            elif obj_type == 'daemonset':
                kube_client.apps_v1 = client.AppsV1Api()
                obj = kube_client.apps_v1.read_namespaced_daemon_set(name, namespace, _preload_content=False)
            elif obj_type == 'statefulset':
                kube_client.apps_v1 = client.AppsV1Api()
                obj = kube_client.apps_v1.read_namespaced_stateful_set(name, namespace, _preload_content=False)
            elif obj_type == 'pod':
                kube_client.core_v1 = client.CoreV1Api()
                obj = kube_client.core_v1.read_namespaced_pod(name, namespace, _preload_content=False)
            elif obj_type in ('serviceaccount','sa'):
                kube_client.core_v1 = client.CoreV1Api(); obj = kube_client.core_v1.read_namespaced_service_account(name, namespace, _preload_content=False)
            elif obj_type == 'role':
                kube_client.rbac_v1 = client.RbacAuthorizationV1Api(); obj = kube_client.rbac_v1.read_namespaced_role(name, namespace, _preload_content=False)
            elif obj_type == 'rolebinding':
                kube_client.rbac_v1 = client.RbacAuthorizationV1Api(); obj = kube_client.rbac_v1.read_namespaced_role_binding(name, namespace, _preload_content=False)
            elif obj_type == 'clusterrole':
                kube_client.rbac_v1 = client.RbacAuthorizationV1Api(); obj = kube_client.rbac_v1.read_cluster_role(name, _preload_content=False)
            elif obj_type == 'clusterrolebinding':
                kube_client.rbac_v1 = client.RbacAuthorizationV1Api(); obj = kube_client.rbac_v1.read_cluster_role_binding(name, _preload_content=False)
            elif obj_type in ('pvc','persistentvolumeclaim'):
                kube_client.core_v1 = client.CoreV1Api()
                obj = kube_client.core_v1.read_namespaced_persistent_volume_claim(name, namespace, _preload_content=False)
            elif obj_type in ('pv','persistentvolume'):
                kube_client.core_v1 = client.CoreV1Api()
                obj = kube_client.core_v1.read_persistent_volume(name, _preload_content=False)
            elif obj_type in ('storageclass','storageclasses','storage-class','sc'):
                kube_client.storage_v1 = client.StorageV1Api()
                obj = kube_client.storage_v1.read_storage_class(name, _preload_content=False)
            elif obj_type == 'node':
                kube_client.core_v1 = client.CoreV1Api()
                obj = kube_client.core_v1.read_node(name, _preload_content=False)
            else:
                return 'Bilinmeyen obje tipi', 400
            # obj.data genellikle JSON string döner, bunu parse edip YAML'a çevir
            import json as _json
            try:
                obj_dict = _json.loads(obj.data)
            except Exception:
                obj_dict = obj.data  # fallback, eğer zaten dict ise
            yaml_str = yaml.safe_dump(obj_dict, sort_keys=False, allow_unicode=True)
            return yaml_str, 200, {'Content-Type': 'text/yaml'}
        elif request.method == 'PATCH':
            data = request.get_json(force=True)
            obj_type = data.get('type')
            namespace = data.get('namespace')
            name = data.get('name')
            yaml_str = data.get('yaml')
            if not obj_type or not name or not yaml_str:
                return 'type, name, yaml zorunlu', 400
            load_kube_config_active()
            c = client.Configuration.get_default_copy()
            c.verify_ssl = False
            c.assert_hostname = False
            client.Configuration.set_default(c)
            kube_client = type('KubeClient', (), {})()
            body = yaml.safe_load(yaml_str)
            if obj_type == 'ingress':
                kube_client.networking_v1 = client.NetworkingV1Api()
                kube_client.networking_v1.patch_namespaced_ingress(name, namespace, body)
            elif obj_type == 'service':
                kube_client.core_v1 = client.CoreV1Api()
                kube_client.core_v1.patch_namespaced_service(name, namespace, body)
            elif obj_type == 'endpoints':
                kube_client.core_v1 = client.CoreV1Api()
                kube_client.core_v1.patch_namespaced_endpoints(name, namespace, body)
            elif obj_type == 'deployment':
                kube_client.apps_v1 = client.AppsV1Api()
                kube_client.apps_v1.patch_namespaced_deployment(name, namespace, body)
            elif obj_type == 'daemonset':
                kube_client.apps_v1 = client.AppsV1Api()
                kube_client.apps_v1.patch_namespaced_daemon_set(name, namespace, body)
            elif obj_type == 'statefulset':
                kube_client.apps_v1 = client.AppsV1Api()
                kube_client.apps_v1.patch_namespaced_stateful_set(name, namespace, body)
            elif obj_type == 'pod':
                kube_client.core_v1 = client.CoreV1Api()
                kube_client.core_v1.patch_namespaced_pod(name, namespace, body)
            elif obj_type in ('serviceaccount','sa'):
                kube_client.core_v1 = client.CoreV1Api(); kube_client.core_v1.patch_namespaced_service_account(name, namespace, body)
            elif obj_type == 'role':
                kube_client.rbac_v1 = client.RbacAuthorizationV1Api(); kube_client.rbac_v1.patch_namespaced_role(name, namespace, body)
            elif obj_type == 'rolebinding':
                kube_client.rbac_v1 = client.RbacAuthorizationV1Api(); kube_client.rbac_v1.patch_namespaced_role_binding(name, namespace, body)
            elif obj_type == 'clusterrole':
                kube_client.rbac_v1 = client.RbacAuthorizationV1Api(); kube_client.rbac_v1.patch_cluster_role(name, body)
            elif obj_type == 'clusterrolebinding':
                kube_client.rbac_v1 = client.RbacAuthorizationV1Api(); kube_client.rbac_v1.patch_cluster_role_binding(name, body)
            elif obj_type in ('pvc','persistentvolumeclaim'):
                kube_client.core_v1 = client.CoreV1Api()
                kube_client.core_v1.patch_namespaced_persistent_volume_claim(name, namespace, body)
            elif obj_type in ('pv','persistentvolume'):
                kube_client.core_v1 = client.CoreV1Api()
                kube_client.core_v1.patch_persistent_volume(name, body)
            elif obj_type in ('storageclass','storageclasses','storage-class','sc'):
                kube_client.storage_v1 = client.StorageV1Api()
                kube_client.storage_v1.patch_storage_class(name, body)
            else:
                return 'Bilinmeyen obje tipi', 400
            # YAML edit sonrası pods_summary_cache'i hemen güncelle
            update_pods_summary_cache()
            _YAML_RESOURCE_TYPE_MAP = {
                'ingress': 'Ingress', 'service': 'Service', 'endpoints': 'Endpoints',
                'deployment': 'Deployment', 'daemonset': 'DaemonSet', 'statefulset': 'StatefulSet',
                'pod': 'Pod', 'serviceaccount': 'ServiceAccount', 'sa': 'ServiceAccount',
                'role': 'Role', 'rolebinding': 'RoleBinding',
                'clusterrole': 'ClusterRole', 'clusterrolebinding': 'ClusterRoleBinding',
                'pvc': 'PVC', 'persistentvolumeclaim': 'PVC',
                'pv': 'PV', 'persistentvolume': 'PV',
                'storageclass': 'StorageClass', 'storageclasses': 'StorageClass',
                'storage-class': 'StorageClass', 'sc': 'StorageClass',
            }
            record_audit_event(
                action='yaml_update',
                resource_type=_YAML_RESOURCE_TYPE_MAP.get(obj_type, obj_type.capitalize() if obj_type else 'Unknown'),
                resource_name=name,
                namespace=namespace or None,
                session_id=_short_session_id(request.cookies.get('session')),
            )
            return 'ok', 200
    except Exception as e:
        return str(e), 500


# Generic delete endpoint for various K8s resources
@bp_explorer.route('/k8s-explorer/delete', methods=['POST', 'DELETE'])
def k8s_explorer_delete():
    # Accept parameters from querystring OR JSON body
    try:
        try:
            data = request.get_json(force=False) or {}
        except Exception:
            data = {}

        obj_type = (request.args.get('type') or data.get('type') or '').lower().strip()
        namespace = (request.args.get('namespace') or data.get('namespace') or '').strip()
        name = (request.args.get('name') or data.get('name') or '').strip()

        if not obj_type or not name:
            return jsonify({'error': 'type ve name zorunlu'}), 400

        namespaced_kinds = {'pod','service','deployment','deployments','replicaset','replicasets','daemonset','daemonsets','statefulset','statefulsets','endpoint','endpoints','pvc','persistentvolumeclaim','persistentvolumeclaims','serviceaccount','sa','role','rolebinding'}
        cluster_scoped = {'pv','persistentvolume','persistentvolumes','storageclass','storageclasses','storage-class','sc','clusterrole','clusterrolebinding','node'}
        if obj_type in namespaced_kinds and not namespace:
            return jsonify({'error': 'namespaced kaynak için namespace zorunlu'}), 400

        load_kube_config_active()
        c = client.Configuration.get_default_copy(); c.verify_ssl=False; c.assert_hostname=False; client.Configuration.set_default(c)
        core_v1 = client.CoreV1Api(); apps_v1 = client.AppsV1Api(); storage_v1 = client.StorageV1Api(); rbac_v1 = client.RbacAuthorizationV1Api()

        _DELETE_RESOURCE_TYPE_MAP = {
            'pod': 'Pod', 'service': 'Service', 'deployment': 'Deployment',
            'replicaset': 'ReplicaSet', 'daemonset': 'DaemonSet', 'statefulset': 'StatefulSet',
            'endpoints': 'Endpoints', 'pvc': 'PVC', 'pv': 'PV', 'storageclass': 'StorageClass',
            'serviceaccount': 'ServiceAccount', 'role': 'Role', 'rolebinding': 'RoleBinding',
            'clusterrole': 'ClusterRole', 'clusterrolebinding': 'ClusterRoleBinding',
        }

        def ok(resp_type, extra=None):
            d = {'ok': True, 'deleted': {'type': resp_type, 'name': name}}
            if namespace:
                d['deleted']['namespace'] = namespace
            if extra:
                d['deleted'].update(extra)
            record_audit_event(
                action='delete',
                resource_type=_DELETE_RESOURCE_TYPE_MAP.get(resp_type, resp_type.capitalize()),
                resource_name=name,
                namespace=namespace or None,
                session_id=_short_session_id(request.cookies.get('session')),
            )
            return jsonify(d), 200

        if obj_type == 'pod':
            core_v1.delete_namespaced_pod(name=name, namespace=namespace, grace_period_seconds=30)
            try: update_pods_summary_cache()
            except Exception: pass
            return ok('pod')
        if obj_type == 'service':
            core_v1.delete_namespaced_service(name=name, namespace=namespace); return ok('service')
        if obj_type in ('deployment','deployments'):
            apps_v1.delete_namespaced_deployment(name=name, namespace=namespace, body=client.V1DeleteOptions()); return ok('deployment')
        if obj_type in ('replicaset','replicasets'):
            apps_v1.delete_namespaced_replica_set(name=name, namespace=namespace, body=client.V1DeleteOptions()); return ok('replicaset')
        if obj_type in ('daemonset','daemonsets'):
            apps_v1.delete_namespaced_daemon_set(name=name, namespace=namespace, body=client.V1DeleteOptions()); return ok('daemonset')
        if obj_type in ('statefulset','statefulsets'):
            apps_v1.delete_namespaced_stateful_set(name=name, namespace=namespace, body=client.V1DeleteOptions()); return ok('statefulset')
        if obj_type in ('endpoint','endpoints'):
            core_v1.delete_namespaced_endpoints(name=name, namespace=namespace); return ok('endpoints')
        if obj_type in ('pvc','persistentvolumeclaim','persistentvolumeclaims'):
            core_v1.delete_namespaced_persistent_volume_claim(name=name, namespace=namespace); return ok('pvc')
        if obj_type in ('pv','persistentvolume','persistentvolumes'):
            core_v1.delete_persistent_volume(name=name); return ok('pv')
        if obj_type in ('storageclass','storageclasses','storage-class','sc'):
            storage_v1.delete_storage_class(name=name); return ok('storageclass')
        if obj_type in ('serviceaccount','sa'):
            core_v1.delete_namespaced_service_account(name=name, namespace=namespace); return ok('serviceaccount')
        if obj_type == 'role':
            rbac_v1.delete_namespaced_role(name=name, namespace=namespace); return ok('role')
        if obj_type == 'rolebinding':
            rbac_v1.delete_namespaced_role_binding(name=name, namespace=namespace); return ok('rolebinding')
        if obj_type == 'clusterrole':
            rbac_v1.delete_cluster_role(name=name); return ok('clusterrole')
        if obj_type == 'clusterrolebinding':
            rbac_v1.delete_cluster_role_binding(name=name); return ok('clusterrolebinding')
        return jsonify({'error': f'Unsupported resource type: {obj_type}'}), 400
    except client.exceptions.ApiException as api_exc:
        msg = None
        try: msg = api_exc.body or str(api_exc)
        except Exception: msg = str(api_exc)
        return jsonify({'error': 'Kubernetes API error', 'details': msg}), getattr(api_exc,'status',500)
    except Exception as e:
        tb = traceback.format_exc()
        return jsonify({'error': str(e), 'trace': tb}), 500


# Pod loglarını döndüren endpoint
@bp_explorer.route('/k8s-explorer/logs')
def k8s_explorer_logs():
    obj_type = request.args.get('type')
    namespace = request.args.get('namespace')
    name = request.args.get('name')
    if obj_type != 'pod' or not namespace or not name:
        return 'type=pod, namespace ve name zorunlu', 400
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        core_v1 = client.CoreV1Api()
        log = core_v1.read_namespaced_pod_log(name=name, namespace=namespace, tail_lines=500)
        return log, 200, {'Content-Type': 'text/plain; charset=utf-8'}
    except Exception as e:
        return str(e), 500


# Workload stats API for Overview pie charts — cache background.py'de

@bp_explorer.route('/k8s-explorer/workload-stats')
def k8s_explorer_workload_stats():
    try:
        refresh = request.args.get('refresh')
        now = time.time()
        # Eğer refresh=1 parametresi varsa veya cache yoksa/süresi dolduysa, güncelle
        if refresh == '1' or not _bg.workload_stats_cache or (now - _bg.workload_stats_cache_time > _bg.WORKLOAD_STATS_CACHE_TTL):
            update_workload_stats_cache()
        result = dict(_bg.workload_stats_cache) if _bg.workload_stats_cache else {}
        age = int(now - _bg.workload_stats_cache_time) if _bg.workload_stats_cache_time else int(now)
        result['_cache_meta'] = {
            'updated_at': _bg.workload_stats_cache_time,
            'age_seconds': age,
            'stale': age > 300,
            'last_error': _bg._wsc_last_error,
        }
        return jsonify(result)
    except Exception as e:
        import sys, traceback
        print('WORKLOAD STATS ERROR:', e, file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        return jsonify({'error': str(e)}), 500


@bp_explorer.route('/k8s-explorer')
def k8s_explorer_page():
    return render_template('k8s_explorer.html')
