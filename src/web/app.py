from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from scanner.k8s_scanner import K8sScanner
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from scanner.k8s_scanner import K8sScanner
from kubernetes import client, config
from datetime import datetime
from flasgger import Swagger
import threading, time, sys, traceback, os, subprocess, json, yaml, urllib.parse, requests
import yaml
import time
import traceback
import urllib.parse
import sys
from flask import session, send_from_directory
import requests
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from scanner.k8s_scanner import K8sScanner
from kubernetes import client, config
import os
import json
from datetime import datetime
from flasgger import Swagger
CORS_ORIGINS = ["http://localhost:8080", "http://127.0.0.1:8080"]

app = Flask(__name__)
CORS(app, origins=CORS_ORIGINS)
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

harbor_trivy_cache = {}
harbor_trivy_cache_time = {}


# Prometheus endpoint autodiscovery (Kubernetes üzerinden)
@app.route('/k8s-explorer/prometheus-url')
def prometheus_url():
    try:
        config.load_kube_config()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        core_v1 = client.CoreV1Api()
        # Tüm namespace'lerde controller-prometheus veya prometheus içeren servisleri ara
        for ns in [ns.metadata.name for ns in core_v1.list_namespace().items]:
            for svc in core_v1.list_namespaced_service(ns).items:
                labels = svc.metadata.labels or {}
                name = svc.metadata.name or ''
                if (
                    'prometheus' in name or
                    'prometheus' in labels.get('app', '') or
                    'prometheus' in labels.get('component', '') or
                    'controller' in name or
                    'controller' in labels.get('app', '') or
                    'controller' in labels.get('component', '')
                ):
                    ports = svc.spec.ports or []
                    port = None
                    for p in ports:
                        if p.port == 9090:
                            port = p
                            break
                    if not port and ports:
                        port = ports[0]
                    if port:
                        # NodePort varsa dışarıdan erişim için node IP ile dön
                        if svc.spec.type == 'NodePort' and port.node_port:
                            nodes = core_v1.list_node().items
                            node_ip = None
                            for node in nodes:
                                for addr in node.status.addresses or []:
                                    if addr.type == 'ExternalIP':
                                        node_ip = addr.address
                                        break
                                if not node_ip:
                                    for addr in node.status.addresses or []:
                                        if addr.type == 'InternalIP':
                                            node_ip = addr.address
                                            break
                                if node_ip:
                                    url = f'http://{node_ip}:{port.node_port}'
                                    return jsonify({'url': url, 'namespace': ns, 'service': name})
                        # Yoksa ClusterIP ile dön (sadece cluster içi erişim için)
                        if svc.spec.cluster_ip and svc.spec.cluster_ip != 'None':
                            url = f'http://{svc.spec.cluster_ip}:{port.port}'
                            return jsonify({'url': url, 'namespace': ns, 'service': name})
        return jsonify({'error': 'Prometheus servisi bulunamadı'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# StatefulSets summary for StatefulSets tab
@app.route('/k8s-explorer/statefulsets-summary')
def statefulsets_summary():
    try:
        namespace = request.args.get('namespace')
        config.load_kube_config()
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
        config.load_kube_config()
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
        config.load_kube_config()
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
        config.load_kube_config()
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
        config.load_kube_config()
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
        config.load_kube_config()
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
        config.load_kube_config()
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
        config.load_kube_config()
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
        config.load_kube_config()
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
        config.load_kube_config()
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
        
        config.load_kube_config()
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
        
        config.load_kube_config()
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
        config.load_kube_config()
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
                
                containers.append({
                    'name': container.name,
                    'image': container.image,
                    'restart_count': container_status.restart_count if container_status else 0
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
# YAML Linter API
@app.route('/yaml-lint-api', methods=['POST'])
def yaml_lint_api():
    try:
        data = request.get_json(force=True)
        yaml_str = data.get('yaml', '')
        if not yaml_str.strip():
            return jsonify({'ok': False, 'error': 'YAML içeriği boş'}), 200
        try:
            yaml.safe_load(yaml_str)
        except yaml.YAMLError as e:
            return jsonify({'ok': False, 'error': str(e)}), 200
        return jsonify({'ok': True}), 200
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500



# Generic delete endpoint for various K8s resources
@app.route('/k8s-explorer/delete', methods=['POST', 'DELETE'])
def k8s_explorer_delete():
    try:
        # Accept parameters from querystring OR JSON body (frontend uses JSON DELETE)
        data = {}
        try:
            data = request.get_json(force=False) or {}
        except Exception:
            data = {}

        obj_type = (request.args.get('type') or data.get('type') or '').lower()
        namespace = request.args.get('namespace') or data.get('namespace')
        name = request.args.get('name') or data.get('name')

        if not obj_type or not namespace or not name:
            return jsonify({'error': 'type, namespace ve name zorunlu'}), 400

        config.load_kube_config()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)

        core_v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()

        # Perform deletion depending on resource type
        if obj_type == 'pod':
            core_v1.delete_namespaced_pod(name=name, namespace=namespace, grace_period_seconds=30)
            # update pods cache immediately
            try:
                update_pods_summary_cache()
            except Exception:
                pass
            return jsonify({'ok': True, 'deleted': {'type': 'pod', 'namespace': namespace, 'name': name}}), 200

        elif obj_type == 'service':
            core_v1.delete_namespaced_service(name=name, namespace=namespace)
            return jsonify({'ok': True, 'deleted': {'type': 'service', 'namespace': namespace, 'name': name}}), 200

        elif obj_type in ('deployment', 'deployments'):
            apps_v1.delete_namespaced_deployment(name=name, namespace=namespace, body=client.V1DeleteOptions())
            return jsonify({'ok': True, 'deleted': {'type': 'deployment', 'namespace': namespace, 'name': name}}), 200

        elif obj_type in ('replicaset', 'replicasets'):
            apps_v1.delete_namespaced_replica_set(name=name, namespace=namespace, body=client.V1DeleteOptions())
            return jsonify({'ok': True}), 200

        elif obj_type in ('daemonset', 'daemonsets'):
            apps_v1.delete_namespaced_daemon_set(name=name, namespace=namespace, body=client.V1DeleteOptions())
            return jsonify({'ok': True}), 200

        elif obj_type in ('statefulset', 'statefulsets'):
            apps_v1.delete_namespaced_stateful_set(name=name, namespace=namespace, body=client.V1DeleteOptions())
            return jsonify({'ok': True}), 200

        else:
            return jsonify({'error': f'Unsupported resource type: {obj_type}'}), 400

    except client.exceptions.ApiException as api_exc:
        # Kubernetes client errors: return message and code
        try:
            msg = api_exc.body or str(api_exc)
        except Exception:
            msg = str(api_exc)
        return jsonify({'error': 'Kubernetes API error', 'details': msg}), getattr(api_exc, 'status', 500)
    except Exception as e:
        # Generic error
        tb = traceback.format_exc()
        return jsonify({'error': str(e), 'trace': tb}), 500


# Workload stats API for Overview pie charts

# --- Workload Stats In-Memory Cache ---

workload_stats_cache = None
workload_stats_cache_time = 0
WORKLOAD_STATS_CACHE_TTL = 20  # 20 saniye

import threading
def update_workload_stats_cache():
    global workload_stats_cache, workload_stats_cache_time
    try:
        config.load_kube_config()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        core_v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()
        batch_v1 = client.BatchV1Api()
        batch_v1beta1 = client.BatchV1beta1Api() if hasattr(client, 'BatchV1beta1Api') else None
        # Pods
        pods = core_v1.list_pod_for_all_namespaces().items
        pods_ready = 0
        pods_pending = 0
        pods_failed = 0
        for pod in pods:
            phase = getattr(pod.status, 'phase', '')
            if phase == 'Running':
                pods_ready += 1
            elif phase == 'Pending':
                pods_pending += 1
            elif phase in ('Failed', 'CrashLoopBackOff', 'Unknown'):
                pods_failed += 1
        # Deployments
        deployments = apps_v1.list_deployment_for_all_namespaces().items
        dep_ready = 0
        dep_failed = 0
        for dep in deployments:
            ready = getattr(dep.status, 'ready_replicas', 0) or 0
            replicas = getattr(dep.status, 'replicas', 0) or 0
            if ready == replicas and replicas > 0:
                dep_ready += 1
            else:
                dep_failed += 1
        # DaemonSets
        daemonsets = apps_v1.list_daemon_set_for_all_namespaces().items
        ds_ready = 0
        ds_failed = 0
        for ds in daemonsets:
            desired = getattr(ds.status, 'desired_number_scheduled', 0) or 0
            ready = getattr(ds.status, 'number_ready', 0) or 0
            if desired == ready and desired > 0:
                ds_ready += 1
            else:
                ds_failed += 1
        # StatefulSets
        statefulsets = apps_v1.list_stateful_set_for_all_namespaces().items
        ss_ready = 0
        ss_failed = 0
        for ss in statefulsets:
            ready = getattr(ss.status, 'ready_replicas', 0) or 0
            replicas = getattr(ss.status, 'replicas', 0) or 0
            if ready == replicas and replicas > 0:
                ss_ready += 1
            else:
                ss_failed += 1
        # ReplicaSets
        replicasets = apps_v1.list_replica_set_for_all_namespaces().items
        rs_ready = 0
        rs_failed = 0
        for rs in replicasets:
            ready = getattr(rs.status, 'ready_replicas', 0) or 0
            replicas = getattr(rs.status, 'replicas', 0) or 0
            if ready == replicas and replicas > 0:
                rs_ready += 1
            else:
                rs_failed += 1
        # Jobs
        jobs = batch_v1.list_job_for_all_namespaces().items
        jobs_ready = 0
        jobs_failed = 0
        for job in jobs:
            succeeded = getattr(job.status, 'succeeded', 0) or 0
            failed = getattr(job.status, 'failed', 0) or 0
            if succeeded > 0:
                jobs_ready += 1
            elif failed > 0:
                jobs_failed += 1
        # CronJobs
        cronjobs_ready = 0
        cronjobs_failed = 0
        cronjobs = []
        try:
            if hasattr(batch_v1, 'list_cron_job_for_all_namespaces'):
                cronjobs = batch_v1.list_cron_job_for_all_namespaces().items
            elif batch_v1beta1:
                cronjobs = batch_v1beta1.list_cron_job_for_all_namespaces().items
        except Exception as cronjob_exc:
            if batch_v1beta1:
                try:
                    cronjobs = batch_v1beta1.list_cron_job_for_all_namespaces().items
                except Exception:
                    cronjobs = []
            else:
                cronjobs = []
        for cj in cronjobs:
            last_schedule = getattr(cj.status, 'last_schedule_time', None)
            if last_schedule:
                cronjobs_ready += 1
            else:
                cronjobs_failed += 1
        workload_stats_cache = {
            'pods': {
                'ready': pods_ready,
                'pending': pods_pending,
                'failed': pods_failed
            },
            'deployments': {'ready': dep_ready, 'failed': dep_failed},
            'daemonsets': {'ready': ds_ready, 'failed': ds_failed},
            'statefulsets': {'ready': ss_ready, 'failed': ss_failed},
            'replicasets': {'ready': rs_ready, 'failed': rs_failed},
            'jobs': {'ready': jobs_ready, 'failed': jobs_failed},
            'cronjobs': {'ready': cronjobs_ready, 'failed': cronjobs_failed}
        }
        workload_stats_cache_time = time.time()
    except Exception as e:
        print('WORKLOAD STATS CACHE ERROR:', e, file=sys.stderr)

def workload_stats_cache_refresher():
    while True:
        update_workload_stats_cache()
        time.sleep(WORKLOAD_STATS_CACHE_TTL)

# Uygulama ilk başladığında cache'i doldur ve arka planda otomatik güncelle
def start_workload_stats_cache():
    t = threading.Thread(target=workload_stats_cache_refresher, daemon=True)
    t.start()

start_workload_stats_cache()

@app.route('/k8s-explorer/workload-stats')
def k8s_explorer_workload_stats():
    global workload_stats_cache, workload_stats_cache_time
    try:
        refresh = request.args.get('refresh')
        now = time.time()
        # Eğer refresh=1 parametresi varsa veya cache yoksa/süresi dolduysa, güncelle
        if refresh == '1' or not workload_stats_cache or (now - workload_stats_cache_time > WORKLOAD_STATS_CACHE_TTL):
            update_workload_stats_cache()
        return jsonify(workload_stats_cache)
    except Exception as e:
        import sys, traceback
        print('WORKLOAD STATS ERROR:', e, file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        return jsonify({'error': str(e)}), 500


@app.route('/k8s-explorer/health')
def k8s_explorer_health():
    """Lightweight health check: try to list a small resource to verify cluster connectivity and return current kubeconfig context."""
    try:
        # Try to read kubeconfig contexts (local file) to get the current context name
        try:
            contexts, current_context = config.list_kube_config_contexts()
            # current_context is a dict like {'name': 'ctx-name', 'context': {...}}
            current_context_name = current_context.get('name') if isinstance(current_context, dict) else (current_context or None)
        except Exception:
            current_context = None
            current_context_name = None
        # Try a lightweight API call to verify connectivity
        try:
            config.load_kube_config()
            c = client.Configuration.get_default_copy()
            c.verify_ssl = False
            c.assert_hostname = False
            client.Configuration.set_default(c)
            core_v1 = client.CoreV1Api()
            # short call: list namespaces with limit to test connectivity
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
        # Return the health result
        return jsonify({'ok': ok, 'context': current_context_name, 'error': error})
    except Exception as e:
        return jsonify({'ok': False, 'context': None, 'error': str(e)}), 500


# --- Pods Summary In-Memory Cache ---
pods_summary_cache = None
pods_summary_cache_time = 0
PODS_SUMMARY_CACHE_TTL = 180  # 3 dakika

def update_pods_summary_cache():
    global pods_summary_cache, pods_summary_cache_time
    try:
        config.load_kube_config()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        core_v1 = client.CoreV1Api()
        pods = core_v1.list_pod_for_all_namespaces().items
        result = []
        for pod in pods:
            # Skip pods that are terminating/deleting so frontend doesn't show them
            if getattr(pod.metadata, 'deletion_timestamp', None):
                continue
            ready_containers = 0
            total_containers = 0
            restart_count = 0
            
            if pod.status.container_statuses:
                total_containers = len(pod.status.container_statuses)
                for container_status in pod.status.container_statuses:
                    if container_status.ready:
                        ready_containers += 1
                    if container_status.restart_count:
                        restart_count += container_status.restart_count
            
            result.append({
                'namespace': pod.metadata.namespace,
                'name': pod.metadata.name,
                'status': pod.status.phase,
                'ready': f"{ready_containers}/{total_containers}",
                'restarts': restart_count,
                'creation_timestamp': pod.metadata.creation_timestamp.isoformat() if pod.metadata.creation_timestamp else None
            })
        pods_summary_cache = {'pods': result}
        pods_summary_cache_time = time.time()
    except Exception as e:
        print('PODS SUMMARY CACHE ERROR:', e, file=sys.stderr)

def pods_summary_cache_refresher():
    while True:
        update_pods_summary_cache()
        time.sleep(PODS_SUMMARY_CACHE_TTL)

def start_pods_summary_cache():
    t = threading.Thread(target=pods_summary_cache_refresher, daemon=True)
    t.start()

start_pods_summary_cache()

@app.route('/k8s-explorer/pods-summary')
def pods_summary():
    global pods_summary_cache, pods_summary_cache_time
    try:
        now = time.time()
        if not pods_summary_cache or (now - pods_summary_cache_time > PODS_SUMMARY_CACHE_TTL):
            update_pods_summary_cache()
        return jsonify(pods_summary_cache)
    except Exception as e:
        return jsonify({'pods': [], 'error': str(e)})

# Deployments summary for Overview tab
@app.route('/k8s-explorer/deployments-summary')
def deployments_summary():
    try:
        config.load_kube_config()
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
        config.load_kube_config()
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
        config.load_kube_config()
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
        config.load_kube_config()
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
        config.load_kube_config()
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
        config.load_kube_config()
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
        config.load_kube_config()
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
        config.load_kube_config()
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

# Workloads page
@app.route('/workloads')
def workloads_page():
    return render_template('workloads.html')

@app.route('/config')
def config_page():
    return render_template('config.html')

@app.route('/k8s-explorer/configmaps-summary')
def configmaps_summary():
    try:
        config.load_kube_config()
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
        config.load_kube_config()
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
        config.load_kube_config()
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
        config.load_kube_config()
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
        config.load_kube_config()
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
        config.load_kube_config()
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
        config.load_kube_config()
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
        config.load_kube_config()
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
        config.load_kube_config()
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
        config.load_kube_config()
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
        config.load_kube_config()
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
        config.load_kube_config()
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
    
# --- Node'lar sayfası ve API ---
@app.route('/nodes')
def nodes_page():
    return render_template('nodes.html')

@app.route('/k8s-explorer/nodes')
def k8s_explorer_nodes():
    try:
        config.load_kube_config()
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
        config.load_kube_config()
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
        config.load_kube_config()
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
            config.load_kube_config()
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
            config.load_kube_config()
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
        config.load_kube_config()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        core_v1 = client.CoreV1Api()
        namespaces = [ns.metadata.name for ns in core_v1.list_namespace().items]
        return jsonify({'namespaces': namespaces})
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

@app.route('/harbor-trivy')
def harbor_trivy_page():
    return render_template('harbor_trivy.html')



@app.route('/harbor-trivy-api', methods=['POST'])
def harbor_trivy_api():
    """
    Harbor Trivy Results
    ---
    post:
      description: Get Trivy scan results for latest images from Harbor (with optional authentication)
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                harbor_url:
                  type: string
                username:
                  type: string
                password:
                  type: string
    """
    try:
        data = request.get_json()
        harbor_url = data.get('harbor_url')
        username = data.get('username')
        password = data.get('password')
        project_name = data.get('project_name')
        if not harbor_url:
            return jsonify({'error': 'Harbor URL gerekli'}), 400
        if not project_name:
            return jsonify({'error': 'Proje adı gerekli'}), 400
        auth = (username, password) if username and password else None
        # CACHE KEY
        cache_key = f"{harbor_url}|{username}|{project_name}"
        now = time.time()
        # 1 dakika cache kontrolü
        if cache_key in harbor_trivy_cache and cache_key in harbor_trivy_cache_time:
            if now - harbor_trivy_cache_time[cache_key] < 60:
                return jsonify(harbor_trivy_cache[cache_key])
        # Ana proje adını ve subpath'i ayır
        if '/' in project_name:
            main_project = project_name.split('/')[0]
            subpath = project_name[len(main_project)+1:]
        else:
            main_project = project_name
            subpath = ''
        # Ana projedeki tüm repo adlarını çek (pagination ile TUMU)
        all_repos = []
        page = 1
        while True:
            repos_resp = requests.get(f'{harbor_url}/api/v2.0/projects/{main_project}/repositories?page={page}&page_size=100', timeout=15, auth=auth)
            repos_resp.raise_for_status()
            repos = repos_resp.json()
            if not repos:
                break
            all_repos.extend(repos)
            if len(repos) < 100:
                break
            page += 1
        repo_names = [repo['name'] for repo in all_repos]
        # Eğer subpath varsa, sadece o path ile başlayan repo'ları filtrele
        if subpath:
            filtered_repo_names = [r for r in repo_names if r.startswith(f"{main_project}/{subpath}")]
        else:
            filtered_repo_names = repo_names
        results = []
        repo_artifacts = {}
        for rname in filtered_repo_names:
            repo_short = rname[len(main_project)+1:] if rname.startswith(f"{main_project}/") else rname
            repo_short_enc = urllib.parse.quote(repo_short, safe='')
            # Sadece ilk artifact (en güncel) çekilecek
            artifacts_resp = requests.get(f'{harbor_url}/api/v2.0/projects/{main_project}/repositories/{repo_short_enc}/artifacts?page_size=1', timeout=10, auth=auth)
            if not artifacts_resp.ok:
                continue
            artifacts = artifacts_resp.json()
            if not artifacts:
                continue
            repo_artifacts[repo_short] = artifacts
            artifact = artifacts[0]
            tags = artifact.get('tags', []) or []
            latest_tag = tags[0]['name'] if tags else None
            latest_digest = artifact.get('digest', '-')
            description = artifact.get('extra_attrs', {}).get('description', '') if 'extra_attrs' in artifact else ''
            cwe_ids = []
            cve_ids = []
            cve_details = []
            if latest_tag:
                tag_name_enc = urllib.parse.quote(latest_tag, safe='')
                vuln_resp = requests.get(f'{harbor_url}/api/v2.0/projects/{main_project}/repositories/{repo_short_enc}/artifacts/{tag_name_enc}/additions/vulnerabilities', timeout=10, auth=auth)
                if vuln_resp.ok:
                    try:
                        vuln_json = vuln_resp.json()
                        print('DEBUG: Trivy vulnerabilities JSON:', json.dumps(vuln_json, ensure_ascii=False), file=sys.stderr)
                        # Handle content-type wrapper key (e.g. "application/vnd.security.vulnerability.report; version=1.1")
                        if isinstance(vuln_json, dict) and len(vuln_json) == 1 and isinstance(list(vuln_json.values())[0], dict):
                            vuln_json = list(vuln_json.values())[0]
                        vulns = []
                        # Harbor/Trivy API bazen vulnerabilities, bazen Vulnerabilities döndürebilir
                        if isinstance(vuln_json, dict):
                            v1 = vuln_json.get('vulnerabilities')
                            v2 = vuln_json.get('Vulnerabilities')
                            # Bazı Trivy sürümlerinde vulnerabilities bir dict olabilir (tek bulgu)
                            if v1 is not None:
                                if isinstance(v1, list):
                                    vulns = v1
                                elif isinstance(v1, dict):
                                    vulns = [v1]
                            elif v2 is not None:
                                if isinstance(v2, list):
                                    vulns = v2
                                elif isinstance(v2, dict):
                                    vulns = [v2]
                        elif isinstance(vuln_json, list):
                            vulns = vuln_json
                        # CWE ve CVE ID'leri topla, detayları da ekle
                        for v in vulns:
                            if isinstance(v, dict):
                                cve_id = v.get('id') or v.get('VulnerabilityID')
                                if cve_id:
                                    cve_ids.append(cve_id)
                                    cve_details.append({
                                        'id': cve_id,
                                        'description': v.get('description', '-')
                                    })
                                # CWE id
                                if v.get('cwe_ids'):
                                    if isinstance(v['cwe_ids'], list):
                                        cwe_ids.extend(v['cwe_ids'])
                                    else:
                                        cwe_ids.append(v['cwe_ids'])
                                if v.get('CweIDs'):
                                    if isinstance(v['CweIDs'], list):
                                        cwe_ids.extend(v['CweIDs'])
                                    else:
                                        cwe_ids.append(v['CweIDs'])
                        print('DEBUG: Extracted CVE IDs:', cve_ids, file=sys.stderr)
                    except Exception as e:
                        print('DEBUG: Exception in vuln parse:', str(e), file=sys.stderr)
                        cwe_ids = []
                        cve_ids = []
                        cve_details = []
            results.append({
                'project': main_project,
                'repo': repo_short,
                'tag': latest_tag,
                'digest': latest_digest,
                'description': description,
                'cwe_ids': list(set(cwe_ids)),
                'cve_ids': list(set(cve_ids)),
                'cve_details': cve_details
            })
        response = {
            'results': results,
            'repo_names': filtered_repo_names
        }
        harbor_trivy_cache[cache_key] = response
        harbor_trivy_cache_time[cache_key] = now
        return jsonify(response)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- Kubernetes Explorer API ---

@app.route('/k8s-explorer/ingresses')
def k8s_explorer_ingresses():
    try:
        config.load_kube_config()
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
        config.load_kube_config()
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
        config.load_kube_config()
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

@app.route('/k8s-explorer/deployment')
def k8s_explorer_deployment_detail():
    namespace = request.args.get('namespace')
    name = request.args.get('name')
    try:
        config.load_kube_config()
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
        config.load_kube_config()
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
        config.load_kube_config()
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

# Service mesh ve pod iletişimi sayfası

@app.route('/mesh')
def mesh():
    return render_template('mesh.html')

# Pod iletişim verisi (basit: hangi pod hangi servise bağlı)
@app.route('/mesh-data')
def mesh_data():
    """
    Service Mesh Data
    ---
    get:
      description: Get mesh data (services, pods, links)
      responses:
        200:
          description: Mesh data
          content:
            application/json:
              schema:
                type: object
    """
    try:
        config.load_kube_config()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        kube_client = type('KubeClient', (), {})()
        kube_client.core_v1 = client.CoreV1Api()
        kube_client.apps_v1 = client.AppsV1Api()
    except Exception as e:
        return jsonify({'error': str(e)})
    mesh = []
    pod_links = []
    pod_to_service_links = []
    namespaces = [ns.metadata.name for ns in kube_client.core_v1.list_namespace().items]
    all_services = {}
    for ns in namespaces:
        services = kube_client.core_v1.list_namespaced_service(ns).items
        for svc in services:
            all_services[f"{ns}:{svc.metadata.name}"] = {
                'ip': svc.spec.cluster_ip,
                'dns': f"{svc.metadata.name}.{ns}.svc.cluster.local"
            }
    for ns in namespaces:
        pods = kube_client.core_v1.list_namespaced_pod(ns).items
        services = kube_client.core_v1.list_namespaced_service(ns).items
        pod_ip_map = {pod.metadata.name: pod.status.pod_ip for pod in pods}
        # Service selector ile eşleşen podları bul
        for svc in services:
            selector = getattr(svc.spec, 'selector', None)
            if not selector:
                continue
            matched_pods = []
            matched_pod_ips = []
            for pod in pods:
                labels = pod.metadata.labels or {}
                if all(labels.get(k) == v for k, v in selector.items()):
                    matched_pods.append(pod.metadata.name)
                    matched_pod_ips.append(pod.status.pod_ip)
            # Podlar arası bağlantı (aynı servise bağlı podlar birbirine konuşabilir)
            for i in range(len(matched_pods)):
                for j in range(i+1, len(matched_pods)):
                    pod_links.append({
                        'namespace': ns,
                        'source': matched_pods[i],
                        'target': matched_pods[j]
                    })
            mesh.append({
                'namespace': ns,
                'service': svc.metadata.name,
                'service_ip': svc.spec.cluster_ip,
                'pods': matched_pods,
                'pod_ips': matched_pod_ips
            })
        # Pod'dan başka servise bağlantı (env var içinde başka servisin ip/dns varsa)
        for pod in pods:
            envs = []
            for c in getattr(pod.spec, 'containers', []):
                envs += getattr(c, 'env', []) or []
            for env in envs:
                val = (getattr(env, 'value', '') or '').lower()
                for svc_key, svc_info in all_services.items():
                    if svc_info['ip'] and svc_info['ip'] in val:
                        pod_to_service_links.append({
                            'namespace': ns,
                            'pod': pod.metadata.name,
                            'target_service': svc_key
                        })
                    elif svc_info['dns'] and svc_info['dns'] in val:
                        pod_to_service_links.append({
                            'namespace': ns,
                            'pod': pod.metadata.name,
                            'target_service': svc_key
                        })
    return jsonify({'mesh': mesh, 'pod_links': pod_links, 'pod_to_service_links': pod_to_service_links})


@app.route('/vulnerabilities')
def vulnerabilities():
    try:
        config.load_kube_config()
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
        config.load_kube_config()
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
