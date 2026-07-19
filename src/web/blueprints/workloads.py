"""blueprints/workloads.py — Workload/sayfa route'ları.

Bu blueprint kullanıcı arayüzü sayfa route'larını içerir: workloads, config,
network, storage, nodes, access-control, configuration, mesh, mesh-data.
Çoğu route yalnızca render_template çağırır; mesh-data gerçek k8s verisi döner.

9 route:
  GET /workloads, /config, /network, /storage, /nodes, /access-control,
  GET /configuration, /mesh
  GET /mesh-data  (JSON — küme bağlantısı gerektiren veri endpoint'i)

Bağımlılık zinciri: kubeconfig_manager <- bu modül <- app.py
"""

from flask import Blueprint, jsonify, render_template, request
from kubernetes import client

from web.audit_log import get_recent_events
from web.kubeconfig_manager import load_kube_config_active

bp_workloads = Blueprint('workloads', __name__)


@bp_workloads.route('/workloads')
def workloads_page():
    """Workloads sayfasını render et.
    ---
    GET /workloads
    Returns: HTML (workloads.html şablonu)
    """
    return render_template('workloads.html')


@bp_workloads.route('/config')
def config_page():
    """Config sayfasını render et.
    ---
    GET /config
    Returns: HTML (config.html şablonu)
    """
    return render_template('config.html')


@bp_workloads.route('/network')
def network_page():
    """Network sayfasını render et (Services, Endpoints, Ingress, NetworkPolicies).
    ---
    GET /network
    Returns: HTML (network.html şablonu)
    """
    return render_template('network.html')


@bp_workloads.route('/storage')
def storage_page():
    """Storage sayfasını render et (PVC, PV, StorageClasses).
    ---
    GET /storage
    Returns: HTML (storage.html şablonu)
    """
    return render_template('storage.html')


@bp_workloads.route('/nodes')
def nodes_page():
    """Nodes sayfasını render et.
    ---
    GET /nodes
    Returns: HTML (nodes.html şablonu)
    """
    return render_template('nodes.html')


@bp_workloads.route('/access-control')
def access_control_page():
    """Access Control (RBAC) sayfasını render et.
    ---
    GET /access-control
    Returns: HTML (access_control.html şablonu)
    """
    return render_template('access_control.html')


@bp_workloads.route('/configuration')
def configuration_page():
    """Configuration sayfasını render et.
    ---
    GET /configuration
    Returns: HTML (configuration.html şablonu)
    """
    return render_template('configuration.html')


@bp_workloads.route('/mesh')
def mesh():
    """Service Mesh görselleştirme sayfasını render et.
    ---
    GET /mesh
    Returns: HTML (mesh.html şablonu)
    """
    return render_template('mesh.html')


@bp_workloads.route('/audit-trail')
def audit_trail_page():
    """Aktivite Geçmişi sayfasını render et.
    ---
    GET /audit-trail
    Returns: HTML (audit_trail.html şablonu)
    """
    return render_template('audit_trail.html')


@bp_workloads.route('/api/audit-trail')
def audit_trail_api():
    """Audit trail JSON API endpoint'i.
    ---
    GET /api/audit-trail?limit=100
    Query Params:
      limit (int): Döndürülecek maksimum kayıt sayısı (varsayılan 100)
    Returns: JSON {events: [AuditEvent, ...]}
    """
    try:
        limit = int(request.args.get('limit', 100))
    except (ValueError, TypeError):
        limit = 100
    events = get_recent_events(limit=limit)
    return jsonify({'events': events})


@bp_workloads.route('/mesh-data')
def mesh_data():
    """Service Mesh veri endpoint'i — pod/servis bağlantı grafiği.
    ---
    GET /mesh-data
    Returns: JSON {mesh: [...], pod_links: [...], pod_to_service_links: [...]}
    Hata durumunda: {error: str} (küme bağlantısı yoksa)
    """
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        kube_client = type('KubeClient', (), {})()
        kube_client.core_v1 = client.CoreV1Api()
        kube_client.apps_v1 = client.AppsV1Api()
    except Exception as e:
        return jsonify({'error': str(e)})
    mesh_data_list = []
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
                for j in range(i + 1, len(matched_pods)):
                    pod_links.append({
                        'namespace': ns,
                        'source': matched_pods[i],
                        'target': matched_pods[j]
                    })
            mesh_data_list.append({
                'namespace': ns,
                'service': svc.metadata.name,
                'service_ip': svc.spec.cluster_ip,
                'pods': matched_pods,
                'pod_ips': matched_pod_ips
            })
        # Pod'dan başka servise bağlantı (env var içinde başka servisin ip/dns varsa)
        for pod in pods:
            envs = []
            for container in getattr(pod.spec, 'containers', []):
                envs += getattr(container, 'env', []) or []
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
    return jsonify({'mesh': mesh_data_list, 'pod_links': pod_links, 'pod_to_service_links': pod_to_service_links})
