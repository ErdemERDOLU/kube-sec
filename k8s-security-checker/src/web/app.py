from flask import Flask, render_template, jsonify, request

app = Flask(__name__)

# Global error handler: Her zaman JSON döndür
@app.errorhandler(Exception)
def handle_exception(e):
    return jsonify({'error': str(e)}), 500
from flask_cors import CORS
from scanner.k8s_scanner import K8sScanner
from kubernetes import client, config

CORS_ORIGINS = ["http://localhost:8080", "http://127.0.0.1:8080"]
app = Flask(__name__)
CORS(app, origins=CORS_ORIGINS)

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
        return jsonify({'error': str(e)})
    scanner = K8sScanner(kube_client)
    all_vulnerabilities = {}
    pod_images = {}
    namespaces = [ns.metadata.name for ns in kube_client.core_v1.list_namespace().items]
    for ns in namespaces:
        deployments = kube_client.apps_v1.list_namespaced_deployment(ns).items
        for dep in deployments:
            vulns = scanner.list_vulnerabilities(dep)
            dep_key = f"{ns}/{dep.metadata.name}"
            if vulns:
                all_vulnerabilities[dep_key] = vulns
            # Pod image bilgisini ekle
            if dep.spec.template.spec.containers:
                pod_images[dep_key] = ', '.join([c.image for c in dep.spec.template.spec.containers])
    return jsonify({'vulnerabilities': all_vulnerabilities, 'pod_images': pod_images})
