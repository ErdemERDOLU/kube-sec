"""explorer/pods.py — Pod ve Prometheus metrik route'ları.

İçerik: pods-summary, pod-properties, restart-pod, pod-metrics,
pod-metrics-range, prometheus-proxy, prometheus-url.
"""

import json
import os
import time

import requests

from flask import jsonify, request
from kubernetes import client

import web.background as _bg
from web.background import (
    update_pods_summary_cache,
    _METRICS_TS,
    _METRICS_TS_LOCK,
)
from web.kubeconfig_manager import load_kube_config_active
from web.audit_log import record_audit_event, _short_session_id

from web.blueprints.explorer import bp_explorer
from web.blueprints.explorer._pagination import paginate_list


# Prometheus endpoint bilgisi (frontend rehberlik eder; gerçek çağrılar backend proxy üzerinden yapılır)
@bp_explorer.route('/k8s-explorer/prometheus-url')
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
@bp_explorer.route('/k8s-explorer/prometheus-proxy')
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


# --- Pods Summary — cache background.py'de ---

@bp_explorer.route('/k8s-explorer/pods-summary')
def pods_summary():
    """Pod listesini döndürür (background cache'den okunur).

    Query parametreleri:
        namespace (str, opsiyonel): Belirtilirse yalnızca o namespace filtrelenir.
        page      (int, opsiyonel): Sayfa numarası (1-tabanlı). Gönderilmezse
                                    tüm liste eski formatta döner (geriye dönük uyumluluk).
        per_page  (int, opsiyonel): Sayfa başına kayıt (varsayılan: 50, max: 500).

    Yanıt (sayfalama KAPALI — page parametresi yok):
        {"pods": [...], "_cache_meta": {...}}

    Yanıt (sayfalama AÇIK — page parametresi var):
        {"items": [...], "page": N, "per_page": M, "total": T, "total_pages": P, "_cache_meta": {...}}

    Not: _cache_meta her iki modda da yanıta dahil edilir (spec gereksinimi).

    Hatalar:
        400: Geçersiz sayfalama parametresi.
    """
    try:
        now = time.time()
        if not _bg.pods_summary_cache or (now - _bg.pods_summary_cache_time > _bg.PODS_SUMMARY_CACHE_TTL):
            update_pods_summary_cache()

        result = dict(_bg.pods_summary_cache) if _bg.pods_summary_cache else {'pods': []}
        age = int(now - _bg.pods_summary_cache_time) if _bg.pods_summary_cache_time else int(now)

        # _cache_meta her modda eklenecek; önce ayrı bir değişkende tut
        cache_meta = {
            'updated_at': _bg.pods_summary_cache_time,
            'age_seconds': age,
            'stale': age > 300,
            'last_error': _bg._psc_last_error,
        }

        # Tam pod listesini çıkar; opsiyonel namespace filtresi uygula (AC-9)
        pods_list = list(result.get('pods', []))
        namespace = request.args.get('namespace')
        if namespace and namespace != 'all':
            pods_list = [p for p in pods_list if p.get('namespace') == namespace]

        # Sayfalama desteği — AC-1 (sayfalama), AC-2 (geriye dönük uyumluluk), AC-7 (doğrulama)
        try:
            paginated, is_paginated = paginate_list(pods_list, request.args)
        except ValueError as ve:
            return jsonify({'error': str(ve)}), 400

        if is_paginated:
            # _cache_meta zarf içinde de yer alır (spec gereksinimi)
            paginated['_cache_meta'] = cache_meta
            return jsonify(paginated)

        # page parametresi yoksa eski format (geriye dönük uyumluluk — loadOverviewData() etkilenmez)
        result['pods'] = pods_list   # namespace filtresi uygulanmışsa filtrelenmiş liste kullanılır
        result['_cache_meta'] = cache_meta
        return jsonify(result)
    except Exception as e:
        return jsonify({'pods': [], 'error': str(e)})


@bp_explorer.route('/k8s-explorer/pod-properties')
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


@bp_explorer.route('/k8s-explorer/restart-pod', methods=['POST'])
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
        record_audit_event(
            action='restart',
            resource_type='Pod',
            resource_name=name,
            namespace=namespace,
            session_id=_short_session_id(request.cookies.get('session')),
        )
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp_explorer.route('/k8s-explorer/pod-metrics')
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


@bp_explorer.route('/k8s-explorer/pod-metrics-range')
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
            r = requests.get(f"{base_url.rstrip('/')}/api/v1/query_range", params=params, timeout=timeout_s, verify=False)
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
