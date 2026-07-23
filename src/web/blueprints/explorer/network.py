"""explorer/network.py — Ağ kaynak route'ları.

İçerik: services, service, service-details, api/k8s/service/.../pods,
endpoints, ingress, ingresses, ingresses-summary, ingress-classes-summary,
network-policies-summary.
"""

from flask import jsonify, request
from kubernetes import client

from web.kubeconfig_manager import configure_kube_client

from web.blueprints.explorer import bp_explorer


# --- Network summaries (namespaced when applicable) ---
@bp_explorer.route('/k8s-explorer/services-summary')
def services_summary():
    try:
        namespace = request.args.get('namespace')
        configure_kube_client()
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


@bp_explorer.route('/k8s-explorer/service')
def k8s_explorer_service_detail():
    namespace = request.args.get('namespace')
    name = request.args.get('name')
    try:
        configure_kube_client()
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


@bp_explorer.route('/k8s-explorer/service-details')
def k8s_explorer_service_details():
    namespace = request.args.get('namespace')
    name = request.args.get('name')
    if not namespace or not name:
        return jsonify({'error': 'namespace ve name zorunlu'}), 400
    try:
        configure_kube_client()
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


# Simple proxy API used by k8s_explorer frontend
@bp_explorer.route('/api/k8s/service/<namespace>/<name>/pods')
def api_service_pods(namespace, name):
    """Return pods belonging to a Service by using its selector."""
    try:
        configure_kube_client()
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


@bp_explorer.route('/k8s-explorer/endpoints-summary')
def endpoints_summary():
    try:
        namespace = request.args.get('namespace')
        configure_kube_client()
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


@bp_explorer.route('/k8s-explorer/ingress')
def k8s_explorer_ingress_detail():
    namespace = request.args.get('namespace')
    name = request.args.get('name')
    try:
        configure_kube_client()
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


@bp_explorer.route('/k8s-explorer/ingresses')
def k8s_explorer_ingresses():
    try:
        configure_kube_client()
        kube_client = type('KubeClient', (), {})()
        kube_client.networking_v1 = client.NetworkingV1Api()
        ingresses = kube_client.networking_v1.list_ingress_for_all_namespaces().items
        result = [{'name': i.metadata.name, 'namespace': i.metadata.namespace} for i in ingresses]
        return jsonify({'ingresses': result})
    except Exception as e:
        return jsonify({'error': str(e)})


@bp_explorer.route('/k8s-explorer/ingresses-summary')
def ingresses_summary():
    try:
        namespace = request.args.get('namespace')
        configure_kube_client()
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


@bp_explorer.route('/k8s-explorer/ingress-classes-summary')
def ingress_classes_summary():
    try:
        configure_kube_client()
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


@bp_explorer.route('/k8s-explorer/network-policies-summary')
def network_policies_summary():
    try:
        namespace = request.args.get('namespace')
        configure_kube_client()
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
