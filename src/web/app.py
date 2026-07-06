from flask import Flask, render_template, jsonify, request, redirect, make_response, session, send_from_directory
from flask_cors import CORS
from scanner.k8s_scanner import K8sScanner
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from datetime import datetime
from flasgger import Swagger
import threading, time, sys, traceback, os, subprocess, json, yaml, urllib.parse, requests, secrets
from pathlib import Path
from version import __version__ as APP_VERSION
from collections import deque
import traceback
import urllib.parse
import sys
import os
import json
from datetime import datetime
from flasgger import Swagger
from scanner.k8s_scanner import K8sScanner

CORS_ORIGINS = ["http://localhost:8080", "http://127.0.0.1:8080"]

# PyInstaller bundle içinde template/static yolları düzelt
if getattr(sys, 'frozen', False):  # bundle
    BASE_DIR = getattr(sys, '_MEIPASS', os.path.abspath(os.path.dirname(__file__)))  # type: ignore[attr-defined]
    # PyInstaller may place bundled data under different relative paths depending on how --add-data was given.
    # Check a few likely candidate locations and pick the first that exists.
    cand_templates = [
        os.path.join(BASE_DIR, 'web', 'templates'),
        os.path.join(BASE_DIR, 'templates'),
        os.path.join(BASE_DIR, 'src', 'web', 'templates'),
    ]
    cand_static = [
        os.path.join(BASE_DIR, 'web', 'static'),
        os.path.join(BASE_DIR, 'static'),
        os.path.join(BASE_DIR, 'src', 'web', 'static'),
    ]
    TEMPLATE_DIR = next((p for p in cand_templates if os.path.isdir(p)), cand_templates[0])
    STATIC_DIR = next((p for p in cand_static if os.path.isdir(p)), cand_static[0])
else:
    SRC_WEB_DIR = os.path.abspath(os.path.dirname(__file__))
    TEMPLATE_DIR = os.path.join(SRC_WEB_DIR, 'templates')
    STATIC_DIR = os.path.join(SRC_WEB_DIR, 'static')

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
_env_secret = os.environ.get('APP_SECRET_KEY')
if _env_secret:
    app.secret_key = _env_secret
elif getattr(sys, 'frozen', False):
    _key_path = Path.home() / '.kubesec' / 'secret_key'
    if _key_path.exists():
        app.secret_key = _key_path.read_text().strip()
    else:
        _generated_key = secrets.token_hex(32)
        _key_path.parent.mkdir(parents=True, exist_ok=True)
        _key_path.write_text(_generated_key)
        _key_path.chmod(0o600)
        app.secret_key = _generated_key
    app.logger.warning("APP_SECRET_KEY not set; using key from ~/.kubesec/secret_key")
else:
    app.secret_key = 'dev-secret-do-not-use-in-production'
CORS(app, origins=CORS_ORIGINS, supports_credentials=True)
swagger = Swagger(app, config={
    "headers": [],
    "specs": [
        {
            "endpoint": 'apispec_1',
            "route": '/apispec_1.json',
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/apidocs/",
    "host": "127.0.0.1:8080",
    "schemes": ["http"]
})

# Suppress noisy InsecureRequestWarning globally (dev convenience; remove for prod hardening)
try:
    import urllib3
    from urllib3.exceptions import InsecureRequestWarning
    urllib3.disable_warnings(InsecureRequestWarning)
except Exception:
    pass

# Favicon route to avoid 404 spam in logs; serve from static if present else empty 204
@app.route('/favicon.ico')
def favicon():
    static_path = os.path.join(app.root_path, 'static')
    ico_path = os.path.join(static_path, 'favicon.ico')
    if os.path.exists(ico_path):
        return send_from_directory(static_path, 'favicon.ico', mimetype='image/vnd.microsoft.icon')
    return ('', 204)

# --- i18n — i18n.py'den import edildi ---
from web.i18n import I18N, translate

@app.context_processor
def inject_i18n():
    try:
        lang = request.cookies.get('lang') or 'tr'
    except Exception:
        lang = 'tr'
    return {
        't': lambda key: translate(key, lang),
        'current_locale': lang,
        'i18n_json': I18N
    }


# Lightweight debug helper to inspect where Flask is resolving templates/static when frozen.
@app.route('/_debug/list-templates')
def _debug_list_templates():
    try:
        tpl = app.template_folder
        static = app.static_folder
        tpl_exists = os.path.isdir(tpl)
        static_exists = os.path.isdir(static)
        tpl_files = []
        static_files = []
        if tpl_exists:
            for root, dirs, files in os.walk(tpl):
                for f in files[:50]:
                    tpl_files.append(os.path.relpath(os.path.join(root, f), tpl))
                break
        if static_exists:
            for root, dirs, files in os.walk(static):
                for f in files[:50]:
                    static_files.append(os.path.relpath(os.path.join(root, f), static))
                break
        return jsonify({'template_folder': tpl, 'template_exists': tpl_exists, 'template_sample': tpl_files,
                        'static_folder': static, 'static_exists': static_exists, 'static_sample': static_files})
    except Exception as e:
        return jsonify({'error': str(e)})

# ---- Kubeconfig Manager — kubeconfig_manager.py'den import edildi ----
from web.kubeconfig_manager import (
    KUBECONFIG_STORE,
    KUBECONFIG_ACTIVE_KEY,
    KUBECONFIG_UPLOAD_DIR,
    KUBECONFIG_ACTIVE_GLOBAL,
    KUBECONFIG_LAST_PATH,
    _KUBECONFIG_LOCK,
    list_kubeconfigs,
    get_active_kubeconfig_path,
    load_kube_config_active,
)

# ---- Arka Plan Cache Sistemi — background.py'den import edildi ----
# Modül referansı: cache veri değişkenleri _bg.xxx ile erişilir (Python name binding semantiği)
import web.background as _bg
from web.background import (
    update_workload_stats_cache,
    update_pods_summary_cache,
    update_pss_cache,
    update_netpol_coverage_cache,
    start_workload_stats_cache,
    start_pods_summary_cache,
    start_metrics_sampler,
    start_pss_cache,
    start_netpol_coverage_cache,
    _METRICS_TS,
    _METRICS_TS_LOCK,
    _evaluate_pod_pss_compliance,
    _pod_matches_pod_selector,
    _netpol_pod_selector_summary,
)

# ---- Blueprint: kubeconfigs (GET/POST/DELETE /kubeconfigs, POST /kubeconfigs/activate) ----
from web.blueprints.kubeconfigs import bp_kubeconfigs
app.register_blueprint(bp_kubeconfigs)

# ---- Blueprint: workloads (sayfa route'ları: /workloads, /config, /network, /storage, /nodes, /access-control, /configuration, /mesh, /mesh-data) ----
from web.blueprints.workloads import bp_workloads
app.register_blueprint(bp_workloads)

@app.route('/k8s-explorer/app-health')
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


@app.route('/set-locale')
def set_locale():
    lang = request.args.get('lang', 'tr')
    if lang not in ('tr', 'en'):
        lang = 'tr'
    next_url = request.args.get('next') or request.referrer or '/'
    resp = redirect(next_url)
    # 180 days
    resp.set_cookie('lang', lang, max_age=60*60*24*180, httponly=False, samesite='Lax')
    return resp

# HPA summary endpoint
@app.route('/k8s-explorer/hpa-summary')
def hpa_summary():
    try:
        namespace = request.args.get('namespace')
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        autoscaling_v1 = client.AutoscalingV1Api()
        if namespace and namespace != 'all':
            hpas = autoscaling_v1.list_namespaced_horizontal_pod_autoscaler(namespace).items
        else:
            hpas = autoscaling_v1.list_horizontal_pod_autoscaler_for_all_namespaces().items
        result = []
        for hpa in hpas:
            md = hpa.metadata
            spec = hpa.spec
            status = hpa.status
            result.append({
                'namespace': getattr(md, 'namespace', None),
                'name': getattr(md, 'name', None),
                'min_replicas': getattr(spec, 'min_replicas', None),
                'max_replicas': getattr(spec, 'max_replicas', None),
                'current_replicas': getattr(status, 'current_replicas', None),
                'desired_replicas': getattr(status, 'desired_replicas', None),
                'creation_timestamp': md.creation_timestamp.isoformat() if getattr(md, 'creation_timestamp', None) else None,
                'metrics': getattr(spec, 'metrics', None),
                'target_kind': getattr(spec.scale_target_ref, 'kind', None) if getattr(spec, 'scale_target_ref', None) else None,
                'target_name': getattr(spec.scale_target_ref, 'name', None) if getattr(spec, 'scale_target_ref', None) else None
            })
        return jsonify({'hpas': result})
    except Exception as e:
        return jsonify({'hpas': [], 'error': str(e)})

# Get a single HPA details
@app.route('/k8s-explorer/hpa')
def get_hpa():
    try:
        name = request.args.get('name')
        namespace = request.args.get('namespace')
        if not name or not namespace:
            return jsonify({'error': 'name and namespace are required'}), 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        autoscaling_v1 = client.AutoscalingV1Api()
        hpa = autoscaling_v1.read_namespaced_horizontal_pod_autoscaler(name=name, namespace=namespace)
        md = hpa.metadata
        spec = hpa.spec
        status = hpa.status
        return jsonify({'hpa': {
            'namespace': getattr(md, 'namespace', None),
            'name': getattr(md, 'name', None),
            'min_replicas': getattr(spec, 'min_replicas', None),
            'max_replicas': getattr(spec, 'max_replicas', None),
            'current_replicas': getattr(status, 'current_replicas', None),
            'desired_replicas': getattr(status, 'desired_replicas', None),
            'creation_timestamp': md.creation_timestamp.isoformat() if getattr(md, 'creation_timestamp', None) else None,
            'metrics': getattr(spec, 'metrics', None),
            'target_kind': getattr(spec.scale_target_ref, 'kind', None) if getattr(spec, 'scale_target_ref', None) else None,
            'target_name': getattr(spec.scale_target_ref, 'name', None) if getattr(spec, 'scale_target_ref', None) else None
        }})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Update HPA (min/max replicas)
@app.route('/k8s-explorer/update-hpa', methods=['POST'])
def update_hpa():
    try:
        data = request.get_json(force=True) or {}
        name = data.get('name')
        namespace = data.get('namespace')
        min_r = data.get('min_replicas')
        max_r = data.get('max_replicas')
        if not name or not namespace:
            return jsonify({'error': 'name and namespace are required'}), 400
        if min_r is None and max_r is None:
            return jsonify({'error': 'nothing to update'}), 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        autoscaling_v1 = client.AutoscalingV1Api()
        patch_spec = {}
        if min_r is not None:
            try:
                patch_spec['minReplicas'] = int(min_r)
            except Exception:
                return jsonify({'error': 'min_replicas must be an integer'}), 400
        if max_r is not None:
            try:
                patch_spec['maxReplicas'] = int(max_r)
            except Exception:
                return jsonify({'error': 'max_replicas must be an integer'}), 400
        patch_body = {'spec': patch_spec}
        autoscaling_v1.patch_namespaced_horizontal_pod_autoscaler(name=name, namespace=namespace, body=patch_body)
        return jsonify({'status': 'ok', 'name': name, 'namespace': namespace})
    except ApiException as e:
        try:
            return jsonify({'error': e.body}), e.status
        except Exception:
            return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Delete HPA
@app.route('/k8s-explorer/delete-hpa', methods=['POST'])
def delete_hpa():
    try:
        data = request.get_json(force=True) or {}
        name = data.get('name')
        namespace = data.get('namespace')
        if not name or not namespace:
            return jsonify({'error': 'name and namespace are required'}), 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        autoscaling_v1 = client.AutoscalingV1Api()
        autoscaling_v1.delete_namespaced_horizontal_pod_autoscaler(name=name, namespace=namespace)
        return jsonify({'status': 'deleted', 'name': name, 'namespace': namespace})
    except ApiException as e:
        try:
            return jsonify({'error': e.body}), e.status
        except Exception:
            return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# PDB summary endpoint
@app.route('/k8s-explorer/pdb-summary')
def pdb_summary():
    try:
        namespace = request.args.get('namespace')
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        policy_v1 = client.PolicyV1Api()
        if namespace and namespace not in ('all', None):
            pdbs = policy_v1.list_namespaced_pod_disruption_budget(namespace).items
        else:
            pdbs = policy_v1.list_pod_disruption_budget_for_all_namespaces().items
        result = []
        for pdb in pdbs:
            md = pdb.metadata
            spec = pdb.spec or {}
            status = pdb.status or {}
            min_avail = getattr(spec, 'min_available', None)
            max_unavail = getattr(spec, 'max_unavailable', None)
            def int_or_str(val):
                try:
                    return str(val)
                except Exception:
                    return None
            result.append({
                'namespace': getattr(md, 'namespace', None),
                'name': getattr(md, 'name', None),
                'min_available': int_or_str(min_avail),
                'max_unavailable': int_or_str(max_unavail),
                'disruptions_allowed': getattr(status, 'disruptions_allowed', None),
                'current_healthy': getattr(status, 'current_healthy', None),
                'desired_healthy': getattr(status, 'desired_healthy', None),
                'expected_pods': getattr(status, 'expected_pods', None),
                'creation_timestamp': md.creation_timestamp.isoformat() if getattr(md, 'creation_timestamp', None) else None,
                'selector': getattr(spec, 'selector', None).to_dict() if getattr(spec, 'selector', None) else None
            })
        return jsonify({'pdbs': result})
    except Exception as e:
        return jsonify({'pdbs': [], 'error': str(e)})

# Leases summary endpoint (namespaced)
@app.route('/k8s-explorer/leases-summary')
def leases_summary():
    try:
        namespace = request.args.get('namespace')
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        coord_v1 = client.CoordinationV1Api()
        if namespace and namespace not in ('all', None):
            leases = coord_v1.list_namespaced_lease(namespace).items
        else:
            leases = coord_v1.list_lease_for_all_namespaces().items
        def dt_to_iso(x):
            try:
                return x.isoformat() if getattr(x, 'isoformat', None) else (str(x) if x else None)
            except Exception:
                return None
        result = []
        for le in leases:
            md = le.metadata
            spec = getattr(le, 'spec', None)
            result.append({
                'namespace': getattr(md, 'namespace', None),
                'name': getattr(md, 'name', None),
                'holder_identity': getattr(spec, 'holder_identity', None) if spec else None,
                'lease_duration_seconds': getattr(spec, 'lease_duration_seconds', None) if spec else None,
                'acquire_time': dt_to_iso(getattr(spec, 'acquire_time', None)) if spec else None,
                'renew_time': dt_to_iso(getattr(spec, 'renew_time', None)) if spec else None,
                'lease_transitions': getattr(spec, 'lease_transitions', None) if spec else None,
                'creation_timestamp': md.creation_timestamp.isoformat() if getattr(md, 'creation_timestamp', None) else None
            })
        return jsonify({'leases': result})
    except Exception as e:
        return jsonify({'leases': [], 'error': str(e)})

# Mutating Webhooks summary (cluster-scoped; optional namespace filter by service namespace)
@app.route('/k8s-explorer/mutating-webhooks-summary')
def mutating_webhooks_summary():
    try:
        namespace = request.args.get('namespace')
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        ar = client.AdmissionregistrationV1Api()
        items = ar.list_mutating_webhook_configuration().items
        result = []
        for cfg in items:
            md = cfg.metadata
            webhooks = getattr(cfg, 'webhooks', []) or []
            services = []
            rules_count = 0
            failure_policies = set()
            for wh in webhooks:
                cc = getattr(wh, 'client_config', None)
                svc = getattr(cc, 'service', None) if cc else None
                if svc:
                    services.append({
                        'namespace': getattr(svc, 'namespace', None),
                        'name': getattr(svc, 'name', None),
                        'path': getattr(svc, 'path', None),
                        'port': getattr(svc, 'port', None),
                    })
                rules = getattr(wh, 'rules', None) or []
                rules_count += len(rules)
                if getattr(wh, 'failure_policy', None):
                    failure_policies.add(wh.failure_policy)
            if namespace and namespace not in ('all', None):
                if not any(s.get('namespace') == namespace for s in services):
                    continue
            result.append({
                'name': getattr(md, 'name', None),
                'webhooks_count': len(webhooks),
                'services': services,
                'rules_count': rules_count,
                'failure_policy': ','.join(sorted(failure_policies)) if failure_policies else None,
                'creation_timestamp': md.creation_timestamp.isoformat() if getattr(md, 'creation_timestamp', None) else None
            })
        return jsonify({'mutating_webhooks': result})
    except Exception as e:
        return jsonify({'mutating_webhooks': [], 'error': str(e)})

# Validating Webhooks summary (cluster-scoped; optional namespace filter by service namespace)
@app.route('/k8s-explorer/validating-webhooks-summary')
def validating_webhooks_summary():
    try:
        namespace = request.args.get('namespace')
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        ar = client.AdmissionregistrationV1Api()
        items = ar.list_validating_webhook_configuration().items
        result = []
        for cfg in items:
            md = cfg.metadata
            webhooks = getattr(cfg, 'webhooks', []) or []
            services = []
            rules_count = 0
            failure_policies = set()
            for wh in webhooks:
                cc = getattr(wh, 'client_config', None)
                svc = getattr(cc, 'service', None) if cc else None
                if svc:
                    services.append({
                        'namespace': getattr(svc, 'namespace', None),
                        'name': getattr(svc, 'name', None),
                        'path': getattr(svc, 'path', None),
                        'port': getattr(svc, 'port', None),
                    })
                rules = getattr(wh, 'rules', None) or []
                rules_count += len(rules)
                if getattr(wh, 'failure_policy', None):
                    failure_policies.add(wh.failure_policy)
            if namespace and namespace not in ('all', None):
                if not any(s.get('namespace') == namespace for s in services):
                    continue
            result.append({
                'name': getattr(md, 'name', None),
                'webhooks_count': len(webhooks),
                'services': services,
                'rules_count': rules_count,
                'failure_policy': ','.join(sorted(failure_policies)) if failure_policies else None,
                'creation_timestamp': md.creation_timestamp.isoformat() if getattr(md, 'creation_timestamp', None) else None
            })
        return jsonify({'validating_webhooks': result})
    except Exception as e:
        return jsonify({'validating_webhooks': [], 'error': str(e)})

# PriorityClasses summary endpoint (cluster-scoped)
@app.route('/k8s-explorer/priority-classes-summary')
def priority_classes_summary():
    try:
        _ = request.args.get('namespace')  # ignored
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        scheduling_v1 = client.SchedulingV1Api()
        pcs = scheduling_v1.list_priority_class().items
        result = []
        for pc in pcs:
            md = pc.metadata
            result.append({
                'name': getattr(md, 'name', None),
                'value': getattr(pc, 'value', None),
                'global_default': getattr(pc, 'global_default', None),
                'description': getattr(pc, 'description', None),
                'preemption_policy': getattr(pc, 'preemption_policy', None),
                'creation_timestamp': md.creation_timestamp.isoformat() if getattr(md, 'creation_timestamp', None) else None
            })
        return jsonify({'priority_classes': result})
    except Exception as e:
        return jsonify({'priority_classes': [], 'error': str(e)})

# RuntimeClasses summary endpoint (cluster-scoped)
@app.route('/k8s-explorer/runtime-classes-summary')
def runtime_classes_summary():
    try:
        _ = request.args.get('namespace')  # ignored
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        co = client.CustomObjectsApi()
        objs = co.list_cluster_custom_object(group="node.k8s.io", version="v1", plural="runtimeclasses")
        items = objs.get('items', [])
        result = []
        for rc in items:
            md = rc.get('metadata', {})
            spec = rc.get('spec', {})
            scheduling = spec.get('scheduling') or {}
            overhead = spec.get('overhead') or {}
            result.append({
                'name': md.get('name'),
                'handler': spec.get('handler'),
                'scheduling': {
                    'node_selector': scheduling.get('nodeSelector'),
                    'tolerations': scheduling.get('tolerations'),
                },
                'overhead': overhead,
                'creation_timestamp': md.get('creationTimestamp')
            })
        return jsonify({'runtime_classes': result})
    except Exception as e:
        return jsonify({'runtime_classes': [], 'error': str(e)})

# Get a single RuntimeClass details (cluster-scoped)
@app.route('/k8s-explorer/runtime-class')
def get_runtime_class():
    try:
        name = request.args.get('name')
        if not name:
            return jsonify({'error': 'name is required'}), 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        co = client.CustomObjectsApi()
        rc = co.get_cluster_custom_object(group="node.k8s.io", version="v1", plural="runtimeclasses", name=name)
        md = rc.get('metadata', {})
        spec = rc.get('spec', {})
        scheduling = spec.get('scheduling') or {}
        overhead = spec.get('overhead') or {}
        return jsonify({'runtime_class': {
            'name': md.get('name'),
            'handler': spec.get('handler'),
            'scheduling': {
                'node_selector': scheduling.get('nodeSelector'),
                'tolerations': scheduling.get('tolerations'),
            },
            'overhead': overhead,
            'creation_timestamp': md.get('creationTimestamp')
        }})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Update RuntimeClass (cluster-scoped)
@app.route('/k8s-explorer/update-runtime-class', methods=['POST'])
def update_runtime_class():
    try:
        data = request.get_json(force=True) or {}
        name = data.get('name')
        if not name:
            return jsonify({'error': 'name is required'}), 400

        # Handler genelde değiştirilmeyen bir alandır; güvenli tarafta kalarak reddedelim
        if 'handler' in data and data.get('handler') not in (None, ''):
            return jsonify({'error': 'RuntimeClass.handler güncellenemez. Gerekirse yeni bir RuntimeClass oluşturun.'}), 400

        node_selector_str = data.get('node_selector')  # e.g. "k=v,k2=v2"
        tolerations_json = data.get('tolerations')     # array or JSON string
        overhead_json = data.get('overhead')           # dict or JSON string

        # Build patch
        patch_spec = {}
        sched = {}

        # nodeSelector parse
        if node_selector_str is not None:
            if node_selector_str == '':
                sched['nodeSelector'] = None
            else:
                try:
                    node_selector = {}
                    for pair in [p.strip() for p in node_selector_str.split(',') if p.strip()]:
                        if '=' in pair:
                            k, v = pair.split('=', 1)
                            node_selector[k.strip()] = v.strip()
                        else:
                            return jsonify({'error': f'Geçersiz nodeSelector girdisi: {pair} (k=v formatı)'}), 400
                    sched['nodeSelector'] = node_selector
                except Exception as pe:
                    return jsonify({'error': f'nodeSelector parse hatası: {pe}'}), 400

        # tolerations parse
        if tolerations_json is not None:
            if isinstance(tolerations_json, str):
                if tolerations_json.strip() == '':
                    sched['tolerations'] = None
                else:
                    try:
                        parsed = json.loads(tolerations_json)
                        if not isinstance(parsed, list):
                            return jsonify({'error': 'tolerations JSON bir dizi olmalı'}), 400
                        sched['tolerations'] = parsed
                    except Exception as je:
                        return jsonify({'error': f'tolerations JSON hatası: {je}'}), 400
            else:
                # assume array or None
                if tolerations_json == '':
                    sched['tolerations'] = None
                else:
                    sched['tolerations'] = tolerations_json

        if sched:
            patch_spec['scheduling'] = sched

        # overhead parse
        if overhead_json is not None:
            if isinstance(overhead_json, str):
                if overhead_json.strip() == '':
                    patch_spec['overhead'] = None
                else:
                    try:
                        parsed = json.loads(overhead_json)
                        if not isinstance(parsed, dict):
                            return jsonify({'error': 'overhead JSON bir nesne olmalı'}), 400
                        patch_spec['overhead'] = parsed
                    except Exception as je:
                        return jsonify({'error': f'overhead JSON hatası: {je}'}), 400
            else:
                if overhead_json == '':
                    patch_spec['overhead'] = None
                else:
                    patch_spec['overhead'] = overhead_json

        if not patch_spec:
            return jsonify({'error': 'nothing to update'}), 400

        patch_body = { 'spec': patch_spec }

        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        co = client.CustomObjectsApi()
        co.patch_cluster_custom_object(group="node.k8s.io", version="v1", plural="runtimeclasses", name=name, body=patch_body)
        return jsonify({'status': 'ok', 'name': name})
    except ApiException as e:
        try:
            return jsonify({'error': e.body}), e.status
        except Exception:
            return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Delete RuntimeClass (cluster-scoped)
@app.route('/k8s-explorer/delete-runtime-class', methods=['POST'])
def delete_runtime_class():
    try:
        data = request.get_json(force=True) or {}
        name = data.get('name')
        if not name:
            return jsonify({'error': 'name is required'}), 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        co = client.CustomObjectsApi()
        co.delete_cluster_custom_object(group="node.k8s.io", version="v1", plural="runtimeclasses", name=name)
        return jsonify({'status': 'deleted', 'name': name})
    except ApiException as e:
        try:
            return jsonify({'error': e.body}), e.status
        except Exception:
            return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Get a single PriorityClass details (cluster-scoped)
@app.route('/k8s-explorer/priority-class')
def get_priority_class():
    try:
        name = request.args.get('name')
        if not name:
            return jsonify({'error': 'name is required'}), 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        scheduling_v1 = client.SchedulingV1Api()
        pc = scheduling_v1.read_priority_class(name=name)
        md = pc.metadata
        return jsonify({'priority_class': {
            'name': getattr(md, 'name', None),
            'value': getattr(pc, 'value', None),
            'global_default': getattr(pc, 'global_default', None),
            'description': getattr(pc, 'description', None),
            'preemption_policy': getattr(pc, 'preemption_policy', None),
            'creation_timestamp': md.creation_timestamp.isoformat() if getattr(md, 'creation_timestamp', None) else None
        }})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Update PriorityClass (cluster-scoped)
@app.route('/k8s-explorer/update-priority-class', methods=['POST'])
def update_priority_class():
    try:
        data = request.get_json(force=True) or {}
        name = data.get('name')
        if not name:
            return jsonify({'error': 'name is required'}), 400

        # Optional fields
        value = data.get('value')
        global_default = data.get('global_default')
        preemption_policy = data.get('preemption_policy')
        description = data.get('description')

        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        scheduling_v1 = client.SchedulingV1Api()

        patch_body = {}

        # PriorityClass.spec.value field is immutable and cannot be updated
        if value not in (None, ''):
            return jsonify({'error': 'PriorityClass.value güncellenemez. Yeni bir PriorityClass oluşturun veya mevcut nesneyi silip yeniden yaratın.'}), 400

        # Only set globalDefault if provided and not empty string
        if global_default is not None and global_default != '':
            if isinstance(global_default, str):
                gd = global_default.strip().lower() in ['true', '1', 'yes', 'on']
            else:
                gd = bool(global_default)
            patch_body['globalDefault'] = gd

        # preemptionPolicy: empty string clears the field, None means no change
        if preemption_policy is not None:
            patch_body['preemptionPolicy'] = preemption_policy if preemption_policy != '' else None

        # description: empty string clears
        if description is not None:
            patch_body['description'] = description if description != '' else None

        if not patch_body:
            return jsonify({'error': 'nothing to update'}), 400

        scheduling_v1.patch_priority_class(name=name, body=patch_body)
        return jsonify({'status': 'ok', 'name': name})
    except ApiException as e:
        try:
            return jsonify({'error': e.body}), e.status
        except Exception:
            return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Delete PriorityClass (cluster-scoped)
@app.route('/k8s-explorer/delete-priority-class', methods=['POST'])
def delete_priority_class():
    try:
        data = request.get_json(force=True) or {}
        name = data.get('name')
        if not name:
            return jsonify({'error': 'name is required'}), 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        scheduling_v1 = client.SchedulingV1Api()
        scheduling_v1.delete_priority_class(name=name)
        return jsonify({'status': 'deleted', 'name': name})
    except ApiException as e:
        try:
            return jsonify({'error': e.body}), e.status
        except Exception:
            return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Get a single PDB details
@app.route('/k8s-explorer/pdb')
def get_pdb():
    try:
        name = request.args.get('name')
        namespace = request.args.get('namespace')
        if not name or not namespace:
            return jsonify({'error': 'name and namespace are required'}), 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        policy_v1 = client.PolicyV1Api()
        pdb = policy_v1.read_namespaced_pod_disruption_budget(name=name, namespace=namespace)
        md = pdb.metadata
        spec = pdb.spec or {}
        status = pdb.status or {}
        def int_or_str(val):
            try:
                return str(val) if val is not None else None
            except Exception:
                return None
        return jsonify({'pdb': {
            'namespace': getattr(md, 'namespace', None),
            'name': getattr(md, 'name', None),
            'min_available': int_or_str(getattr(spec, 'min_available', None)),
            'max_unavailable': int_or_str(getattr(spec, 'max_unavailable', None)),
            'disruptions_allowed': getattr(status, 'disruptions_allowed', None),
            'current_healthy': getattr(status, 'current_healthy', None),
            'desired_healthy': getattr(status, 'desired_healthy', None),
            'expected_pods': getattr(status, 'expected_pods', None),
            'creation_timestamp': md.creation_timestamp.isoformat() if getattr(md, 'creation_timestamp', None) else None,
            'selector': getattr(spec, 'selector', None).to_dict() if getattr(spec, 'selector', None) else None
        }})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Update PDB (minAvailable/maxUnavailable)
@app.route('/k8s-explorer/update-pdb', methods=['POST'])
def update_pdb():
    try:
        data = request.get_json(force=True) or {}
        name = data.get('name')
        namespace = data.get('namespace')
        min_av = data.get('min_available')
        max_un = data.get('max_unavailable')
        if not name or not namespace:
            return jsonify({'error': 'name and namespace are required'}), 400
        if (min_av is None or min_av == '') and (max_un is None or max_un == ''):
            return jsonify({'error': 'nothing to update'}), 400

        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        policy_v1 = client.PolicyV1Api()

        def parse_int_or_str(v):
            if v is None or v == '':
                return None
            # If purely digits, send as int; else keep as string (supports percentages like '50%')
            try:
                if isinstance(v, (int, float)) or (isinstance(v, str) and v.strip().isdigit()):
                    return int(v)
            except Exception:
                pass
            return str(v)

        patch_spec = {}
        pav = parse_int_or_str(min_av)
        pmax = parse_int_or_str(max_un)

        # Validate: Kubernetes PDB allows only one of minAvailable or maxUnavailable
        if pav is not None and pmax is not None:
            return jsonify({'error': 'min_available ve max_unavailable aynı anda ayarlanamaz. Yalnızca birini doldurun.'}), 400

        # If setting one, ensure the other is cleared to avoid server-side validation errors
        if pav is not None:
            patch_spec['minAvailable'] = pav
            # If max was provided as empty or missing, explicitly clear it
            if max_un == '' or max_un is None:
                patch_spec['maxUnavailable'] = None
        if pmax is not None:
            patch_spec['maxUnavailable'] = pmax
            if min_av == '' or min_av is None:
                patch_spec['minAvailable'] = None

        patch_body = {'spec': patch_spec}
        policy_v1.patch_namespaced_pod_disruption_budget(name=name, namespace=namespace, body=patch_body)
        return jsonify({'status': 'ok', 'name': name, 'namespace': namespace})
    except ApiException as e:
        try:
            return jsonify({'error': e.body}), e.status
        except Exception:
            return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Delete PDB
@app.route('/k8s-explorer/delete-pdb', methods=['POST'])
def delete_pdb():
    try:
        data = request.get_json(force=True) or {}
        name = data.get('name')
        namespace = data.get('namespace')
        if not name or not namespace:
            return jsonify({'error': 'name and namespace are required'}), 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        policy_v1 = client.PolicyV1Api()
        policy_v1.delete_namespaced_pod_disruption_budget(name=name, namespace=namespace)
        return jsonify({'status': 'deleted', 'name': name, 'namespace': namespace})
    except ApiException as e:
        try:
            return jsonify({'error': e.body}), e.status
        except Exception:
            return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Prometheus endpoint bilgisi (frontend rehberlik eder; gerçek çağrılar backend proxy üzerinden yapılır)
@app.route('/k8s-explorer/prometheus-url')
def prometheus_url():
    try:
        manual_url = request.args.get('prometheus') or os.environ.get('PROMETHEUS_URL')
        if manual_url:
            return jsonify({'mode': 'manual', 'url': manual_url})
        # Varsayılan olarak backend proxy kullanılır
        return jsonify({'mode': 'proxy', 'url': '/k8s-explorer/prometheus-proxy'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Prometheus dahili proxy (Kubernetes API service-proxy üzerinden)
@app.route('/k8s-explorer/prometheus-proxy')
def prometheus_proxy():
    """Prometheus HTTP API için dahili proxy.
    Desteklenen parametreler: path=query|query_range, query, start, end, step, prometheus (opsiyonel override)
    Öncelik: Kubernetes API service-proxy → manuel URL.
    """
    try:
        api_path = (request.args.get('path') or 'query').strip()
        if api_path not in ('query', 'query_range'):
            return jsonify({'error': 'path sadece query veya query_range olabilir'}), 400
        query = request.args.get('query') or ''
        start = request.args.get('start')
        end = request.args.get('end')
        step = request.args.get('step')
        manual_url = request.args.get('prometheus') or os.environ.get('PROMETHEUS_URL')

        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)

        core_v1 = client.CoreV1Api()
        api_client = client.ApiClient()

        def detect_prom_service_targets(max_targets: int = 8):
            targets = []  # (ns, svc, port_designator)
            try:
                all_ns = [ns.metadata.name for ns in core_v1.list_namespace().items]
                prio = ['monitoring', 'prometheus', 'observability', 'default', 'kube-system']
                ordered_ns = prio + [n for n in all_ns if n not in prio]
                for nsn in ordered_ns:
                    for svc in core_v1.list_namespaced_service(nsn).items:
                        name_s = (svc.metadata.name or '').lower()
                        labels = {k.lower(): (v.lower() if isinstance(v, str) else v) for k, v in ((svc.metadata.labels or {}).items())}
                        looks = ('prometheus' in name_s) or any(isinstance(v, str) and 'prometheus' in v for v in (labels or {}).values())
                        if not looks:
                            continue
                        ports = svc.spec.ports or []
                        pref_names = ['web', 'http', 'http-web', 'prometheus']
                        port_obj = None
                        for p in ports:
                            pname = (getattr(p, 'name', '') or '').lower()
                            if pname in pref_names or getattr(p, 'port', None) == 9090:
                                port_obj = p; break
                        if not port_obj and ports:
                            port_obj = ports[0]
                        if not port_obj:
                            continue
                        port_designator = getattr(port_obj, 'name', None) or getattr(port_obj, 'port', None)
                        if not port_designator:
                            continue
                        targets.append((nsn, svc.metadata.name, str(port_designator)))
                        if len(targets) >= max_targets:
                            raise StopIteration
            except StopIteration:
                pass
            except Exception:
                pass
            # de-dup
            seen = set(); out = []
            for t in targets:
                key = (t[0], t[1], t[2])
                if key not in seen:
                    out.append(t); seen.add(key)
            return out

        def prom_call_via_proxy(ns: str, svc: str, port: str, path_suffix: str, qp: list, timeout_s: float = 3.0):
            for scheme in ['http', 'https']:
                try:
                    p = f'/api/v1/namespaces/{ns}/services/{scheme}:{svc}:{port}/proxy/api/v1/{path_suffix}'
                    resp = api_client.call_api(p, 'GET', query_params=qp, auth_settings=['BearerToken'], _preload_content=False, request_timeout=timeout_s)[0]
                    body = resp.data.decode('utf-8') if hasattr(resp, 'data') else str(resp)
                    j = json.loads(body)
                    if j.get('status') == 'success':
                        return j, f'k8s-proxy://{scheme}:{svc}:{port} (ns {ns})'
                except Exception:
                    continue
            return None, None

        qp = []
        if query:
            qp.append(('query', query))
        if api_path == 'query_range':
            # start/end/step gereklidir
            if not start or not end or not step:
                return jsonify({'error': 'query_range için start, end ve step zorunlu'}), 400
            qp.extend([('start', start), ('end', end), ('step', step)])

        # 1) Kubernetes API service-proxy ile dene
        try:
            start_budget = time.time(); budget = 5.0
            for ns_s, svc_s, port_s in detect_prom_service_targets():
                if time.time() - start_budget > budget:
                    break
                j, ep = prom_call_via_proxy(ns_s, svc_s, port_s, api_path, qp, timeout_s=2.5)
                if j:
                    return jsonify({'source': 'prometheus', 'endpoint': ep, **j})
        except Exception:
            pass

        # 2) Manuel URL (opsiyonel)
        if manual_url:
            try:
                r = requests.get(f"{manual_url.rstrip('/')}/api/v1/{api_path}", params=qp, timeout=3.0, verify=False)
                if r.status_code == 200:
                    j = r.json()
                    return jsonify({'source': 'prometheus', 'endpoint': manual_url, **j})
            except Exception:
                pass

        return jsonify({'error': 'Prometheus erişilemedi (proxy/manual)'}), 502
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# StatefulSets summary for StatefulSets tab
@app.route('/k8s-explorer/statefulsets-summary')
def statefulsets_summary():
    try:
        namespace = request.args.get('namespace')
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        apps_v1 = client.AppsV1Api()
        if namespace:
            statefulsets = apps_v1.list_namespaced_stateful_set(namespace).items
        else:
            statefulsets = apps_v1.list_stateful_set_for_all_namespaces().items
        result = []
        for ss in statefulsets:
            ready = getattr(ss.status, 'ready_replicas', 0) or 0
            replicas = getattr(ss.status, 'replicas', 0) or 0
            creation_timestamp = getattr(ss.metadata, 'creation_timestamp', None)
            result.append({
                'namespace': ss.metadata.namespace,
                'name': ss.metadata.name,
                'ready': f"{ready}/{replicas}",
                'replicas': replicas,
                'creation_timestamp': creation_timestamp.isoformat() if creation_timestamp else None
            })
        return jsonify({'statefulsets': result})
    except Exception as e:
        return jsonify({'statefulsets': [], 'error': str(e)})

@app.route('/k8s-explorer/statefulset-properties')
def statefulset_properties():
    """Return detailed properties for a single StatefulSet."""
    namespace = request.args.get('namespace')
    name = request.args.get('name')
    if not namespace or not name:
        return jsonify({'error': 'namespace ve name zorunlu'}), 400
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        apps_v1 = client.AppsV1Api()
        ss = apps_v1.read_namespaced_stateful_set(name=name, namespace=namespace)
        md = ss.metadata
        spec = ss.spec
        status = ss.status
        tpl_spec = spec.template.spec if spec and spec.template else None
        containers = tpl_spec.containers if tpl_spec else []
        def to_dict_container(cn):
            resources = getattr(cn, 'resources', None)
            sec = getattr(cn, 'security_context', None)
            return {
                'name': cn.name,
                'image': cn.image,
                'image_pull_policy': getattr(cn, 'image_pull_policy', None),
                'ports': [p.container_port for p in (cn.ports or [])] if getattr(cn, 'ports', None) else [],
                'env': [{ 'name': e.name, 'value': getattr(e, 'value', None)} for e in (cn.env or [])] if getattr(cn, 'env', None) else [],
                'resources': {
                    'limits': getattr(resources, 'limits', None) if resources else None,
                    'requests': getattr(resources, 'requests', None) if resources else None
                },
                'security_context': {
                    'run_as_user': getattr(sec, 'run_as_user', None) if sec else None,
                    'read_only_root_filesystem': getattr(sec, 'read_only_root_filesystem', None) if sec else None,
                    'allow_privilege_escalation': getattr(sec, 'allow_privilege_escalation', None) if sec else None,
                } if sec else None,
                'liveness_probe': bool(getattr(cn, 'liveness_probe', None)),
                'readiness_probe': bool(getattr(cn, 'readiness_probe', None)),
            }
        result = {
            'metadata': {
                'name': md.name,
                'namespace': md.namespace,
                'labels': md.labels or {},
                'annotations': md.annotations or {},
                'creation_timestamp': md.creation_timestamp.isoformat() if getattr(md, 'creation_timestamp', None) else None,
            },
            'spec': {
                'replicas': getattr(spec, 'replicas', None),
                'service_name': getattr(spec, 'service_name', None),
                'pod_management_policy': getattr(spec, 'pod_management_policy', None),
                'update_strategy': getattr(getattr(spec, 'update_strategy', None), 'type', None),
                'selector': getattr(getattr(spec, 'selector', None), 'match_labels', None),
                'containers': [to_dict_container(cn) for cn in (containers or [])]
            },
            'status': {
                'replicas': getattr(status, 'replicas', None),
                'ready_replicas': getattr(status, 'ready_replicas', None),
                'current_replicas': getattr(status, 'current_replicas', None),
                'updated_replicas': getattr(status, 'updated_replicas', None),
                'collision_count': getattr(status, 'collision_count', None),
                'conditions': [
                    {
                        'type': c.type,
                        'status': c.status,
                        'reason': getattr(c, 'reason', None),
                        'message': getattr(c, 'message', None),
                        'last_transition_time': getattr(c, 'last_transition_time', None).isoformat() if getattr(c, 'last_transition_time', None) else None
                    } for c in (getattr(status, 'conditions', []) or [])
                ]
            }
        }
        return jsonify({'statefulset': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# StatefulSet restart API
@app.route('/k8s-explorer/restart-statefulset', methods=['POST'])
def restart_statefulset():
    try:
        data = request.get_json(force=True)
        namespace = data.get('namespace')
        name = data.get('name')
        if not namespace or not name:
            return jsonify({'error': 'namespace ve name zorunlu'}), 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        apps_v1 = client.AppsV1Api()
        # Patch StatefulSet's pod template annotation to trigger restart
        now = datetime.utcnow().isoformat() + 'Z'
        patch = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": now
                        }
                    }
                }
            }
        }
        apps_v1.patch_namespaced_stateful_set(name, namespace, patch)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# StatefulSet logs API
@app.route('/k8s-explorer/statefulset-logs')
def statefulset_logs():
    try:
        namespace = request.args.get('namespace')
        name = request.args.get('name')
        mode = request.args.get('mode')
        if not namespace or not name:
            return jsonify({'error': 'namespace ve name zorunlu'}), 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        core_v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()
        # Get StatefulSet to find its selector
        ss = apps_v1.read_namespaced_stateful_set(name, namespace)
        selector = ss.spec.selector.match_labels
        # List pods matching selector
        label_selector = ','.join([f"{k}={v}" for k,v in selector.items()])
        pods = core_v1.list_namespaced_pod(namespace, label_selector=label_selector).items
        if not pods:
            return jsonify({'logs': 'Bu StatefulSet\'e ait pod bulunamadı.'})
        if mode == 'perpod':
            pod_logs = {}
            for pod in pods:
                pod_name = pod.metadata.name
                containers = [c.name for c in (pod.spec.containers or [])]
                container_arg = {'container': containers[0]} if containers else {}
                try:
                    pod_log = core_v1.read_namespaced_pod_log(name=pod_name, namespace=namespace, tail_lines=200, **container_arg)
                except Exception as e:
                    pod_log = f'Log alınamadı: {e}'
                pod_logs[pod_name] = pod_log
            return jsonify({'pod_logs': pod_logs})
        else:
            logs = ''
            for pod in pods:
                pod_name = pod.metadata.name
                containers = [c.name for c in (pod.spec.containers or [])]
                container_arg = {'container': containers[0]} if containers else {}
                try:
                    pod_log = core_v1.read_namespaced_pod_log(name=pod_name, namespace=namespace, tail_lines=200, **container_arg)
                except Exception as e:
                    pod_log = f'Log alınamadı: {e}'
                logs += f"\n===== {pod_name} =====\n{pod_log}\n"
            return jsonify({'logs': logs})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# StatefulSet scale API
@app.route('/k8s-explorer/scale-statefulset', methods=['POST'])
def scale_statefulset():
    try:
        data = request.get_json(force=True)
        namespace = data.get('namespace')
        name = data.get('name')
        replicas = data.get('replicas')
        if not namespace or not name or replicas is None:
            return jsonify({'error': 'namespace, name ve replicas zorunlu'}), 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        apps_v1 = client.AppsV1Api()
        # Patch the statefulset with new replica count
        body = {"spec": {"replicas": int(replicas)}}
        apps_v1.patch_namespaced_stateful_set_scale(name, namespace, body)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# DaemonSets summary for DaemonSets tab
@app.route('/k8s-explorer/daemonsets-summary')
def daemonsets_summary():
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        apps_v1 = client.AppsV1Api()
        daemonsets = apps_v1.list_daemon_set_for_all_namespaces().items
        result = []
        for ds in daemonsets:
            desired = getattr(ds.status, 'desired_number_scheduled', 0)
            ready = getattr(ds.status, 'number_ready', 0)
            current = getattr(ds.status, 'current_number_scheduled', 0)
            creation_timestamp = getattr(ds.metadata, 'creation_timestamp', None)
            result.append({
                'namespace': ds.metadata.namespace,
                'name': ds.metadata.name,
                'ready': f"{ready}/{desired}",
                'current': current,
                'desired': desired,
                'creation_timestamp': creation_timestamp.isoformat() if creation_timestamp else None
            })
        return jsonify({'daemonsets': result})
    except Exception as e:
        return jsonify({'daemonsets': [], 'error': str(e)})

@app.route('/k8s-explorer/daemonset-properties')
def daemonset_properties():
    """Return detailed properties for a single DaemonSet."""
    namespace = request.args.get('namespace')
    name = request.args.get('name')
    if not namespace or not name:
        return jsonify({'error': 'namespace ve name zorunlu'}), 400
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        apps_v1 = client.AppsV1Api()
        ds = apps_v1.read_namespaced_daemon_set(name=name, namespace=namespace)
        md = ds.metadata
        spec = ds.spec
        status = ds.status
        tpl_spec = spec.template.spec if spec and spec.template else None
        containers = tpl_spec.containers if tpl_spec else []
        def to_dict_container(cn):
            resources = getattr(cn, 'resources', None)
            sec = getattr(cn, 'security_context', None)
            return {
                'name': cn.name,
                'image': cn.image,
                'image_pull_policy': getattr(cn, 'image_pull_policy', None),
                'ports': [p.container_port for p in (cn.ports or [])] if getattr(cn, 'ports', None) else [],
                'env': [{ 'name': e.name, 'value': getattr(e, 'value', None)} for e in (cn.env or [])] if getattr(cn, 'env', None) else [],
                'resources': {
                    'limits': getattr(resources, 'limits', None) if resources else None,
                    'requests': getattr(resources, 'requests', None) if resources else None
                },
                'security_context': {
                    'run_as_user': getattr(sec, 'run_as_user', None) if sec else None,
                    'read_only_root_filesystem': getattr(sec, 'read_only_root_filesystem', None) if sec else None,
                    'allow_privilege_escalation': getattr(sec, 'allow_privilege_escalation', None) if sec else None,
                } if sec else None,
                'liveness_probe': bool(getattr(cn, 'liveness_probe', None)),
                'readiness_probe': bool(getattr(cn, 'readiness_probe', None)),
            }
        result = {
            'metadata': {
                'name': md.name,
                'namespace': md.namespace,
                'labels': md.labels or {},
                'annotations': md.annotations or {},
                'creation_timestamp': md.creation_timestamp.isoformat() if getattr(md, 'creation_timestamp', None) else None,
            },
            'spec': {
                'selector': getattr(spec.selector, 'match_labels', None) if getattr(spec, 'selector', None) else None,
                'update_strategy': getattr(getattr(spec, 'update_strategy', None), 'type', None),
                'min_ready_seconds': getattr(spec, 'min_ready_seconds', None),
                'revision_history_limit': getattr(spec, 'revision_history_limit', None),
                'containers': [to_dict_container(cn) for cn in (containers or [])]
            },
            'status': {
                'desired_number_scheduled': getattr(status, 'desired_number_scheduled', None),
                'current_number_scheduled': getattr(status, 'current_number_scheduled', None),
                'number_ready': getattr(status, 'number_ready', None),
                'number_available': getattr(status, 'number_available', None),
                'number_unavailable': getattr(status, 'number_unavailable', None),
                'updated_number_scheduled': getattr(status, 'updated_number_scheduled', None),
                'conditions': [
                    {
                        'type': c.type,
                        'status': c.status,
                        'reason': getattr(c, 'reason', None),
                        'message': getattr(c, 'message', None),
                        'last_transition_time': getattr(c, 'last_transition_time', None).isoformat() if getattr(c, 'last_transition_time', None) else None
                    } for c in (getattr(status, 'conditions', []) or [])
                ]
            }
        }
        return jsonify({'daemonset': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# DaemonSet restart API
@app.route('/k8s-explorer/restart-daemonset', methods=['POST'])
def restart_daemonset():
    try:
        data = request.get_json(force=True)
        namespace = data.get('namespace')
        name = data.get('name')
        if not namespace or not name:
            return jsonify({'error': 'namespace ve name zorunlu'}), 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        apps_v1 = client.AppsV1Api()
        # Patch DaemonSet's pod template annotation to trigger restart
        now = datetime.utcnow().isoformat() + 'Z'
        patch = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": now
                        }
                    }
                }
            }
        }
        apps_v1.patch_namespaced_daemon_set(name, namespace, patch)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# DaemonSet logs API
@app.route('/k8s-explorer/daemonset-logs')
def daemonset_logs():
    try:
        namespace = request.args.get('namespace')
        name = request.args.get('name')
        mode = request.args.get('mode')
        if not namespace or not name:
            return jsonify({'error': 'namespace ve name zorunlu'}), 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        core_v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()
        # Get DaemonSet to find its selector
        ds = apps_v1.read_namespaced_daemon_set(name, namespace)
        selector = ds.spec.selector.match_labels
        # List pods matching selector
        label_selector = ','.join([f"{k}={v}" for k,v in selector.items()])
        pods = core_v1.list_namespaced_pod(namespace, label_selector=label_selector).items
        if not pods:
            return jsonify({'logs': 'Bu DaemonSet\'e ait pod bulunamadı.'})
        if mode == 'perpod':
            pod_logs = {}
            for pod in pods:
                pod_name = pod.metadata.name
                try:
                    pod_log = core_v1.read_namespaced_pod_log(name=pod_name, namespace=namespace, tail_lines=200)
                except Exception as e:
                    pod_log = f'Log alınamadı: {e}'
                pod_logs[pod_name] = pod_log
            return jsonify({'pod_logs': pod_logs})
        else:
            logs = ''
            for pod in pods:
                pod_name = pod.metadata.name
                try:
                    pod_log = core_v1.read_namespaced_pod_log(name=pod_name, namespace=namespace, tail_lines=200)
                except Exception as e:
                    pod_log = f'Log alınamadı: {e}'
                logs += f"\n===== {pod_name} =====\n{pod_log}\n"
            return jsonify({'logs': logs})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Deployment scale API
@app.route('/k8s-explorer/scale-deployment', methods=['POST'])
def scale_deployment():
    try:
        data = request.get_json(force=True)
        namespace = data.get('namespace')
        name = data.get('name')
        replicas = data.get('replicas')
        if not namespace or not name or replicas is None:
            return jsonify({'error': 'namespace, name ve replicas zorunlu'}), 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        apps_v1 = client.AppsV1Api()
        # Patch the deployment with new replica count
        body = {"spec": {"replicas": int(replicas)}}
        apps_v1.patch_namespaced_deployment_scale(name, namespace, body)
        # Immediately refresh pods and workload stats caches so frontend reflects new replica count
        try:
            update_pods_summary_cache()
        except Exception:
            pass
        try:
            update_workload_stats_cache()
        except Exception:
            pass
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/k8s-explorer/restart-pod', methods=['POST'])
def restart_pod():
    try:
        data = request.get_json(force=True)
        namespace = data.get('namespace')
        name = data.get('name')
        if not namespace or not name:
            return jsonify({'error': 'namespace ve name zorunlu'}), 400
        
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        
        v1 = client.CoreV1Api()
        # Delete the pod to restart it (it will be recreated by the controller)
        v1.delete_namespaced_pod(name=name, namespace=namespace)
        # Update pods summary cache immediately so frontend sees change
        try:
            update_pods_summary_cache()
        except Exception:
            pass
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/k8s-explorer/restart-deployment', methods=['POST'])
def restart_deployment():
    try:
        data = request.get_json(force=True)
        namespace = data.get('namespace')
        name = data.get('name')
        if not namespace or not name:
            return jsonify({'error': 'namespace ve name zorunlu'}), 400
        
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        
        apps_v1 = client.AppsV1Api()
        # Patch deployment's pod template annotation to trigger restart
        now = datetime.utcnow().isoformat() + 'Z'
        patch = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": now
                        }
                    }
                }
            }
        }
        apps_v1.patch_namespaced_deployment(name, namespace, patch)
        # Immediately refresh pods and workload stats caches so frontend reflects restarted pods
        try:
            update_pods_summary_cache()
        except Exception:
            pass
        try:
            update_workload_stats_cache()
        except Exception:
            pass
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/k8s-explorer/pod-properties')
def pod_properties():
    """Return detailed properties for a single Pod."""
    namespace = request.args.get('namespace')
    name = request.args.get('name')
    if not namespace or not name:
        return jsonify({'error': 'namespace ve name zorunlu'}), 400
    
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        
        v1 = client.CoreV1Api()
        pod = v1.read_namespaced_pod(name=name, namespace=namespace)
        
        containers = []
        if pod.spec.containers:
            for container in pod.spec.containers:
                container_status = None
                if pod.status.container_statuses:
                    container_status = next((cs for cs in pod.status.container_statuses if cs.name == container.name), None)

                # Extract resources (requests/limits) if present
                reqs = {}
                lims = {}
                try:
                    if getattr(container, 'resources', None):
                        if getattr(container.resources, 'requests', None):
                            reqs = dict(container.resources.requests)
                        if getattr(container.resources, 'limits', None):
                            lims = dict(container.resources.limits)
                except Exception:
                    pass

                containers.append({
                    'name': container.name,
                    'image': container.image,
                    'restart_count': container_status.restart_count if container_status else 0,
                    'resources': {
                        'requests': reqs,
                        'limits': lims
                    }
                })
        
        result = {
            'namespace': pod.metadata.namespace,
            'name': pod.metadata.name,
            'status': pod.status.phase,
            'node': pod.spec.node_name,
            'creation_timestamp': pod.metadata.creation_timestamp.isoformat() if pod.metadata.creation_timestamp else None,
            'containers': containers
        }
        
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/k8s-explorer/pod-metrics')
def pod_metrics():
    """Return current CPU/Memory usage for a Pod.
    Prefers Prometheus (via k8s service-proxy or direct service discovery) with optional manual override;
    otherwise falls back to metrics-server (metrics.k8s.io).
    Response: { source: 'prometheus'|'metrics-server'|'none', cpu_mcores: int, memory_bytes: int, containers: [{name, cpu_mcores, memory_bytes}], endpoint? }
    """
    try:
        namespace = request.args.get('namespace')
        name = request.args.get('name')
        if not namespace or not name:
            return jsonify({'error': 'namespace ve name zorunlu'}), 400

        manual_url = request.args.get('prometheus') or os.environ.get('PROMETHEUS_URL')

        load_kube_config_active()
        c = client.Configuration.get_default_copy(); c.verify_ssl = False; c.assert_hostname = False; client.Configuration.set_default(c)
        core_v1 = client.CoreV1Api(); api_client = client.ApiClient()

        q_cpu = f'sum(rate(container_cpu_usage_seconds_total{{namespace="{namespace}",pod="{name}",container!="",image!=""}}[5m]))'
        q_mem = f'sum(container_memory_working_set_bytes{{namespace="{namespace}",pod="{name}",container!="",image!=""}})'

        def prom_query(base_url: str, query: str, timeout_s: float = 2.0):
            r = requests.get(f"{base_url.rstrip('/')}/api/v1/query", params={'query': query}, timeout=timeout_s, verify=False)
            if r.status_code != 200:
                return None
            return r.json()

        # 1) Manual override
        if manual_url:
            try:
                d1 = prom_query(manual_url, q_cpu, timeout_s=2.0)
                d2 = prom_query(manual_url, q_mem, timeout_s=2.0)
                res1 = (d1.get('data', {}) or {}).get('result', []) if d1 else []
                res2 = (d2.get('data', {}) or {}).get('result', []) if d2 else []
                if res1 or res2:
                    cpu_val = float(res1[0]['value'][1]) if res1 else 0.0
                    mem_val = float(res2[0]['value'][1]) if res2 else 0.0
                    return jsonify({'source': 'prometheus', 'cpu_mcores': int(round(cpu_val * 1000)), 'memory_bytes': int(round(mem_val)), 'endpoint': manual_url})
            except Exception:
                pass

        # 2) Via k8s API service-proxy
        def detect_prom_service_targets(max_targets: int = 8):
            targets = []
            try:
                all_ns = [ns.metadata.name for ns in core_v1.list_namespace().items]
                prio = ['monitoring', 'prometheus', 'observability', 'default', 'kube-system']
                ordered_ns = prio + [n for n in all_ns if n not in prio]
                for nsn in ordered_ns:
                    for svc in core_v1.list_namespaced_service(nsn).items:
                        name_s = (svc.metadata.name or '').lower()
                        labels = {k.lower(): (v.lower() if isinstance(v, str) else v) for k, v in ((svc.metadata.labels or {}).items())}
                        looks = (
                            'prometheus' in name_s or 'thanos' in name_s or
                            'prometheus' in (labels.get('app') or '') or
                            'prometheus' in (labels.get('component') or '') or
                            'prometheus' in (labels.get('app.kubernetes.io/name') or '') or
                            'prometheus' in (labels.get('app.kubernetes.io/instance') or '')
                        )
                        if not looks:
                            continue
                        ports = svc.spec.ports or []
                        pref_names = ['web', 'http', 'http-web', 'prometheus']
                        port_obj = None
                        for p in ports:
                            pname = (getattr(p, 'name', '') or '').lower()
                            if pname in pref_names or getattr(p, 'port', None) == 9090:
                                port_obj = p; break
                        if not port_obj and ports:
                            port_obj = ports[0]
                        if not port_obj:
                            continue
                        port_designator = getattr(port_obj, 'name', None) or getattr(port_obj, 'port', None)
                        if not port_designator:
                            continue
                        targets.append((nsn, svc.metadata.name, str(port_designator)))
                        if len(targets) >= max_targets:
                            raise StopIteration
            except StopIteration:
                pass
            except Exception:
                pass
            seen = set(); out = []
            for t in targets:
                k = (t[0], t[1], t[2])
                if k not in seen:
                    out.append(t); seen.add(k)
            return out

        def prom_query_via_proxy(ns: str, svc: str, port: str, query: str, timeout_s: float = 2.5):
            for scheme in ['http', 'https']:
                try:
                    path = f'/api/v1/namespaces/{ns}/services/{scheme}:{svc}:{port}/proxy/api/v1/query'
                    qp = [('query', query)]
                    resp = api_client.call_api(path, 'GET', query_params=qp, auth_settings=['BearerToken'], _preload_content=False, request_timeout=timeout_s)[0]
                    body = resp.data.decode('utf-8') if hasattr(resp, 'data') else str(resp)
                    j = json.loads(body)
                    if j.get('status') == 'success':
                        return j, f'k8s-proxy://{scheme}:{svc}:{port} (ns {ns})'
                except Exception:
                    continue
            return None, None

        try:
            start = time.time(); budget = 6.0
            for ns_s, svc_s, port_s in detect_prom_service_targets():
                if time.time() - start > budget:
                    break
                j1, ep1 = prom_query_via_proxy(ns_s, svc_s, port_s, q_cpu, timeout_s=2.5)
                j2, ep2 = prom_query_via_proxy(ns_s, svc_s, port_s, q_mem, timeout_s=2.5)
                res1 = (j1.get('data', {}) or {}).get('result', []) if j1 else []
                res2 = (j2.get('data', {}) or {}).get('result', []) if j2 else []
                if res1 or res2:
                    cpu_val = float(res1[0]['value'][1]) if res1 else 0.0
                    mem_val = float(res2[0]['value'][1]) if res2 else 0.0
                    return jsonify({'source': 'prometheus', 'cpu_mcores': int(round(cpu_val * 1000)), 'memory_bytes': int(round(mem_val)), 'endpoint': ep1 or ep2})
        except Exception:
            pass

        # 3) Direct service URLs (NodePort/ClusterIP)
        def detect_prom_urls(max_candidates: int = 3):
            candidates = []
            try:
                all_ns = [ns.metadata.name for ns in core_v1.list_namespace().items]
                prio = ['monitoring', 'prometheus', 'observability', 'default', 'kube-system']
                ordered_ns = prio + [n for n in all_ns if n not in prio]
                for nsn in ordered_ns:
                    for svc in core_v1.list_namespaced_service(nsn).items:
                        name_s = (svc.metadata.name or '').lower()
                        labels = {k.lower(): (v.lower() if isinstance(v, str) else v) for k, v in ((svc.metadata.labels or {}).items())}
                        looks = ('prometheus' in name_s) or any(isinstance(v, str) and 'prometheus' in v for v in labels.values() or [])
                        if not looks:
                            continue
                        ports = svc.spec.ports or []
                        pref_names = ['web', 'http', 'http-web', 'prometheus']
                        port_obj = None
                        for p in ports:
                            pname = (getattr(p, 'name', '') or '').lower()
                            if pname in pref_names or getattr(p, 'port', None) == 9090:
                                port_obj = p; break
                        if not port_obj and ports:
                            port_obj = ports[0]
                        if not port_obj:
                            continue
                        if svc.spec.type == 'NodePort' and getattr(port_obj, 'node_port', None):
                            try:
                                for node in core_v1.list_node().items:
                                    node_ip = None
                                    for addr in node.status.addresses or []:
                                        if addr.type in ('ExternalIP', 'InternalIP'):
                                            node_ip = addr.address; break
                                    if node_ip:
                                        candidates.append(f'http://{node_ip}:{port_obj.node_port}')
                                        candidates.append(f'https://{node_ip}:{port_obj.node_port}')
                            except Exception:
                                pass
                        if svc.spec.cluster_ip and svc.spec.cluster_ip != 'None':
                            cip = svc.spec.cluster_ip
                            candidates.append(f'http://{cip}:{port_obj.port}')
                            candidates.append(f'https://{cip}:{port_obj.port}')
                        if len(candidates) >= max_candidates:
                            raise StopIteration
            except StopIteration:
                pass
            except Exception:
                pass
            seen = set(); out = []
            for u in candidates:
                if u not in seen:
                    out.append(u); seen.add(u)
                if len(out) >= max_candidates:
                    break
            return out

        start = time.time(); budget = 4.0
        for base in detect_prom_urls():
            if time.time() - start > budget:
                break
            try:
                d1 = prom_query(base, q_cpu, timeout_s=2.0)
                d2 = prom_query(base, q_mem, timeout_s=2.0)
                res1 = (d1.get('data', {}) or {}).get('result', []) if d1 else []
                res2 = (d2.get('data', {}) or {}).get('result', []) if d2 else []
                if res1 or res2:
                    cpu_val = float(res1[0]['value'][1]) if res1 else 0.0
                    mem_val = float(res2[0]['value'][1]) if res2 else 0.0
                    return jsonify({'source': 'prometheus', 'cpu_mcores': int(round(cpu_val * 1000)), 'memory_bytes': int(round(mem_val)), 'endpoint': base})
            except Exception:
                continue

        # 4) Fallback to metrics-server
        try:
            co = client.CustomObjectsApi()
            obj = co.get_namespaced_custom_object('metrics.k8s.io', 'v1beta1', namespace, 'pods', name)
            containers = (obj.get('containers') or []) if isinstance(obj, dict) else []

            def parse_cpu_to_mcores(cpu_str: str) -> float:
                s = str(cpu_str or '').strip()
                if not s:
                    return 0.0
                try:
                    if s.endswith('n'):
                        return float(s[:-1]) / 1e6
                    if s.endswith('u'):
                        return float(s[:-1]) / 1e3
                    if s.endswith('m'):
                        return float(s[:-1])
                    return float(s) * 1000.0
                except Exception:
                    return 0.0

            def parse_mem_to_bytes(mem_str: str) -> float:
                s = str(mem_str or '').strip()
                if not s:
                    return 0.0
                try:
                    units = {'Ki': 1024,'Mi': 1024**2,'Gi': 1024**3,'Ti': 1024**4,'Pi': 1024**5,'Ei': 1024**6,'K': 1000,'M': 1000**2,'G': 1000**3,'T': 1000**4,'P': 1000**5,'E': 1000**6}
                    for u, mul in units.items():
                        if s.endswith(u):
                            return float(s[:-len(u)]) * mul
                    return float(s)
                except Exception:
                    return 0.0

            total_cpu_m = 0.0
            total_mem_b = 0.0
            cont_out = []
            for ct in containers:
                nm = ct.get('name')
                usage = ct.get('usage', {}) or {}
                c_m = parse_cpu_to_mcores(usage.get('cpu'))
                m_b = parse_mem_to_bytes(usage.get('memory'))
                total_cpu_m += c_m
                total_mem_b += m_b
                cont_out.append({'name': nm, 'cpu_mcores': int(round(c_m)), 'memory_bytes': int(round(m_b))})

            if total_cpu_m > 0 or total_mem_b > 0 or cont_out:
                return jsonify({'source': 'metrics-server','cpu_mcores': int(round(total_cpu_m)),'memory_bytes': int(round(total_mem_b)),'containers': cont_out})
        except Exception:
            pass

        return jsonify({'source': 'none', 'cpu_mcores': 0, 'memory_bytes': 0, 'containers': []})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/k8s-explorer/pod-metrics-range')
def pod_metrics_range():
    """Return time-series CPU/Memory usage for a Pod via Prometheus query_range.
    Params: namespace, name, minutes(optional, default 30), step(optional, default 15s)
    Response: { source: 'prometheus'|'none', endpoint?: str,
                cpu: { unit: 'cores', data: [[ts(float seconds), value(float)]] },
                memory: { unit: 'bytes', data: [[ts(float seconds), value(float)]] } }
    """
    try:
        namespace = request.args.get('namespace')
        name = request.args.get('name')
        if not namespace or not name:
            return jsonify({'error': 'namespace ve name zorunlu'}), 400

        # Window and step
        try:
            minutes = int(request.args.get('minutes') or 30)
        except Exception:
            minutes = 30
        minutes = max(5, min(240, minutes))
        step = (request.args.get('step') or '15s').strip()
        # Simple guard: allow Ns or Ms
        if not step.endswith(('s', 'm')):
            step = '15s'

        manual_url = request.args.get('prometheus') or os.environ.get('PROMETHEUS_URL')

        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)

        core_v1 = client.CoreV1Api()
        api_client = client.ApiClient()

        # Queries (CPU as rate over 5m; Memory as instantaneous working_set)
        q_cpu = f'sum(rate(container_cpu_usage_seconds_total{{namespace="{namespace}",pod="{name}",container!="",image!=""}}[5m]))'
        q_mem = f'sum(container_memory_working_set_bytes{{namespace="{namespace}",pod="{name}",container!="",image!=""}})'

        end_ts = time.time()
        start_ts = end_ts - minutes * 60

        def prom_query_range(base_url: str, query: str, start_s: float, end_s: float, step_expr: str, timeout_s: float = 2.0):
            params = {
                'query': query,
                'start': f"{start_s}",
                'end': f"{end_s}",
                'step': step_expr,
            }
            r = requests.get(f'{base_url.rstrip('/')}/api/v1/query_range', params=params, timeout=timeout_s, verify=False)
            if r.status_code != 200:
                return None
            return r.json()

        # 1) Manual override
        if manual_url:
            try:
                d1 = prom_query_range(manual_url, q_cpu, start_ts, end_ts, step, timeout_s=2.0)
                d2 = prom_query_range(manual_url, q_mem, start_ts, end_ts, step, timeout_s=2.0)
                if d1 and d2:
                    def extract_series(j):
                        res = (j.get('data', {}) or {}).get('result', []) or []
                        if not res:
                            return []
                        # Sum result vectors if multiple series (defensive)
                        # But PromQL sum should already aggregate; still keep simple first series
                        values = res[0].get('values') or []
                        out = []
                        for t, v in values:
                            try:
                                out.append([float(t), float(v)])
                            except Exception:
                                continue
                        return out
                    cpu_series = extract_series(d1)
                    mem_series = extract_series(d2)
                    if cpu_series or mem_series:
                        return jsonify({'source': 'prometheus','endpoint': manual_url,
                                        'cpu': {'unit': 'cores', 'data': cpu_series},
                                        'memory': {'unit': 'bytes', 'data': mem_series}})
            except Exception:
                pass

        # 2) Via Kubernetes API service proxy
        def prom_query_range_via_proxy(ns: str, svc: str, port: str, query: str, start_s: float, end_s: float, step_expr: str, timeout_s: float = 2.0):
            for scheme in ['http', 'https']:
                try:
                    path = f'/api/v1/namespaces/{ns}/services/{scheme}:{svc}:{port}/proxy/api/v1/query_range'
                    qp = [('query', query), ('start', f'{start_s}'), ('end', f'{end_s}'), ('step', step_expr)]
                    resp = api_client.call_api(path, 'GET', query_params=qp, auth_settings=['BearerToken'], _preload_content=False, request_timeout=timeout_s)[0]
                    body = resp.data.decode('utf-8') if hasattr(resp, 'data') else str(resp)
                    j = json.loads(body)
                    if j.get('status') == 'success':
                        return j, f'k8s-proxy://{scheme}:{svc}:{port} (ns {ns})'
                except Exception:
                    continue
            return None, None

        def detect_prom_service_targets(max_targets: int = 6):
            targets = []
            try:
                all_ns = [ns.metadata.name for ns in core_v1.list_namespace().items]
                prio = ['monitoring', 'prometheus', 'observability', 'default', 'kube-system']
                ordered_ns = prio + [n for n in all_ns if n not in prio]
                for ns in ordered_ns:
                    for svc in core_v1.list_namespaced_service(ns).items:
                        name_s = (svc.metadata.name or '').lower()
                        labels = {k.lower(): (v.lower() if isinstance(v, str) else v) for k, v in ((svc.metadata.labels or {}).items())}
                        looks = ('prometheus' in name_s) or any(isinstance(v, str) and 'prometheus' in v for v in labels.values() or [])
                        if not looks:
                            continue
                        ports = svc.spec.ports or []
                        pref_names = ['web', 'http', 'http-web', 'prometheus']
                        port_obj = None
                        for p in ports:
                            pname = (getattr(p, 'name', '') or '').lower()
                            if pname in pref_names or getattr(p, 'port', None) == 9090:
                                port_obj = p; break
                        if not port_obj and ports:
                            port_obj = ports[0]
                        if not port_obj:
                            continue
                        port_designator = getattr(port_obj, 'name', None) or getattr(port_obj, 'port', None)
                        if not port_designator:
                            continue
                        targets.append((ns, svc.metadata.name, str(port_designator)))
                        if len(targets) >= max_targets:
                            raise StopIteration
            except StopIteration:
                pass
            except Exception:
                pass
            seen = set(); out = []
            for t in targets:
                key = (t[0], t[1], t[2])
                if key not in seen:
                    out.append(t); seen.add(key)
            return out

        try:
            start_budget = time.time(); budget = 4.0
            for ns_s, svc_s, port_s in detect_prom_service_targets():
                if time.time() - start_budget > budget:
                    break
                j1, ep = prom_query_range_via_proxy(ns_s, svc_s, port_s, q_cpu, start_ts, end_ts, step, timeout_s=2.0)
                if not j1:
                    continue
                j2, _ = prom_query_range_via_proxy(ns_s, svc_s, port_s, q_mem, start_ts, end_ts, step, timeout_s=2.0)
                if not j2:
                    continue
                def extract_series(j):
                    res = (j.get('data', {}) or {}).get('result', []) or []
                    if not res:
                        return []
                    values = res[0].get('values') or []
                    out = []
                    for t, v in values:
                        try:
                            out.append([float(t), float(v)])
                        except Exception:
                            continue
                    return out
                cpu_series = extract_series(j1)
                mem_series = extract_series(j2)
                if cpu_series or mem_series:
                    return jsonify({'source': 'prometheus','endpoint': ep,
                                    'cpu': {'unit': 'cores', 'data': cpu_series},
                                    'memory': {'unit': 'bytes', 'data': mem_series}})
        except Exception:
            pass

        # 3) Direct URLs (NodePort/ClusterIP)
        def detect_prom_urls(max_candidates: int = 3):
            candidates = []
            try:
                all_ns = [ns.metadata.name for ns in core_v1.list_namespace().items]
                prio = ['monitoring', 'prometheus', 'observability', 'default', 'kube-system']
                ordered_ns = prio + [n for n in all_ns if n not in prio]
                for nsn in ordered_ns:
                    for svc in core_v1.list_namespaced_service(nsn).items:
                        name_s = (svc.metadata.name or '').lower()
                        labels = {k.lower(): (v.lower() if isinstance(v, str) else v) for k, v in ((svc.metadata.labels or {}).items())}
                        looks = ('prometheus' in name_s) or any(isinstance(v, str) and 'prometheus' in v for v in labels.values() or [])
                        if not looks:
                            continue
                        ports = svc.spec.ports or []
                        pref_names = ['web', 'http', 'http-web', 'prometheus']
                        port_obj = None
                        for p in ports:
                            pname = (getattr(p, 'name', '') or '').lower()
                            if pname in pref_names or getattr(p, 'port', None) == 9090:
                                port_obj = p; break
                        if not port_obj and ports:
                            port_obj = ports[0]
                        if not port_obj:
                            continue
                        if svc.spec.type == 'NodePort' and getattr(port_obj, 'node_port', None):
                            try:
                                for node in core_v1.list_node().items:
                                    node_ip = None
                                    for addr in node.status.addresses or []:
                                        if addr.type in ('ExternalIP', 'InternalIP'):
                                            node_ip = addr.address; break
                                    if node_ip:
                                        candidates.append(f'http://{node_ip}:{port_obj.node_port}')
                                        candidates.append(f'https://{node_ip}:{port_obj.node_port}')
                            except Exception:
                                pass
                        if svc.spec.cluster_ip and svc.spec.cluster_ip != 'None':
                            cip = svc.spec.cluster_ip
                            candidates.append(f'http://{cip}:{port_obj.port}')
                            candidates.append(f'https://{cip}:{port_obj.port}')
                        if len(candidates) >= max_candidates:
                            raise StopIteration
            except StopIteration:
                pass
            except Exception:
                pass
            seen = set(); out = []
            for u in candidates:
                if u not in seen:
                    out.append(u); seen.add(u)
                if len(out) >= max_candidates:
                    break
            return out

        start2 = time.time(); budget2 = 3.0
        for base in detect_prom_urls():
            if time.time() - start2 > budget2:
                break
            try:
                d1 = prom_query_range(base, q_cpu, start_ts, end_ts, step, timeout_s=1.5)
                d2 = prom_query_range(base, q_mem, start_ts, end_ts, step, timeout_s=1.5)
                if not d1 or not d2:
                    continue
                def extract_series(j):
                    res = (j.get('data', {}) or {}).get('result', []) or []
                    if not res:
                        return []
                    values = res[0].get('values') or []
                    out = []
                    for t, v in values:
                        try:
                            out.append([float(t), float(v)])
                        except Exception:
                            continue
                    return out
                cpu_series = extract_series(d1)
                mem_series = extract_series(d2)
                if cpu_series or mem_series:
                    return jsonify({'source': 'prometheus','endpoint': base,
                                    'cpu': {'unit': 'cores', 'data': cpu_series},
                                    'memory': {'unit': 'bytes', 'data': mem_series}})
            except Exception:
                continue

        # Prometheus başarısız olduysa metrics-server zaman serisi tamponunu dön (best-effort)
        try:
            key = (namespace, name)
            with _METRICS_TS_LOCK:
                dq = list(_METRICS_TS.get(key, []))
            if dq:
                # dq: [(ts_sec, cpu_mcores, mem_bytes)]
                # İstenen pencereye göre filtrele ve downsample et (step yaklaşık saniye cinsinden)
                def step_to_seconds(expr: str) -> float:
                    try:
                        if expr.endswith('ms'):
                            return max(0.001, float(expr[:-2]) / 1000.0)
                        if expr.endswith('s'):
                            return max(1.0, float(expr[:-1]))
                        if expr.endswith('m'):
                            return max(60.0, float(expr[:-1]) * 60.0)
                        if expr.endswith('h'):
                            return max(3600.0, float(expr[:-1]) * 3600.0)
                    except Exception:
                        return 15.0
                    return 15.0
                st = end_ts - minutes * 60
                secs = step_to_seconds(step)
                cpu_series = []
                mem_series = []
                next_bucket = st
                acc_cpu = 0
                acc_mem = 0
                acc_cnt = 0
                for ts, cpu_m, mem_b in dq:
                    if ts < st:
                        continue
                    # bucket dolduysa yaz ve yeni bucket'a geç
                    while ts >= next_bucket + secs:
                        if acc_cnt > 0:
                            cpu_series.append([float(next_bucket + secs/2.0), float(acc_cpu)/1000.0/acc_cnt])  # cores
                            mem_series.append([float(next_bucket + secs/2.0), float(acc_mem)/acc_cnt])
                        next_bucket += secs
                        acc_cpu = 0
                        acc_mem = 0
                        acc_cnt = 0
                    acc_cpu += cpu_m
                    acc_mem += mem_b
                    acc_cnt += 1
                # Kuyruk bitti; kalan varsa flush et
                if acc_cnt > 0:
                    cpu_series.append([float(min(end_ts, next_bucket + secs/2.0)), float(acc_cpu)/1000.0/acc_cnt])
                    mem_series.append([float(min(end_ts, next_bucket + secs/2.0)), float(acc_mem)/acc_cnt])
                return jsonify({'source': 'metrics-server',
                                'cpu': {'unit': 'cores', 'data': cpu_series},
                                'memory': {'unit': 'bytes', 'data': mem_series}})
        except Exception:
            pass
        return jsonify({'source': 'none', 'cpu': {'unit': 'cores', 'data': []}, 'memory': {'unit': 'bytes', 'data': []}})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/k8s-explorer/describe')
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



@app.route('/yaml-linter')
def yaml_linter_page():
    return render_template('yaml_linter.html')
# YAML Linter API — yardımcı sabitler ve fonksiyonlar
# Kural #4 ve #5 için container taraması yapılan Kubernetes workload kind'ları
_YAML_LINTER_WORKLOAD_KINDS = frozenset({
    'Deployment', 'StatefulSet', 'DaemonSet', 'Job', 'CronJob', 'ReplicaSet'
})


def _yaml_lint_check_image_latest(image):
    """
    Image tag kontrolü: :latest veya tag'siz imajları tespit eder.

    :param image: Container image string (örn. "nginx:latest", "nginx", "nginx:1.19")
    :returns: True — imaj üretime uygun değil; False — imaj kabul edilebilir
    """
    if not image or not isinstance(image, str):
        return False
    # Digest referansları güvenlidir, atla
    if '@sha256:' in image:
        return False
    if image.endswith(':latest'):
        return True
    # Hiç ":" içermiyorsa tag verilmemiş demektir -> latest davranışı
    if ':' not in image:
        return True
    return False


def _yaml_lint_document(doc, doc_index):
    """
    Tek bir parse edilmiş YAML belgesi üzerinde 5 MVP Kubernetes best practice kuralını çalıştırır.

    Kurallar:
      1. missing-api-version  — apiVersion alanı eksik/boş
      2. missing-kind         — kind alanı eksik/boş
      3. missing-metadata-name — metadata.name alanı eksik/boş
      4. image-latest-tag     — :latest veya tag'siz container imajı
      5. missing-resource-limits — resources.limits tanımlı değil veya boş dict

    :param doc: yaml.safe_load_all() ile parse edilen belge nesnesi
    :param doc_index: Belge sırası (0-tabanlı, path mesajları için)
    :returns: warnings listesi; her öğe {rule, severity, message, path} şeklinde
    """
    warnings = []
    if not isinstance(doc, dict):
        return warnings

    # Kural 1: missing-api-version
    if not doc.get('apiVersion'):
        warnings.append({
            'rule': 'missing-api-version',
            'severity': 'error',
            'message': 'apiVersion alanı eksik veya boş.',
            'path': 'apiVersion',
        })

    # Kural 2: missing-kind
    kind = doc.get('kind')
    if not kind:
        warnings.append({
            'rule': 'missing-kind',
            'severity': 'error',
            'message': 'kind alanı eksik veya boş.',
            'path': 'kind',
        })

    # Kural 3: missing-metadata-name
    metadata = doc.get('metadata')
    if not isinstance(metadata, dict) or not metadata.get('name'):
        warnings.append({
            'rule': 'missing-metadata-name',
            'severity': 'error',
            'message': 'metadata.name alanı eksik veya boş.',
            'path': 'metadata.name',
        })

    # Kural 4 ve 5: container taraması — yalnızca desteklenen kind'lar için
    containers = None
    base_path = None
    if kind in _YAML_LINTER_WORKLOAD_KINDS:
        # Deployment, StatefulSet, DaemonSet, Job, CronJob, ReplicaSet
        spec = doc.get('spec') or {}
        template = spec.get('template') or {}
        tspec = template.get('spec') or {}
        containers = tspec.get('containers') or []
        base_path = 'spec.template.spec.containers'
    elif kind == 'Pod':
        spec = doc.get('spec') or {}
        containers = spec.get('containers') or []
        base_path = 'spec.containers'
    # Diğer kind'lar (Service, ConfigMap, vb.) için container taraması yapılmaz

    if containers is not None:
        for idx, container in enumerate(containers):
            if not isinstance(container, dict):
                continue
            container_name = container.get('name', str(idx))
            image = container.get('image', '')

            # Kural 4: image-latest-tag
            if _yaml_lint_check_image_latest(image):
                warnings.append({
                    'rule': 'image-latest-tag',
                    'severity': 'warning',
                    'message': (
                        f"Container '{container_name}' imajı '{image}' kullanıyor"
                        f" -- üretim ortamlarında sabit tag kullanın."
                    ),
                    'path': f'{base_path}[{idx}].image',
                })

            # Kural 5: missing-resource-limits
            resources = container.get('resources')
            limits = None
            if isinstance(resources, dict):
                limits = resources.get('limits')
            # Eksik veya boş dict her ikisi de uyarı üretir
            if not limits:
                warnings.append({
                    'rule': 'missing-resource-limits',
                    'severity': 'warning',
                    'message': f"Container '{container_name}' için resources.limits tanımlanmamış.",
                    'path': f'{base_path}[{idx}].resources.limits',
                })

    return warnings


@app.route('/yaml-lint-api', methods=['POST'])
def yaml_lint_api():
    """
    YAML Linter API — multi-document YAML syntax kontrolü ve K8s best practice denetimi.

    POST /yaml-lint-api
    Content-Type: application/json
    Body: { "yaml": "<yaml içeriği>" }

    Response (boş içerik):
        { ok: false, error: str, line: null, column: null, documents: 0, warnings: [] }
    Response (syntax hatası):
        { ok: false, error: str, line: int|null, column: int|null, documents: int, warnings: [] }
    Response (başarılı, uyarısız):
        { ok: true, documents: int, warnings: [] }
    Response (başarılı, uyarılı):
        { ok: true, documents: int, warnings: [{rule, severity, message, path}, ...] }
    """
    try:
        data = request.get_json(force=True)
        yaml_str = data.get('yaml', '')

        # Boş içerik kontrolü
        if not yaml_str.strip():
            return jsonify({
                'ok': False,
                'error': 'YAML içeriği boş',
                'line': None,
                'column': None,
                'documents': 0,
                'warnings': [],
            }), 200

        # Multi-document desteği: generator'u teker teker tüket, ilk syntax hatasında dur
        # list() kullanmak yerine for-döngüsü ile tüketilir; böylece ilk hata anında
        # parsed_docs o ana kadar başarılı okunan belgeleri içerir (Risk #2 uyarınca).
        parsed_docs = []
        try:
            for doc in yaml.safe_load_all(yaml_str):
                parsed_docs.append(doc)
        except yaml.YAMLError as e:
            # PyYAML'ın MarkedYAMLError alt sınıfında problem_mark mevcuttur (0-indexed).
            # Diğer YAMLError türlerinde problem_mark olmayabilir; bu durumda null döner.
            line = None
            column = None
            if hasattr(e, 'problem_mark') and e.problem_mark is not None:
                line = e.problem_mark.line + 1      # 0-indexed -> 1-indexed
                column = e.problem_mark.column + 1  # 0-indexed -> 1-indexed
            # e.problem kısa hata metnini verir (örn. "mapping values are not allowed here")
            error_msg = (
                e.problem
                if hasattr(e, 'problem') and e.problem
                else str(e)
            )
            return jsonify({
                'ok': False,
                'error': error_msg,
                'line': line,
                'column': column,
                'documents': len(parsed_docs),
                'warnings': [],
            }), 200

        # Syntax başarılı: her belge üzerinde best practice kurallarını çalıştır
        all_warnings = []
        for idx, doc in enumerate(parsed_docs):
            all_warnings.extend(_yaml_lint_document(doc, idx))

        return jsonify({
            'ok': True,
            'documents': len(parsed_docs),
            'warnings': all_warnings,
        }), 200

    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500



# Generic delete endpoint for various K8s resources
@app.route('/k8s-explorer/delete', methods=['POST', 'DELETE'])
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

        def ok(resp_type, extra=None):
            d = {'ok': True, 'deleted': {'type': resp_type, 'name': name}}
            if namespace:
                d['deleted']['namespace'] = namespace
            if extra:
                d['deleted'].update(extra)
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


# Workload stats API for Overview pie charts — cache background.py'de

@app.route('/k8s-explorer/workload-stats')
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


@app.route('/k8s-explorer/health')
def k8s_explorer_health():
    """Lightweight health check returning: connectivity ok flag, active kube context name, error (if any).

    We now derive the context name from the *active* kubeconfig path selected via session / global fallback
    instead of whatever the default KUBECONFIG env might point to. This matches the cluster actually used
    by backend requests (load_kube_config_active()).
    """
    try:
        current_context_name = None
        # Ensure active kubeconfig is loaded (this sets default client configuration)
        load_kube_config_active()
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
        return jsonify({'ok': ok, 'context': current_context_name, 'error': error})
    except Exception as e:
        return jsonify({'ok': False, 'context': None, 'error': str(e)}), 500


# --- Pods Summary — cache background.py'de ---

@app.route('/k8s-explorer/pods-summary')
def pods_summary():
    try:
        now = time.time()
        if not _bg.pods_summary_cache or (now - _bg.pods_summary_cache_time > _bg.PODS_SUMMARY_CACHE_TTL):
            update_pods_summary_cache()
        result = dict(_bg.pods_summary_cache) if _bg.pods_summary_cache else {'pods': []}
        age = int(now - _bg.pods_summary_cache_time) if _bg.pods_summary_cache_time else int(now)
        result['_cache_meta'] = {
            'updated_at': _bg.pods_summary_cache_time,
            'age_seconds': age,
            'stale': age > 300,
            'last_error': _bg._psc_last_error,
        }
        return jsonify(result)
    except Exception as e:
        return jsonify({'pods': [], 'error': str(e)})

# --- Metrics sampler — background.py'de (start_metrics_sampler dosyanın sonunda çağrılır) ---

# Deployments summary for Overview tab
@app.route('/k8s-explorer/deployments-summary')
def deployments_summary():
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        apps_v1 = client.AppsV1Api()
        deployments = apps_v1.list_deployment_for_all_namespaces().items
        result = []
        for dep in deployments:
            replicas = getattr(dep.status, 'replicas', 0)
            ready_replicas = getattr(dep.status, 'ready_replicas', 0)
            updated_replicas = getattr(dep.status, 'updated_replicas', 0)
            available_replicas = getattr(dep.status, 'available_replicas', 0)
            creation_timestamp = getattr(dep.metadata, 'creation_timestamp', None)
            # READY as "ready/total"
            ready_str = f"{ready_replicas}/{replicas}" if replicas is not None else str(ready_replicas)
            result.append({
                'namespace': dep.metadata.namespace,
                'name': dep.metadata.name,
                'ready': ready_str,
                'replicas': replicas,
                'ready_replicas': ready_replicas,
                'updated_replicas': updated_replicas,
                'available_replicas': available_replicas,
                'creation_timestamp': creation_timestamp.isoformat() if creation_timestamp else None
            })
        return jsonify({'deployments': result})
    except Exception as e:
        return jsonify({'deployments': [], 'error': str(e)})

@app.route('/k8s-explorer/replicasets-summary')
def replicasets_summary():
    """ReplicaSets summary list (namespace, name, ready, desired, age)."""
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        apps_v1 = client.AppsV1Api()
        rsets = apps_v1.list_replica_set_for_all_namespaces().items
        result = []
        for rs in rsets:
            desired = getattr(rs.spec, 'replicas', 0) or 0
            ready = getattr(rs.status, 'ready_replicas', 0) or 0
            creation_timestamp = getattr(rs.metadata, 'creation_timestamp', None)
            result.append({
                'namespace': rs.metadata.namespace,
                'name': rs.metadata.name,
                'ready': f"{ready}/{desired}",
                'desired': desired,
                'ready_replicas': ready,
                'creation_timestamp': creation_timestamp.isoformat() if creation_timestamp else None
            })
        return jsonify({'replicasets': result})
    except Exception as e:
        return jsonify({'replicasets': [], 'error': str(e)})


@app.route('/k8s-explorer/jobs-summary')
def jobs_summary():
    """Jobs summary list (namespace, name, succeeded, failed, completions, age)."""
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        batch_v1 = client.BatchV1Api()
        jobs = batch_v1.list_job_for_all_namespaces().items
        result = []
        for job in jobs:
            succeeded = getattr(job.status, 'succeeded', 0) or 0
            failed = getattr(job.status, 'failed', 0) or 0
            completions = getattr(job.spec, 'completions', None)
            creation_timestamp = getattr(job.metadata, 'creation_timestamp', None)
            result.append({
                'namespace': job.metadata.namespace,
                'name': job.metadata.name,
                'succeeded': succeeded,
                'failed': failed,
                'completions': completions,
                'creation_timestamp': creation_timestamp.isoformat() if creation_timestamp else None
            })
        return jsonify({'jobs': result})
    except Exception as e:
        return jsonify({'jobs': [], 'error': str(e)})


@app.route('/k8s-explorer/cronjobs-summary')
def cronjobs_summary():
    """CronJobs summary list (namespace, name, schedule, suspended, last_schedule_time, active, age)."""
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        batch_v1 = client.BatchV1Api()
        batch_v1beta1 = client.BatchV1beta1Api() if hasattr(client, 'BatchV1beta1Api') else None
        cronjobs = []
        # Prefer BatchV1 CronJob API if available
        try:
            if hasattr(batch_v1, 'list_cron_job_for_all_namespaces'):
                cronjobs = batch_v1.list_cron_job_for_all_namespaces().items
            elif batch_v1beta1:
                cronjobs = batch_v1beta1.list_cron_job_for_all_namespaces().items
            else:
                cronjobs = []
        except Exception:
            # Fallback to beta if v1 call failed
            if batch_v1beta1:
                try:
                    cronjobs = batch_v1beta1.list_cron_job_for_all_namespaces().items
                except Exception:
                    cronjobs = []
            else:
                cronjobs = []
        result = []
        for cj in cronjobs:
            spec = getattr(cj, 'spec', None) or {}
            status = getattr(cj, 'status', None) or {}
            suspended = getattr(spec, 'suspend', False)
            schedule = getattr(spec, 'schedule', None)
            last_schedule_time = getattr(status, 'last_schedule_time', None) or getattr(status, 'lastScheduleTime', None)
            active = 0
            try:
                active = len(getattr(status, 'active', []) or [])
            except Exception:
                active = 0
            creation_timestamp = getattr(cj.metadata, 'creation_timestamp', None)
            result.append({
                'namespace': cj.metadata.namespace,
                'name': cj.metadata.name,
                'schedule': schedule,
                'suspended': bool(suspended),
                'last_schedule_time': last_schedule_time.isoformat() if last_schedule_time else None,
                'active': active,
                'creation_timestamp': creation_timestamp.isoformat() if creation_timestamp else None
            })
        return jsonify({'cronjobs': result})
    except Exception as e:
        return jsonify({'cronjobs': [], 'error': str(e)})


# Simple proxy API used by k8s_explorer frontend
@app.route('/api/k8s/service/<namespace>/<name>/pods')
def api_service_pods(namespace, name):
    """Return pods belonging to a Service by using its selector."""
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        core_v1 = client.CoreV1Api()
        svc = core_v1.read_namespaced_service(name, namespace)
        selector = svc.spec.selector or {}
        if not selector:
            return jsonify([])
        # Build label selector string
        selector_str = ','.join([f"{k}={v}" for k, v in selector.items()])
        pods = core_v1.list_namespaced_pod(namespace=namespace, label_selector=selector_str).items
        result = []
        for p in pods:
            result.append({
                'namespace': p.metadata.namespace,
                'name': p.metadata.name,
                'status': getattr(p.status, 'phase', None)
            })
        return jsonify(result)
    except client.exceptions.ApiException as ae:
        # If the service doesn't exist, return empty list (frontend expects no pods)
        try:
            status_code = int(getattr(ae, 'status', 0) or 0)
        except Exception:
            status_code = 0
        if status_code == 404:
            return jsonify([])
        import traceback
        tb = traceback.format_exc()
        return jsonify({'error': str(ae), 'traceback': tb}), 500
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        return jsonify({'error': str(e), 'traceback': tb}), 500

@app.route('/k8s-explorer/delete-replicasets', methods=['POST'])
def delete_replicasets():
    """Delete one or more ReplicaSets.
    Body JSON: { "items": [ {"namespace": "ns", "name": "rs1"}, ... ] }
    Returns: { deleted: [...], errors: [...] }
    """
    try:
        data = request.get_json(force=True)
        items = data.get('items') if isinstance(data, dict) else None
        if not items or not isinstance(items, list):
            return jsonify({'error': 'items listesi zorunlu'}), 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        apps_v1 = client.AppsV1Api()
        deleted = []
        errors = []
        for it in items:
            ns = (it or {}).get('namespace')
            name = (it or {}).get('name')
            if not ns or not name:
                errors.append({'namespace': ns, 'name': name, 'error': 'eksik namespace veya name'})
                continue
            try:
                # Foreground propagation -> orphanDependents=False ensures pods may be deleted depending policy
                apps_v1.delete_namespaced_replica_set(name=name, namespace=ns)
                deleted.append({'namespace': ns, 'name': name})
            except Exception as ie:
                errors.append({'namespace': ns, 'name': name, 'error': str(ie)})
        status_code = 207 if errors else 200
        return jsonify({'deleted': deleted, 'errors': errors}), status_code
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/k8s-explorer/deployment-properties')
def deployment_properties():
    """Return detailed properties for a single Deployment (spec + status essentials)."""
    namespace = request.args.get('namespace')
    name = request.args.get('name')
    if not namespace or not name:
        return jsonify({'error': 'namespace ve name zorunlu'}), 400
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        apps_v1 = client.AppsV1Api()
        dep = apps_v1.read_namespaced_deployment(name=name, namespace=namespace)
        md = dep.metadata
        spec = dep.spec
        status = dep.status
        def to_dict_container(cn):
            resources = getattr(cn, 'resources', None)
            limits = getattr(resources, 'limits', None) if resources else None
            requests_r = getattr(resources, 'requests', None) if resources else None
            sec = getattr(cn, 'security_context', None)
            return {
                'name': cn.name,
                'image': cn.image,
                'image_pull_policy': getattr(cn, 'image_pull_policy', None),
                'ports': [p.container_port for p in (cn.ports or [])] if getattr(cn, 'ports', None) else [],
                'env': [{ 'name': e.name, 'value': getattr(e, 'value', None)} for e in (cn.env or [])] if getattr(cn, 'env', None) else [],
                'resources': {
                    'limits': limits,
                    'requests': requests_r
                },
                'security_context': {
                    'run_as_user': getattr(sec, 'run_as_user', None) if sec else None,
                    'run_as_group': getattr(sec, 'run_as_group', None) if sec else None,
                    'fs_group': getattr(sec, 'fs_group', None) if sec else None,
                    'read_only_root_filesystem': getattr(sec, 'read_only_root_filesystem', None) if sec else None,
                    'allow_privilege_escalation': getattr(sec, 'allow_privilege_escalation', None) if sec else None,
                } if sec else None,
                'liveness_probe': bool(getattr(cn, 'liveness_probe', None)),
                'readiness_probe': bool(getattr(cn, 'readiness_probe', None)),
            }
        containers = [to_dict_container(cn) for cn in (spec.template.spec.containers or [])]
        strategy = getattr(spec, 'strategy', None)
        selector = getattr(spec, 'selector', None)
        result = {
            'metadata': {
                'name': md.name,
                'namespace': md.namespace,
                'labels': md.labels or {},
                'annotations': md.annotations or {},
                'creation_timestamp': md.creation_timestamp.isoformat() if getattr(md, 'creation_timestamp', None) else None,
            },
            'spec': {
                'replicas': getattr(spec, 'replicas', None),
                'strategy': getattr(strategy, 'type', None) if strategy else None,
                'selector': getattr(selector, 'match_labels', None) if selector else None,
                'containers': containers,
            },
            'status': {
                'replicas': getattr(status, 'replicas', None),
                'ready_replicas': getattr(status, 'ready_replicas', None),
                'updated_replicas': getattr(status, 'updated_replicas', None),
                'available_replicas': getattr(status, 'available_replicas', None),
                'unavailable_replicas': getattr(status, 'unavailable_replicas', None),
                'conditions': [
                    {
                        'type': c.type,
                        'status': c.status,
                        'reason': getattr(c, 'reason', None),
                        'message': getattr(c, 'message', None),
                        'last_update_time': getattr(c, 'last_update_time', None).isoformat() if getattr(c, 'last_update_time', None) else None
                    } for c in (getattr(status, 'conditions', []) or [])
                ]
            }
        }
        return jsonify({'deployment': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/configmap-secrets')
def configmap_secrets():
    return render_template('configmap_secrets.html')

@app.route('/configmap-secrets-data')
def configmap_secrets_data():
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        core_v1 = client.CoreV1Api()
        keywords = ['password', 'passwd', 'secret', 'key', 'token', 'apikey', 'api_key', 'auth', 'credential', 'private', 'jwt', 'access', 'refresh']
        suspects = []
        namespaces = [ns.metadata.name for ns in core_v1.list_namespace().items]
        for ns in namespaces:
            configmaps = core_v1.list_namespaced_config_map(ns).items
            for cm in configmaps:
                data = getattr(cm, 'data', {}) or {}
                for k, v in data.items():
                    val = (v or '').lower()
                    for kw in keywords:
                        if kw in k.lower() or kw in val:
                            suspects.append({
                                'namespace': ns,
                                'configmap': cm.metadata.name,
                                'key': k,
                                'value': v[:20] + ('...' if len(v) > 20 else '')
                            })
                            break
        return jsonify({'suspects': suspects})
    except Exception as e:
        return jsonify({'error': str(e), 'suspects': []}), 500

@app.route('/k8s-explorer/configmaps-summary')
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


@app.route('/k8s-explorer/configmap')
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


@app.route('/k8s-explorer/update-configmap', methods=['POST'])
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

@app.route('/k8s-explorer/secrets-summary')
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


@app.route('/k8s-explorer/secret')
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


@app.route('/k8s-explorer/update-secret', methods=['POST'])
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


@app.route('/k8s-explorer/delete-secret', methods=['POST'])
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

@app.route('/k8s-explorer/resource-quotas-summary')
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

@app.route('/k8s-explorer/limit-ranges-summary')
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

# Workloads page (moved below app initialization)

# Node uncordon endpoint
@app.route('/k8s-explorer/node-uncordon', methods=['POST'])
def k8s_explorer_node_uncordon():
    try:
        data = request.get_json(force=True)
        node_name = data.get('node')
        if not node_name:
            return 'Node adı zorunlu', 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        kube_client = type('KubeClient', (), {})()
        kube_client.core_v1 = client.CoreV1Api()
        # Node'u uncordon et
        body = {"spec": {"unschedulable": False}}
        kube_client.core_v1.patch_node(node_name, body)
        return 'Node uncordon (schedulable) yapıldı.'
    except Exception as e:
        return str(e), 500


# Node cordon endpoint
@app.route('/k8s-explorer/node-cordon', methods=['POST'])
def k8s_explorer_node_cordon():
    try:
        data = request.get_json(force=True)
        node_name = data.get('node')
        if not node_name:
            return 'Node adı zorunlu', 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        kube_client = type('KubeClient', (), {})()
        kube_client.core_v1 = client.CoreV1Api()
        # Node'u cordon et
        body = {"spec": {"unschedulable": True}}
        kube_client.core_v1.patch_node(node_name, body)
        return 'Node cordon (unschedulable) yapıldı.'
    except Exception as e:
        return str(e), 500


# Node drain endpoint
@app.route('/k8s-explorer/node-drain', methods=['POST'])
def k8s_explorer_node_drain():
    try:
        data = request.get_json(force=True)
        node_name = data.get('node')
        if not node_name:
            return 'Node adı zorunlu', 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        kube_client = type('KubeClient', (), {})()
        kube_client.core_v1 = client.CoreV1Api()
        log_lines = []
        # Node'u cordon et
        body = {"spec": {"unschedulable": True}}
        kube_client.core_v1.patch_node(node_name, body)
        log_lines.append(f"Node '{node_name}' cordon (unschedulable) yapıldı.")
        # Node'daki podları evict et
        pods = kube_client.core_v1.list_pod_for_all_namespaces(field_selector=f'spec.nodeName={node_name}').items
        for pod in pods:
            owner_refs = getattr(pod.metadata, 'owner_references', []) or []
            is_daemonset = any(getattr(ref, 'kind', '') == 'DaemonSet' for ref in owner_refs)
            if is_daemonset:
                log_lines.append(f"Pod {pod.metadata.name} (ns: {pod.metadata.namespace}) bir DaemonSet'e ait, atlanıyor.")
                continue
            try:
                kube_client.core_v1.delete_namespaced_pod(pod.metadata.name, pod.metadata.namespace, grace_period_seconds=30)
                log_lines.append(f"Pod {pod.metadata.name} (ns: {pod.metadata.namespace}) drain/evict edildi.")
            except Exception as ex:
                log_lines.append(f"Pod {pod.metadata.name} (ns: {pod.metadata.namespace}) drain edilirken hata: {str(ex)}")
        log_lines.append("Drain işlemi tamamlandı.")
        return {"logs": log_lines}, 200
    except Exception as e:
        return {"logs": [str(e)]}, 500
    
@app.route('/k8s-explorer/nodes')
def k8s_explorer_nodes():
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        kube_client = type('KubeClient', (), {})()
        kube_client.core_v1 = client.CoreV1Api()
        nodes = kube_client.core_v1.list_node().items
        result = []
        for n in nodes:
            status = 'Ready'
            unschedulable = getattr(n.spec, 'unschedulable', False)
            for cond in n.status.conditions or []:
                if cond.type == 'Ready' and cond.status != 'True':
                    status = 'NotReady'
            # unschedulable ise status'ü Cordoned olarak göster
            if unschedulable:
                status = 'Cordoned'
            result.append({'name': n.metadata.name, 'status': status, 'unschedulable': unschedulable})
        return jsonify({'nodes': result})
    except Exception as e:
        return jsonify({'error': str(e)})



# Namespace altında önce ingress varsa onu, yoksa service'leri döndüren endpoint
@app.route('/k8s-explorer/namespace-children')
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


# Pod loglarını döndüren endpoint
@app.route('/k8s-explorer/logs')
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
    

@app.route('/k8s-explorer/yaml', methods=['GET', 'PATCH'])
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
            return 'ok', 200
    except Exception as e:
        return str(e), 500

# Namespace listesini döndüren endpoint
@app.route('/k8s-explorer/namespaces')
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


# --- Network summaries (namespaced when applicable) ---
@app.route('/k8s-explorer/services-summary')
def services_summary():
    try:
        namespace = request.args.get('namespace')
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        v1 = client.CoreV1Api()
        if namespace and namespace != 'all':
            items = v1.list_namespaced_service(namespace).items
        else:
            items = v1.list_service_for_all_namespaces().items
        result = []
        for svc in items:
            spec = svc.spec
            ports = []
            for p in (spec.ports or []):
                try:
                    ports.append({'port': p.port, 'targetPort': getattr(p, 'target_port', None), 'protocol': getattr(p, 'protocol', None)})
                except Exception:
                    ports.append({'port': getattr(p, 'port', None)})

            # externalIPs alanını güvenle çek
            ext_ips = None
            try:
                ext_ips = getattr(spec, 'external_i_ps', None)
                if not ext_ips:
                    ext_ips = getattr(spec, 'external_ips', None)
            except Exception:
                ext_ips = None
            external_ip = None
            try:
                if isinstance(ext_ips, list) and ext_ips:
                    external_ip = ext_ips[0]
                elif isinstance(ext_ips, str):
                    external_ip = ext_ips
            except Exception:
                external_ip = None

            result.append({
                'namespace': svc.metadata.namespace,
                'name': svc.metadata.name,
                'type': getattr(spec, 'type', None),
                'cluster_ip': getattr(spec, 'cluster_ip', None),
                'external_ip': external_ip,
                'selector': getattr(spec, 'selector', None) or {},
                'ports': ports,
                'creation_timestamp': svc.metadata.creation_timestamp.isoformat() if getattr(svc.metadata, 'creation_timestamp', None) else None
            })
        return jsonify({'services': result})
    except Exception as e:
        return jsonify({'services': [], 'error': str(e)})


@app.route('/k8s-explorer/endpoints-summary')
def endpoints_summary():
    try:
        namespace = request.args.get('namespace')
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        v1 = client.CoreV1Api()
        if namespace and namespace != 'all':
            items = v1.list_namespaced_endpoints(namespace).items
        else:
            items = v1.list_endpoints_for_all_namespaces().items
        result = []
        for ep in items:
            subsets = []
            for ss in (ep.subsets or []) or []:
                def to_tr(a):
                    try:
                        tr = getattr(a, 'target_ref', None) or getattr(a, 'targetRef', None)
                        return {'kind': getattr(tr, 'kind', None), 'name': getattr(tr, 'name', None)} if tr else None
                    except Exception:
                        return None
                addresses = [{'ip': getattr(a, 'ip', None), 'targetRef': to_tr(a)} for a in (ss.addresses or [])]
                not_ready = [{'ip': getattr(a, 'ip', None), 'targetRef': to_tr(a)} for a in (ss.not_ready_addresses or [])]
                ports = [{'name': getattr(p, 'name', None), 'port': getattr(p, 'port', None), 'protocol': getattr(p, 'protocol', None)} for p in (ss.ports or [])]
                subsets.append({'addresses': addresses, 'not_ready_addresses': not_ready, 'ports': ports})
            result.append({
                'namespace': ep.metadata.namespace,
                'name': ep.metadata.name,
                'subsets': subsets,
                'creation_timestamp': ep.metadata.creation_timestamp.isoformat() if getattr(ep.metadata, 'creation_timestamp', None) else None
            })
        return jsonify({'endpoints': result})
    except Exception as e:
        return jsonify({'endpoints': [], 'error': str(e)})


@app.route('/k8s-explorer/ingresses-summary')
def ingresses_summary():
    try:
        namespace = request.args.get('namespace')
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        net_v1 = client.NetworkingV1Api()
        if namespace and namespace != 'all':
            items = net_v1.list_namespaced_ingress(namespace).items
        else:
            items = net_v1.list_ingress_for_all_namespaces().items
        result = []
        for ing in items:
            hosts = []
            try:
                rules = getattr(ing.spec, 'rules', None) or []
                for rule in rules:
                    h = getattr(rule, 'host', None)
                    if h:
                        hosts.append(h)
            except Exception:
                pass
            ing_class = getattr(ing.spec, 'ingress_class_name', None)
            if not ing_class:
                ing_class = getattr(ing.spec, 'ingressClassName', None)
            result.append({
                'namespace': ing.metadata.namespace,
                'name': ing.metadata.name,
                'class': ing_class,
                'hosts': hosts,
                'creation_timestamp': ing.metadata.creation_timestamp.isoformat() if getattr(ing.metadata, 'creation_timestamp', None) else None
            })
        return jsonify({'ingresses': result})
    except Exception as e:
        return jsonify({'ingresses': [], 'error': str(e)})


@app.route('/k8s-explorer/ingress-classes-summary')
def ingress_classes_summary():
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        net_v1 = client.NetworkingV1Api()
        items = net_v1.list_ingress_class().items
        result = []
        for ic in items:
            params = None
            try:
                params = getattr(ic.spec, 'parameters', None)
                if params:
                    params = {
                        'apiGroup': getattr(params, 'api_group', None) or getattr(params, 'apiGroup', None),
                        'kind': getattr(params, 'kind', None),
                        'name': getattr(params, 'name', None),
                        'scope': getattr(params, 'scope', None),
                        'namespace': getattr(params, 'namespace', None),
                    }
            except Exception:
                params = None
            # Detect default ingress class via annotation networking.kubernetes.io/default-ingress-class=true
            is_default = False
            try:
                ann = getattr(ic.metadata, 'annotations', {}) or {}
                val = ann.get('ingressclass.kubernetes.io/is-default-class') or ann.get('networking.kubernetes.io/default-ingress-class')
                if isinstance(val, str):
                    is_default = val.lower() in ('true', '1', 'yes')
                elif isinstance(val, bool):
                    is_default = val
            except Exception:
                is_default = False
            result.append({
                'name': ic.metadata.name,
                'controller': getattr(ic.spec, 'controller', None),
                'parameters': params,
                'is_default': is_default,
                'creation_timestamp': ic.metadata.creation_timestamp.isoformat() if getattr(ic.metadata, 'creation_timestamp', None) else None
            })
        return jsonify({'ingress_classes': result})
    except Exception as e:
        return jsonify({'ingress_classes': [], 'error': str(e)})


@app.route('/k8s-explorer/network-policies-summary')
def network_policies_summary():
    try:
        namespace = request.args.get('namespace')
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        net_v1 = client.NetworkingV1Api()
        if namespace and namespace != 'all':
            items = net_v1.list_namespaced_network_policy(namespace).items
        else:
            items = net_v1.list_network_policy_for_all_namespaces().items
        result = []
        for np in items:
            spec = np.spec
            ingress_rules = len(getattr(spec, 'ingress', []) or []) if spec else 0
            egress_rules = len(getattr(spec, 'egress', []) or []) if spec else 0
            pod_selector = getattr(spec, 'pod_selector', None)
            pod_selector_match = getattr(pod_selector, 'match_labels', None) if pod_selector else None
            result.append({
                'namespace': np.metadata.namespace,
                'name': np.metadata.name,
                'policy_types': getattr(spec, 'policy_types', None) if spec else None,
                'ingress_rules': ingress_rules,
                'egress_rules': egress_rules,
                'pod_selector': pod_selector_match,
                'creation_timestamp': np.metadata.creation_timestamp.isoformat() if getattr(np.metadata, 'creation_timestamp', None) else None
            })
        return jsonify({'network_policies': result})
    except Exception as e:
        return jsonify({'network_policies': [], 'error': str(e)})


# --- Storage summaries ---
@app.route('/k8s-explorer/pvcs-summary')
def pvcs_summary():
    try:
        namespace = request.args.get('namespace')
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        v1 = client.CoreV1Api()
        if namespace and namespace != 'all':
            items = v1.list_namespaced_persistent_volume_claim(namespace).items
        else:
            items = v1.list_persistent_volume_claim_for_all_namespaces().items
        result = []
        for pvc in items:
            spec = pvc.spec
            status = pvc.status
            result.append({
                'namespace': pvc.metadata.namespace,
                'name': pvc.metadata.name,
                'status': getattr(status, 'phase', None),
                'volume': getattr(spec, 'volume_name', None) if spec else None,
                'storage_class': getattr(spec, 'storage_class_name', None) or getattr(spec, 'storage_class', None),
                'access_modes': getattr(spec, 'access_modes', None) if spec else None,
                'capacity': getattr(getattr(status, 'capacity', None) or {}, 'get', lambda k, d=None: None)('storage', None) if status else None,
                'creation_timestamp': pvc.metadata.creation_timestamp.isoformat() if getattr(pvc.metadata, 'creation_timestamp', None) else None
            })
        return jsonify({'pvcs': result})
    except Exception as e:
        return jsonify({'pvcs': [], 'error': str(e)})

@app.route('/k8s-explorer/pvs-summary')
def pvs_summary():
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        v1 = client.CoreV1Api()
        items = v1.list_persistent_volume().items
        result = []
        for pv in items:
            spec = pv.spec
            status = pv.status
            claim_ref = getattr(spec, 'claim_ref', None)
            claim = f"{getattr(claim_ref,'namespace',None)}/{getattr(claim_ref,'name',None)}" if claim_ref else None
            cap = getattr(getattr(status, 'capacity', None) or {}, 'get', lambda k, d=None: None)('storage', None) if status else None
            result.append({
                'name': pv.metadata.name,
                'capacity': cap,
                'access_modes': getattr(spec, 'access_modes', None) if spec else None,
                'reclaim_policy': getattr(spec, 'persistent_volume_reclaim_policy', None) if spec else None,
                'storage_class': getattr(spec, 'storage_class_name', None) or getattr(spec, 'storage_class', None),
                'status': getattr(status, 'phase', None),
                'claim': claim,
                'creation_timestamp': pv.metadata.creation_timestamp.isoformat() if getattr(pv.metadata, 'creation_timestamp', None) else None
            })
        return jsonify({'pvs': result})
    except Exception as e:
        return jsonify({'pvs': [], 'error': str(e)})

@app.route('/k8s-explorer/storage-classes-summary')
def storage_classes_summary():
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        storage_v1 = client.StorageV1Api()
        items = storage_v1.list_storage_class().items
        result = []
        for sc in items:
            allow_expansion = getattr(sc.allow_volume_expansion, 'value', None) if hasattr(sc, 'allow_volume_expansion') else getattr(sc, 'allow_volume_expansion', None)
            result.append({
                'name': sc.metadata.name,
                'provisioner': getattr(sc, 'provisioner', None),
                'reclaim_policy': getattr(sc, 'reclaim_policy', None),
                'volume_binding_mode': getattr(sc, 'volume_binding_mode', None),
                'allow_expansion': allow_expansion,
                'creation_timestamp': sc.metadata.creation_timestamp.isoformat() if getattr(sc.metadata, 'creation_timestamp', None) else None
            })
        return jsonify({'storage_classes': result})
    except Exception as e:
        return jsonify({'storage_classes': [], 'error': str(e)})

@app.route('/k8s-explorer/rbac-summary')
def rbac_summary():
    """Return summaries for ServiceAccounts (namespaced), Roles (namespaced), RoleBindings (namespaced), ClusterRoles (cluster), ClusterRoleBindings (cluster).
       Optional namespace param filters namespaced sets, default=default."""
    try:
        namespace = request.args.get('namespace') or 'default'
        load_kube_config_active()
        c = client.Configuration.get_default_copy(); c.verify_ssl=False; c.assert_hostname=False; client.Configuration.set_default(c)
        core_v1 = client.CoreV1Api()
        rbac_v1 = client.RbacAuthorizationV1Api()

        # ServiceAccounts
        if namespace == 'all':
            sas = core_v1.list_service_account_for_all_namespaces().items
        else:
            sas = core_v1.list_namespaced_service_account(namespace).items
        sa_list = []
        for sa in sas:
            sa_list.append({
                'namespace': getattr(sa.metadata,'namespace',None),
                'name': getattr(sa.metadata,'name',None),
                'secrets': len(getattr(sa,'secrets',[]) or []),
                'age': sa.metadata.creation_timestamp.isoformat() if getattr(sa.metadata,'creation_timestamp',None) else None
            })

        # Roles
        if namespace == 'all':
            roles_items = []
            for ns in [n.metadata.name for n in core_v1.list_namespace().items]:
                try:
                    roles_items += rbac_v1.list_namespaced_role(ns).items
                except Exception:
                    continue
        else:
            roles_items = rbac_v1.list_namespaced_role(namespace).items
        roles = []
        for r in roles_items:
            rules = getattr(r,'rules',[]) or []
            roles.append({
                'namespace': getattr(r.metadata,'namespace',None),
                'name': getattr(r.metadata,'name',None),
                'rules_count': len(rules),
                'age': r.metadata.creation_timestamp.isoformat() if getattr(r.metadata,'creation_timestamp',None) else None
            })

        # RoleBindings
        if namespace == 'all':
            rbs_items = []
            for ns in [n.metadata.name for n in core_v1.list_namespace().items]:
                try:
                    rbs_items += rbac_v1.list_namespaced_role_binding(ns).items
                except Exception:
                    continue
        else:
            rbs_items = rbac_v1.list_namespaced_role_binding(namespace).items
        role_bindings = []
        for rb in rbs_items:
            subs = getattr(rb,'subjects',[]) or []
            role_ref = getattr(rb,'role_ref',None)
            role_bindings.append({
                'namespace': getattr(rb.metadata,'namespace',None),
                'name': getattr(rb.metadata,'name',None),
                'subjects': len(subs),
                'roleRef': {'kind': getattr(role_ref,'kind',None), 'name': getattr(role_ref,'name',None)} if role_ref else None,
                'age': rb.metadata.creation_timestamp.isoformat() if getattr(rb.metadata,'creation_timestamp',None) else None
            })

        # ClusterRoles
        cr_items = rbac_v1.list_cluster_role().items
        cluster_roles = []
        for cr in cr_items:
            cluster_roles.append({
                'name': getattr(cr.metadata,'name',None),
                'rules_count': len(getattr(cr,'rules',[]) or []),
                'age': cr.metadata.creation_timestamp.isoformat() if getattr(cr.metadata,'creation_timestamp',None) else None
            })

        # ClusterRoleBindings
        crb_items = rbac_v1.list_cluster_role_binding().items
        cluster_role_bindings = []
        for crb in crb_items:
            subs = getattr(crb,'subjects',[]) or []
            role_ref = getattr(crb,'role_ref',None)
            cluster_role_bindings.append({
                'name': getattr(crb.metadata,'name',None),
                'subjects': len(subs),
                'roleRef': {'kind': getattr(role_ref,'kind',None), 'name': getattr(role_ref,'name',None)} if role_ref else None,
                'age': crb.metadata.creation_timestamp.isoformat() if getattr(crb.metadata,'creation_timestamp',None) else None
            })
        return jsonify({'service_accounts': sa_list, 'roles': roles, 'role_bindings': role_bindings, 'cluster_roles': cluster_roles, 'cluster_role_bindings': cluster_role_bindings})
    except Exception as e:
        return jsonify({'error': str(e), 'service_accounts': [], 'roles': [], 'role_bindings': [], 'cluster_roles': [], 'cluster_role_bindings': []}), 500

@app.route('/k8s-explorer/rbac-detail')
def rbac_detail():
    try:
        kind = (request.args.get('kind') or '').lower()
        name = request.args.get('name')
        namespace = request.args.get('namespace')
        if not kind or not name:
            return jsonify({'error': 'kind ve name zorunlu'}), 400
        load_kube_config_active(); c = client.Configuration.get_default_copy(); c.verify_ssl=False; c.assert_hostname=False; client.Configuration.set_default(c)
        core_v1 = client.CoreV1Api(); rbac_v1 = client.RbacAuthorizationV1Api()
        obj = None
        if kind == 'serviceaccount':
            if not namespace: return jsonify({'error': 'namespace zorunlu'}), 400
            obj = core_v1.read_namespaced_service_account(name, namespace)
        elif kind == 'role':
            if not namespace: return jsonify({'error': 'namespace zorunlu'}), 400
            obj = rbac_v1.read_namespaced_role(name, namespace)
        elif kind == 'rolebinding':
            if not namespace: return jsonify({'error': 'namespace zorunlu'}), 400
            obj = rbac_v1.read_namespaced_role_binding(name, namespace)
        elif kind == 'clusterrole':
            obj = rbac_v1.read_cluster_role(name)
        elif kind == 'clusterrolebinding':
            obj = rbac_v1.read_cluster_role_binding(name)
        else:
            return jsonify({'error': 'desteklenmeyen kind'}), 400
        # convert via to_dict if exists
        data = getattr(obj,'to_dict',lambda: obj)()
        return jsonify({'object': data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# --- Storage detail endpoints ---
@app.route('/k8s-explorer/pvc-details')
def pvc_details():
    try:
        name = request.args.get('name')
        namespace = request.args.get('namespace')
        if not name or not namespace:
            return jsonify({'error': 'name ve namespace zorunlu'}), 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        v1 = client.CoreV1Api()
        pvc = v1.read_namespaced_persistent_volume_claim(name, namespace)
        md = pvc.metadata; spec = pvc.spec; status = pvc.status
        return jsonify({'pvc': {
            'name': getattr(md,'name',None),
            'namespace': getattr(md,'namespace',None),
            'labels': getattr(md,'labels',{}) or {},
            'annotations': getattr(md,'annotations',{}) or {},
            'creation_timestamp': getattr(md,'creation_timestamp',None).isoformat() if getattr(md,'creation_timestamp',None) else None,
            'volume': getattr(spec,'volume_name',None) if spec else None,
            'access_modes': getattr(spec,'access_modes',None) if spec else None,
            'resources': getattr(spec,'resources',None).to_dict() if getattr(spec,'resources',None) else None,
            'storage_class': getattr(spec,'storage_class_name',None) or getattr(spec,'storage_class',None),
            'status': getattr(status,'phase',None) if status else None,
            'capacity': getattr(getattr(status,'capacity',None) or {},'get',lambda k,d=None:None)('storage',None) if status else None
        }})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/k8s-explorer/pv-details')
def pv_details():
    try:
        name = request.args.get('name')
        if not name:
            return jsonify({'error': 'name zorunlu'}), 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        v1 = client.CoreV1Api()
        pv = v1.read_persistent_volume(name)
        md = pv.metadata; spec = pv.spec; status = pv.status
        claim_ref = getattr(spec,'claim_ref',None)
        claim = f"{getattr(claim_ref,'namespace',None)}/{getattr(claim_ref,'name',None)}" if claim_ref else None
        return jsonify({'pv': {
            'name': getattr(md,'name',None),
            'labels': getattr(md,'labels',{}) or {},
            'annotations': getattr(md,'annotations',{}) or {},
            'creation_timestamp': getattr(md,'creation_timestamp',None).isoformat() if getattr(md,'creation_timestamp',None) else None,
            'capacity': getattr(getattr(status,'capacity',None) or {},'get',lambda k,d=None:None)('storage',None) if status else None,
            'access_modes': getattr(spec,'access_modes',None) if spec else None,
            'reclaim_policy': getattr(spec,'persistent_volume_reclaim_policy',None) if spec else None,
            'storage_class': getattr(spec,'storage_class_name',None) or getattr(spec,'storage_class',None),
            'status': getattr(status,'phase',None) if status else None,
            'claim': claim,
            'volume_mode': getattr(spec,'volume_mode',None) if spec else None,
            'node_affinity': getattr(getattr(spec,'node_affinity',None),'to_dict',lambda:None)()
        }})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/k8s-explorer/storage-class-details')
def storage_class_details():
    try:
        name = request.args.get('name')
        if not name:
            return jsonify({'error': 'name zorunlu'}), 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        storage_v1 = client.StorageV1Api()
        sc = storage_v1.read_storage_class(name)
        md = sc.metadata
        return jsonify({'storage_class': {
            'name': getattr(md,'name',None),
            'labels': getattr(md,'labels',{}) or {},
            'annotations': getattr(md,'annotations',{}) or {},
            'creation_timestamp': getattr(md,'creation_timestamp',None).isoformat() if getattr(md,'creation_timestamp',None) else None,
            'provisioner': getattr(sc,'provisioner',None),
            'reclaim_policy': getattr(sc,'reclaim_policy',None),
            'volume_binding_mode': getattr(sc,'volume_binding_mode',None),
            'allow_expansion': getattr(sc,'allow_volume_expansion',None)
        }})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.errorhandler(Exception)
def handle_exception(e):
    import sys
    tb = traceback.format_exc()
    print('GLOBAL ERROR HANDLER:', e, file=sys.stderr)
    print(tb, file=sys.stderr)
    response = {
        'error': str(e),
        'traceback': tb
    }
    return jsonify(response), 500
# --- Kubernetes Explorer API ---

# Kubernetes Explorer sayfası
@app.route('/k8s-explorer')
def k8s_explorer_page():
    return render_template('k8s_explorer.html')

# ---- Trivy Operator: Install, Status, Reports ----
@app.route('/trivy-operator')
def trivy_operator_page():
    return render_template('trivy_operator.html')

def _run_cmd(cmd, timeout=120):
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out, err
    except subprocess.TimeoutExpired:
        return 124, '', 'timeout'
    except Exception as e:
        return 1, '', str(e)

def _kubectl_base_args():
    args = ["kubectl"]
    try:
        kc = get_active_kubeconfig_path()
        if kc:
            args += ["--kubeconfig", kc]
    except Exception:
        pass
    return args

@app.route('/trivy-operator/status')
def trivy_operator_status():
    try:
        # Load kube config and relax SSL verification to avoid false negatives on self-signed clusters
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)

        # Clients
        apps_api = client.AppsV1Api()
        core_api = client.CoreV1Api()
        status = {
            'installed': False,
            'namespace': None,
            'deployment_ready': False
        }

        # 1) Try detect CRD presence (helps decide if operator was installed at least once)
        crd_present = False
        try:
            api_ext = client.ApiextensionsV1Api()
            _ = api_ext.read_custom_resource_definition('vulnerabilityreports.aquasecurity.github.io')
            crd_present = True
        except Exception:
            crd_present = False

        # 2) Check default namespace first
        found_ns = None
        try:
            ns_obj = core_api.read_namespace('trivy-system')
            if ns_obj:
                found_ns = 'trivy-system'
        except Exception:
            # namespace may be customized; continue with cluster-wide discovery
            pass

        # 3) Try to find the operator Deployment either in found_ns or cluster-wide
        operator_dep = None
        if found_ns:
            try:
                operator_dep = apps_api.read_namespaced_deployment('trivy-operator', found_ns)
            except Exception:
                operator_dep = None
        if not operator_dep:
            # Fallback: list all deployments and find by name or known labels
            try:
                for dep in apps_api.list_deployment_for_all_namespaces().items:
                    name = getattr(dep.metadata, 'name', '') or ''
                    labels = getattr(dep.metadata, 'labels', {}) or {}
                    if (
                        name == 'trivy-operator' or
                        labels.get('app.kubernetes.io/name') == 'trivy-operator' or
                        labels.get('name') == 'trivy-operator'
                    ):
                        operator_dep = dep
                        found_ns = getattr(dep.metadata, 'namespace', None)
                        break
            except Exception:
                pass

        # 4) Compute readiness and installation flags
        if operator_dep:
            ready = False
            try:
                # Prefer Available condition
                for cond in (getattr(operator_dep.status, 'conditions', []) or []):
                    if getattr(cond, 'type', '') == 'Available' and getattr(cond, 'status', '') == 'True':
                        ready = True
                        break
                # Fallback: availableReplicas >= 1
                if not ready:
                    avail = getattr(operator_dep.status, 'available_replicas', 0) or 0
                    ready = avail >= 1
            except Exception:
                ready = False
            status['namespace'] = found_ns
            status['deployment_ready'] = ready
            status['installed'] = True
        else:
            # No deployment found; still consider installed if CRD exists
            status['installed'] = bool(crd_present)
            status['namespace'] = found_ns or 'trivy-system'
            status['deployment_ready'] = False

        # Optional debugging hints for UI (ignored if not used)
        status['crd_present'] = crd_present
        return jsonify(status)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/trivy-operator/install', methods=['POST'])
def trivy_operator_install():
    """Install Trivy Operator via helm if available, else apply static manifest."""
    try:
        data = request.get_json(silent=True) or {}
        use_helm = data.get('use_helm', True)
        version = data.get('version')  # e.g. 0.31.0

        # Ensure kubeconfig
        _ = get_active_kubeconfig_path()

        if use_helm:
            # helm repo add/update, then install
            cmds = []
            base = []
            kc = get_active_kubeconfig_path()
            if kc:
                base = ["--kubeconfig", kc]
            cmds.append(["helm", "repo", "add", "aqua", "https://aquasecurity.github.io/helm-charts/"])
            cmds.append(["helm", "repo", "update"])
            install_cmd = ["helm", "upgrade", "--install", "trivy-operator", "aqua/trivy-operator", "-n", "trivy-system", "--create-namespace"]
            if version:
                install_cmd += ["--version", str(version)]
            # helm doesn’t support --kubeconfig directly; set env KUBECONFIG
            env = os.environ.copy()
            if kc:
                env['KUBECONFIG'] = kc
            for c in cmds:
                code, out, err = _run_cmd(c, timeout=90)
                if code != 0:
                    return jsonify({'error': f'helm error: {err or out}', 'cmd': c}), 500
            code, out, err = _run_cmd(install_cmd, timeout=300)
            if code != 0:
                return jsonify({'error': f'helm install error: {err or out}', 'cmd': install_cmd}), 500
            return jsonify({'ok': True, 'method': 'helm', 'output': out})
        else:
            # Fallback to static manifest apply from GitHub raw (requires network on client)
            # Prefer kubectl apply -f with local cached path if exists under yaml/
            manifest_path = os.path.join(os.path.dirname(__file__), '..', '..', 'yaml', 'trivy-operator.yaml')
            if not os.path.exists(manifest_path):
                # Try to apply remote manifest url via kubectl
                url = 'https://raw.githubusercontent.com/aquasecurity/trivy-operator/main/deploy/static/trivy-operator.yaml'
                cmd = _kubectl_base_args() + ["apply", "-f", url]
                code, out, err = _run_cmd(cmd, timeout=300)
                if code != 0:
                    return jsonify({'error': f'kubectl apply failed: {err or out}'}), 500
                return jsonify({'ok': True, 'method': 'kubectl-url', 'output': out})
            else:
                cmd = _kubectl_base_args() + ["apply", "-f", manifest_path]
                code, out, err = _run_cmd(cmd, timeout=300)
                if code != 0:
                    return jsonify({'error': f'kubectl apply failed: {err or out}'}), 500
                return jsonify({'ok': True, 'method': 'kubectl-file', 'output': out})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/trivy-operator/list-vulnerabilityreports')
def list_vulnerability_reports():
    """List VulnerabilityReport CRs across namespaces or a specific namespace."""
    try:
        namespace = request.args.get('namespace')  # optional
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        co = client.CustomObjectsApi()
        group = 'aquasecurity.github.io'
        version = 'v1alpha1'
        plural = 'vulnerabilityreports'
        if namespace and namespace.strip() and namespace != '-A':
            resp = co.list_namespaced_custom_object(group, version, namespace.strip(), plural)
        else:
            resp = co.list_cluster_custom_object(group, version, f'cluster{plural}') if False else None
            # Fallback: iterate all namespaces when cluster list not available for namespaced resource
            core = client.CoreV1Api()
            ns_list = [ns.metadata.name for ns in core.list_namespace().items]
            items = []
            for ns in ns_list:
                try:
                    r = co.list_namespaced_custom_object(group, version, ns, plural)
                    items.extend(r.get('items', []))
                except Exception:
                    continue
            resp = {'items': items}

        out = []
        for it in resp.get('items', []):
            md = it.get('metadata', {})
            rep = it.get('report', {})
            sumry = rep.get('summary', {})
            art = rep.get('artifact', {})
            out.append({
                'name': md.get('name'),
                'namespace': md.get('namespace'),
                'repository': art.get('repository'),
                'tag': art.get('tag'),
                'scanner': (rep.get('scanner') or {}).get('name'),
                'summary': {
                    'critical': sumry.get('criticalCount'),
                    'high': sumry.get('highCount'),
                    'medium': sumry.get('mediumCount'),
                    'low': sumry.get('lowCount'),
                    'unknown': sumry.get('unknownCount'),
                },
                'updateTimestamp': rep.get('updateTimestamp'),
            })
        return jsonify({'items': out})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/trivy-operator/scan', methods=['POST'])
def trivy_operator_scan():
    """Trigger on-demand scan by annotating workloads with trivy-operator scan annotation.
    Body: { namespace?: str, target?: 'all'|'workload', kind?: str, name?: str }
    """
    try:
        data = request.get_json(force=True) or {}
        namespace = data.get('namespace')
        target = data.get('target') or 'all'
        kind = (data.get('kind') or '').lower()
        name = data.get('name')

        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)

        anno = {
            'trivy-operator.aquasecurity.github.io/scan': 'true',
            'trivy-operator.aquasecurity.github.io/scan-ts': datetime.utcnow().isoformat() + 'Z'
        }

        patched = []
        errors = []

        def patch_meta(obj_kind, ns, nm):
            try:
                if obj_kind == 'deployment':
                    api = client.AppsV1Api()
                    api.patch_namespaced_deployment(nm, ns, {'metadata': {'annotations': anno}})
                elif obj_kind == 'statefulset':
                    api = client.AppsV1Api()
                    api.patch_namespaced_stateful_set(nm, ns, {'metadata': {'annotations': anno}})
                elif obj_kind == 'daemonset':
                    api = client.AppsV1Api()
                    api.patch_namespaced_daemon_set(nm, ns, {'metadata': {'annotations': anno}})
                elif obj_kind == 'replicaset':
                    api = client.AppsV1Api()
                    api.patch_namespaced_replica_set(nm, ns, {'metadata': {'annotations': anno}})
                elif obj_kind == 'job':
                    api = client.BatchV1Api()
                    api.patch_namespaced_job(nm, ns, {'metadata': {'annotations': anno}})
                elif obj_kind == 'cronjob':
                    api = client.BatchV1Api()
                    api.patch_namespaced_cron_job(nm, ns, {'metadata': {'annotations': anno}})
                elif obj_kind == 'pod':
                    api = client.CoreV1Api()
                    api.patch_namespaced_pod(nm, ns, {'metadata': {'annotations': anno}})
                elif obj_kind in ('replicationcontroller', 'rc'):
                    api = client.CoreV1Api()
                    api.patch_namespaced_replication_controller(nm, ns, {'metadata': {'annotations': anno}})
                else:
                    raise ValueError(f'Unsupported kind: {obj_kind}')
                patched.append({'kind': obj_kind, 'namespace': ns, 'name': nm})
            except Exception as e:
                errors.append({'kind': obj_kind, 'namespace': ns, 'name': nm, 'error': str(e)})

        def list_and_patch_all_in_ns(ns):
            apps = client.AppsV1Api()
            batch = client.BatchV1Api()
            corev1 = client.CoreV1Api()
            # deployments
            for d in apps.list_namespaced_deployment(ns).items:
                patch_meta('deployment', ns, d.metadata.name)
            # statefulsets
            for s in apps.list_namespaced_stateful_set(ns).items:
                patch_meta('statefulset', ns, s.metadata.name)
            # daemonsets
            for ds in apps.list_namespaced_daemon_set(ns).items:
                patch_meta('daemonset', ns, ds.metadata.name)
            # jobs
            for j in batch.list_namespaced_job(ns).items:
                patch_meta('job', ns, j.metadata.name)
            # cronjobs
            for cj in batch.list_namespaced_cron_job(ns).items:
                patch_meta('cronjob', ns, cj.metadata.name)
            # pods
            for p in corev1.list_namespaced_pod(ns).items:
                patch_meta('pod', ns, p.metadata.name)

        if target == 'workload' and kind and name and namespace:
            patch_meta(kind, namespace, name)
        else:
            # all in namespace (or across all namespaces if none given)
            if namespace:
                list_and_patch_all_in_ns(namespace)
            else:
                core = client.CoreV1Api()
                for ns in [n.metadata.name for n in core.list_namespace().items]:
                    list_and_patch_all_in_ns(ns)

        return jsonify({'ok': True, 'patched': patched, 'errors': errors})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/trivy-operator/get-vulnerabilityreport')
def get_vulnerability_report():
    """Get a single VulnerabilityReport with vulnerabilities for a specific namespace/name."""
    try:
        namespace = request.args.get('namespace')
        name = request.args.get('name')
        if not namespace or not name:
            return jsonify({'error': 'namespace and name are required'}), 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        co = client.CustomObjectsApi()
        group = 'aquasecurity.github.io'
        version = 'v1alpha1'
        plural = 'vulnerabilityreports'
        obj = co.get_namespaced_custom_object(group, version, namespace, plural, name)
        rep = obj.get('report') or {}
        vulns = rep.get('vulnerabilities') or []
        # Normalize fields commonly used on UI
        items = []
        for v in vulns:
            items.append({
                'vulnerabilityID': v.get('vulnerabilityID') or v.get('id'),
                'title': v.get('title'),
                'severity': v.get('severity'),
                'resource': v.get('resource'),
                'installedVersion': v.get('installedVersion'),
                'fixedVersion': v.get('fixedVersion'),
                'score': v.get('score') or (v.get('cvss') or {}).get('V3Score') or (v.get('cvss') or {}).get('V2Score'),
                'primaryLink': v.get('primaryLink') or (v.get('links')[0] if isinstance(v.get('links'), list) and v.get('links') else None),
                'target': v.get('target'),
            })
        return jsonify({'name': name, 'namespace': namespace, 'vulnerabilities': items})
    except ApiException as e:
        try:
            return jsonify({'error': e.body}), e.status
        except Exception:
            return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- Kubernetes Explorer API ---

@app.route('/k8s-explorer/ingresses')
def k8s_explorer_ingresses():
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        kube_client = type('KubeClient', (), {})()
        kube_client.networking_v1 = client.NetworkingV1Api()
        ingresses = kube_client.networking_v1.list_ingress_for_all_namespaces().items
        result = [{'name': i.metadata.name, 'namespace': i.metadata.namespace} for i in ingresses]
        return jsonify({'ingresses': result})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/k8s-explorer/ingress')
def k8s_explorer_ingress_detail():
    namespace = request.args.get('namespace')
    name = request.args.get('name')
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        kube_client = type('KubeClient', (), {})()
        kube_client.networking_v1 = client.NetworkingV1Api()
        kube_client.core_v1 = client.CoreV1Api()
        ing = kube_client.networking_v1.read_namespaced_ingress(name, namespace)
        # İlk backend service'i bul
        svc_name = None
        if ing.spec.rules:
            for rule in ing.spec.rules:
                http = getattr(rule, 'http', None)
                if http and http.paths:
                    for path in http.paths:
                        backend = getattr(path, 'backend', None)
                        if backend and getattr(backend, 'service', None):
                            svc_name = backend.service.name
                            break
                        elif backend and getattr(backend, 'service_name', None):
                            svc_name = backend.service_name
                            break
                if svc_name:
                    break
        service = {'name': svc_name} if svc_name else None
        return jsonify({'service': service})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/k8s-explorer/service')
def k8s_explorer_service_detail():
    namespace = request.args.get('namespace')
    name = request.args.get('name')
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        kube_client = type('KubeClient', (), {})()
        kube_client.core_v1 = client.CoreV1Api()
        kube_client.apps_v1 = client.AppsV1Api()
        svc = kube_client.core_v1.read_namespaced_service(name, namespace)
        service_labels = svc.metadata.labels or {}
        service_selector = svc.spec.selector or {}
        deployments = kube_client.apps_v1.list_namespaced_deployment(namespace).items
        matched = []
        for dep in deployments:
            dep_selector = getattr(dep.spec.selector, 'match_labels', {}) or {}
            # 1. Service label ile deployment selector eşleşmesi
            if service_labels and dep_selector and all(service_labels.get(k) == v for k, v in dep_selector.items()):
                matched.append({'name': dep.metadata.name, 'match_type': 'label', 'deployment_selector': dep_selector})
                continue
            # 2. Service selector ile deployment selector birebir eşleşmesi
            if service_selector and dep_selector and service_selector == dep_selector:
                matched.append({'name': dep.metadata.name, 'match_type': 'selector', 'deployment_selector': dep_selector})
        if matched:
            return jsonify({'deployments': matched})
        else:
            if not service_selector:
                return jsonify({'deployments': [], 'error': 'Service selector yok veya boş, deployment eşleşmesi yapılamaz.'})
            else:
                return jsonify({'deployments': [], 'error': 'Service selector veya label ile eşleşen deployment bulunamadı.'})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/k8s-explorer/service-details')
def k8s_explorer_service_details():
    namespace = request.args.get('namespace')
    name = request.args.get('name')
    if not namespace or not name:
        return jsonify({'error': 'namespace ve name zorunlu'}), 400
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        core_v1 = client.CoreV1Api()
        svc = core_v1.read_namespaced_service(name, namespace)
        md = svc.metadata
        spec = svc.spec
        status = getattr(svc, 'status', None)
        ports = []
        for p in (spec.ports or []) if spec else []:
            ports.append({
                'name': getattr(p, 'name', None),
                'port': getattr(p, 'port', None),
                'protocol': getattr(p, 'protocol', None),
                'targetPort': getattr(p, 'target_port', None),
                'nodePort': getattr(p, 'node_port', None)
            })
        details = {
            'metadata': {
                'name': getattr(md, 'name', None),
                'namespace': getattr(md, 'namespace', None),
                'labels': md.labels or {},
                'annotations': md.annotations or {},
                'creation_timestamp': md.creation_timestamp.isoformat() if getattr(md, 'creation_timestamp', None) else None,
                'uid': getattr(md, 'uid', None)
            },
            'spec': {
                'type': getattr(spec, 'type', None) if spec else None,
                'cluster_ip': getattr(spec, 'cluster_ip', None) if spec else None,
                'external_ips': getattr(spec, 'external_ips', None) if spec else None,
                'selector': getattr(spec, 'selector', None) if spec else None,
                'session_affinity': getattr(spec, 'session_affinity', None) if spec else None,
                'ports': ports
            },
            'status': {
                'load_balancer': getattr(getattr(status, 'load_balancer', None), 'ingress', None) if status else None
            }
        }
        return jsonify({'service': details})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/k8s-explorer/deployment')
def k8s_explorer_deployment_detail():
    namespace = request.args.get('namespace')
    name = request.args.get('name')
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        kube_client = type('KubeClient', (), {})()
        kube_client.apps_v1 = client.AppsV1Api()
        kube_client.core_v1 = client.CoreV1Api()
        dep = kube_client.apps_v1.read_namespaced_deployment(name, namespace)
        # Deployment'ın podlarını bul
        selector = dep.spec.selector.match_labels or {}
        pod_names = []
        if selector:
            label_selector = ','.join([f"{k}={v}" for k,v in selector.items()])
            pods = kube_client.core_v1.list_namespaced_pod(namespace, label_selector=label_selector).items
            pod_names = [p.metadata.name for p in pods]
        return jsonify({'pods': pod_names})
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/rbac-risky-roles')
def rbac_risky_roles():
    """
    RBAC Risky Roles
    ---
    get:
      description: List risky RBAC roles (wildcard permissions)
      responses:
        200:
          description: Risky roles
          content:
            application/json:
              schema:
                type: object
                properties:
                  risky_roles:
                    type: array
                    items:
                      type: object
    """
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        kube_client = type('KubeClient', (), {})()
        kube_client.rbac_v1 = client.RbacAuthorizationV1Api()
    except Exception as e:
        return jsonify({'error': str(e)})
    risky = []
    # ClusterRoles
    try:
        cluster_roles = kube_client.rbac_v1.list_cluster_role().items
        for cr in cluster_roles:
            for rule in cr.rules or []:
                if ('*' in (rule.verbs or []) or 'all' in (rule.verbs or [])) and ('*' in (rule.resources or []) or 'all' in (rule.resources or [])):
                    risky.append({
                        'namespace': '',
                        'name': cr.metadata.name,
                        'type': 'ClusterRole',
                        'rules': str(rule)
                    })
    except Exception:
        pass
    # Roles (namespace scoped)
    try:
        namespaces = [ns.metadata.name for ns in kube_client.rbac_v1.list_namespace().items]
        for ns in namespaces:
            try:
                roles = kube_client.rbac_v1.list_namespaced_role(ns).items
                for r in roles:
                    for rule in r.rules or []:
                        if ('*' in (rule.verbs or []) or 'all' in (rule.verbs or [])) and ('*' in (rule.resources or []) or 'all' in (rule.resources or [])):
                            risky.append({
                                'namespace': ns,
                                'name': r.metadata.name,
                                'type': 'Role',
                                'rules': str(rule)
                            })
            except Exception:
                continue
    except Exception:
        pass
    return jsonify({'risky_roles': risky})


# Privileged container kontrolü API
@app.route('/privileged-containers')
def privileged_containers():
    """
    Privileged Containers
    ---
    get:
      description: List privileged containers or root containers
      parameters:
        - in: query
          name: allpods
          schema:
            type: string
          description: Show all pods (1) or only privileged (default)
        - in: query
          name: rootcheck
          schema:
            type: string
          description: Show root containers (1) or privileged (default)
      responses:
        200:
          description: Privileged/root containers
          content:
            application/json:
              schema:
                type: object
    """
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        kube_client = type('KubeClient', (), {})()
        kube_client.core_v1 = client.CoreV1Api()
    except Exception as e:
        return jsonify({'error': str(e)})
    show_all = request.args.get('allpods') == '1'
    root_check = request.args.get('rootcheck') == '1'
    pods_result = []
    privileged_flat = []
    namespaces = [ns.metadata.name for ns in kube_client.core_v1.list_namespace().items]
    for ns in namespaces:
        pods = kube_client.core_v1.list_namespaced_pod(ns).items
        for pod in pods:
            priv_containers = []
            root_containers = []
            for container in pod.spec.containers:
                sec_ctx = getattr(container, 'security_context', None) or getattr(container, 'securityContext', None)
                privileged = False
                run_as_user = None
                run_as_non_root = None
                if sec_ctx:
                    privileged = getattr(sec_ctx, 'privileged', False)
                    run_as_user = getattr(sec_ctx, 'run_as_user', None)
                    if run_as_user is None:
                        run_as_user = getattr(sec_ctx, 'runAsUser', None)
                    run_as_non_root = getattr(sec_ctx, 'run_as_non_root', None)
                    if run_as_non_root is None:
                        run_as_non_root = getattr(sec_ctx, 'runAsNonRoot', None)
                if privileged:
                    priv_containers.append(container.name)
                    privileged_flat.append({
                        'namespace': ns,
                        'pod': pod.metadata.name,
                        'container': container.name
                    })
                # root check: runAsUser: 0 veya runAsNonRoot: false
                if (run_as_user == 0) or (run_as_non_root is False):
                    root_containers.append(container.name)
            if show_all:
                if root_check:
                    pods_result.append({
                        'namespace': ns,
                        'pod': pod.metadata.name,
                        'root_containers': root_containers
                    })
                else:
                    pods_result.append({
                        'namespace': ns,
                        'pod': pod.metadata.name,
                        'privileged_containers': priv_containers
                    })
    if show_all:
        return jsonify({'pods': pods_result})
    else:
        return jsonify({'privileged': privileged_flat})

# Privileged container sayfası

@app.route('/privileged-containers-page')
def privileged_containers_page():
    return render_template('privileged_containers.html')

# Exec olayları sayfası (tablo)

@app.route('/exec-events-page')
def exec_events_page():
    return render_template('exec_events.html')


@app.route('/')
def index():
    return render_template('index.html')



@app.route('/vulnerabilities')
def vulnerabilities():
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        kube_client = type('KubeClient', (), {})()
        kube_client.core_v1 = client.CoreV1Api()
        kube_client.apps_v1 = client.AppsV1Api()
        kube_client.networking_v1 = client.NetworkingV1Api()
    except Exception as e:
        return render_template('vulnerabilities.html', error=str(e))
    
    scanner = K8sScanner(kube_client)
    all_vulnerabilities = {}
    pod_images = {}
    
    selected_namespace = request.args.get('namespace', 'all')
    
    namespaces = [ns.metadata.name for ns in kube_client.core_v1.list_namespace().items]
    
    if selected_namespace != 'all' and selected_namespace in namespaces:
        target_namespaces = [selected_namespace]
    else:
        target_namespaces = namespaces
    
    for ns in target_namespaces:
        deployments = kube_client.apps_v1.list_namespaced_deployment(ns).items
        for dep in deployments:
            vulns = scanner.list_vulnerabilities(dep)
            dep_key = f"{ns}/{dep.metadata.name}"
            if vulns:
                all_vulnerabilities[dep_key] = vulns
            # Pod image bilgisini ekle
            if dep.spec.template.spec.containers:
                pod_images[dep_key] = ', '.join([c.image for c in dep.spec.template.spec.containers])
    
    return render_template('vulnerabilities.html', 
                         vulnerabilities=all_vulnerabilities, 
                         pod_images=pod_images,
                         all_namespaces=namespaces,
                         selected_namespace=selected_namespace)




@app.route('/exec-events')
def exec_events():
    """
    Kubernetes Events (kubectl get events)
    ---
    get:
      description: List recent Kubernetes events from API
      responses:
        200:
          description: Events
          content:
            application/json:
              schema:
                type: object
    """
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        core_v1 = client.CoreV1Api()
        k8s_events = core_v1.list_event_for_all_namespaces().items
        events = []
        for ev in k8s_events:
            events.append({
                'time': getattr(ev, 'last_timestamp', None) or getattr(ev, 'event_time', None) or getattr(ev, 'first_timestamp', None) or '',
                'namespace': getattr(ev.metadata, 'namespace', ''),
                'name': getattr(ev, 'involved_object', None) and getattr(ev.involved_object, 'name', ''),
                'kind': getattr(ev, 'involved_object', None) and getattr(ev.involved_object, 'kind', ''),
                'type': getattr(ev, 'type', ''),
                'reason': getattr(ev, 'reason', ''),
                'message': getattr(ev, 'message', ''),
                'source': getattr(ev, 'source', None) and getattr(ev.source, 'component', ''),
            })
        # Son 100 event'i zamana göre tersten sırala
        events = sorted(events, key=lambda x: str(x['time']), reverse=True)[:100]
        return jsonify({'events': events})
    except Exception as e:
        return jsonify({'error': str(e), 'events': []}), 500


# =============================================================================
# PSS / PSA (Pod Security Standards / Pod Security Admission) Analizi
# _evaluate_pod_pss_compliance, update_pss_cache, start_pss_cache -> background.py
# =============================================================================

# --- PSS API Endpoint'leri ---

@app.route('/k8s-explorer/pss-summary')
def k8s_explorer_pss_summary():
    """PSS Summary — tüm namespace'ler için PSA etiketleri ve pod uyumluluk istatistikleri.
    ---
    tags:
      - pss
    get:
      description: >
        Her namespace için pod-security.kubernetes.io/{enforce,warn,audit} etiketlerini
        ve enforce profiline göre hesaplanmış compliant_pods / noncompliant_pods sayılarını döner.
        Etiket yoksa labels=null döner. enforce etiketi yoksa compliant_pods/noncompliant_pods null olur.
        Cache dolmamışsa {"loading": true} döner.
      responses:
        200:
          description: PSS özet verisi
          schema:
            type: object
            properties:
              namespaces:
                type: array
                items:
                  type: object
        500:
          description: Sunucu hatası
    """
    try:
        now = time.time()
        if not _bg.pss_cache or (now - _bg.pss_cache_time > _bg.PSS_CACHE_TTL):
            update_pss_cache()
        if not _bg.pss_cache:
            return jsonify({'loading': True})
        return jsonify(_bg.pss_cache)
    except Exception as e:
        print('PSS SUMMARY ERROR:', e, file=sys.stderr)
        return jsonify({'error': str(e)}), 500


@app.route('/k8s-explorer/pss-namespace-detail')
def k8s_explorer_pss_namespace_detail():
    """PSS Namespace Detail — tek namespace için pod bazlı uyumluluk detayı.
    ---
    tags:
      - pss
    get:
      description: >
        Belirtilen namespace'teki her pod için compliant durumu ve violations listesini döner.
        Hangi profilin uygulandığını (enforce etiketi) da içerir.
      parameters:
        - in: query
          name: namespace
          schema:
            type: string
          required: true
          description: Detayı alınacak namespace adı
      responses:
        200:
          description: Pod bazlı uyumluluk detayı
          schema:
            type: object
            properties:
              namespace:
                type: string
              profile:
                type: string
              pods:
                type: array
        400:
          description: namespace parametresi eksik
        404:
          description: Namespace bulunamadı
        500:
          description: Sunucu hatası
    """
    namespace = request.args.get('namespace', '').strip()
    if not namespace:
        return jsonify({'error': 'namespace parametresi zorunlu'}), 400
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        core_v1 = client.CoreV1Api()

        # Namespace'i oku — PSA enforce etiketini belirle
        try:
            ns_obj = core_v1.read_namespace(namespace)
        except ApiException as ae:
            if ae.status == 404:
                return jsonify({'error': f'Namespace bulunamadı: {namespace}'}), 404
            raise

        ns_labels = ns_obj.metadata.labels or {}
        _prefix = 'pod-security.kubernetes.io/'
        profile = ns_labels.get(f'{_prefix}enforce')  # None olabilir

        pods = core_v1.list_namespaced_pod(namespace).items
        pods_result = []

        for pod in pods:
            if profile is not None:
                try:
                    compliant, violations = _evaluate_pod_pss_compliance(pod, profile)
                except Exception as _eval_err:
                    compliant = False
                    violations = [f"Değerlendirme hatası: {str(_eval_err)}"]
            else:
                # enforce etiketi yok; uyumluluk hesaplanamaz
                compliant = None
                violations = []

            pods_result.append({
                'name': pod.metadata.name,
                'compliant': compliant,
                'violations': violations,
            })

        return jsonify({
            'namespace': namespace,
            'profile': profile,
            'pods': pods_result,
        })
    except Exception as e:
        print('PSS NAMESPACE DETAIL ERROR:', e, file=sys.stderr)
        return jsonify({'error': str(e)}), 500


# --- PSS Sayfa Route'u ---

@app.route('/pod-security-standards')
def pod_security_standards():
    """Pod Security Standards analiz sayfasını render eder."""
    return render_template('pod_security_standards.html')


# ---------------------------------------------------------------------------
# NetworkPolicy Kapsam Analizi — cache, yardımcı fonksiyonlar -> background.py
# ---------------------------------------------------------------------------

@app.route('/k8s-explorer/netpol-coverage-summary')
def k8s_explorer_netpol_coverage_summary():
    """NetworkPolicy Kapsam Özeti — cluster geneli namespace + pod kapsam istatistikleri.
    ---
    tags:
      - netpol
    get:
      description: >
        Tüm namespace'ler için NetworkPolicy varlık durumunu, her namespace'teki
        covered/uncovered pod sayılarını ve cluster geneli kapsam yüzdelerini döner.
        Cache dolmamışsa {"loading": true} döner; cache doluysa {"cluster_summary": {...},
        "namespaces": [...]} şeklinde tam veriyi döner.
      responses:
        200:
          description: NetworkPolicy kapsam özet verisi
          schema:
            type: object
            properties:
              cluster_summary:
                type: object
              namespaces:
                type: array
        500:
          description: Sunucu hatası
    """
    try:
        now = time.time()
        if not _bg.netpol_coverage_cache or (now - _bg.netpol_coverage_cache_time > _bg.NETPOL_COVERAGE_CACHE_TTL):
            update_netpol_coverage_cache()
        if not _bg.netpol_coverage_cache:
            return jsonify({'loading': True})
        return jsonify(_bg.netpol_coverage_cache)
    except Exception as e:
        print('NETPOL COVERAGE SUMMARY ERROR:', e, file=sys.stderr)
        return jsonify({'error': str(e)}), 500


@app.route('/k8s-explorer/netpol-coverage-ns-detail')
def k8s_explorer_netpol_coverage_ns_detail():
    """NetworkPolicy Kapsam Namespace Detayı — tek namespace için korumasız pod listesi.
    ---
    tags:
      - netpol
    get:
      description: >
        Belirtilen namespace'teki NetworkPolicy listesini, her policy'nin podSelector özetini
        ve hiçbir NetworkPolicy tarafından kapsanmayan pod'ların adlarını + label'larını döner.
      parameters:
        - in: query
          name: namespace
          schema:
            type: string
          required: true
          description: Detayı alınacak namespace adı
      responses:
        200:
          description: Namespace başına korumasız pod detayı
          schema:
            type: object
            properties:
              namespace:
                type: string
              policy_count:
                type: integer
              policies:
                type: array
              unprotected_pods:
                type: array
              total_pods:
                type: integer
              covered_pods:
                type: integer
              uncovered_pods:
                type: integer
        400:
          description: namespace parametresi eksik
        500:
          description: Sunucu hatası
    """
    namespace = request.args.get('namespace', '').strip()
    if not namespace:
        return jsonify({'error': 'namespace parametresi zorunlu'}), 400
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        core_v1 = client.CoreV1Api()
        net_v1 = client.NetworkingV1Api()

        ns_netpols = net_v1.list_namespaced_network_policy(namespace).items
        policy_count = len(ns_netpols)

        policies_summary = []
        for np in ns_netpols:
            pod_selector = getattr(np.spec, 'pod_selector', None) if np.spec else None
            policies_summary.append({
                'name': np.metadata.name,
                'pod_selector_summary': _netpol_pod_selector_summary(pod_selector),
            })

        pods = core_v1.list_namespaced_pod(namespace).items
        total_pods = len(pods)

        unprotected_pods = []
        covered_count = 0

        for pod in pods:
            pod_labels = pod.metadata.labels or {}
            matched = False
            if policy_count > 0:
                for np in ns_netpols:
                    pod_selector = getattr(np.spec, 'pod_selector', None) if np.spec else None
                    if _pod_matches_pod_selector(pod_labels, pod_selector):
                        matched = True
                        break
            if matched:
                covered_count += 1
            else:
                unprotected_pods.append({
                    'name': pod.metadata.name,
                    'labels': pod_labels,
                })

        covered_pods = covered_count
        uncovered_pods = total_pods - covered_count

        return jsonify({
            'namespace': namespace,
            'policy_count': policy_count,
            'policies': policies_summary,
            'unprotected_pods': unprotected_pods,
            'total_pods': total_pods,
            'covered_pods': covered_pods,
            'uncovered_pods': uncovered_pods,
        })
    except Exception as e:
        print('NETPOL COVERAGE NS DETAIL ERROR:', e, file=sys.stderr)
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Arka plan cache thread'lerini başlat (tüm import'lar ve registrasyonlar sonrasında)
# ---------------------------------------------------------------------------
start_workload_stats_cache()
start_pods_summary_cache()
start_metrics_sampler()
start_pss_cache()
start_netpol_coverage_cache()
