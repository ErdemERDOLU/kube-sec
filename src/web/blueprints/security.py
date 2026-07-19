"""blueprints/security.py — Güvenlik route'ları.

Bu blueprint Kube-Sec güvenlik özelliklerini içerir: ConfigMap/Secret veri sızıntısı,
RBAC risky roles, privileged containers, exec olayları, YAML linter, Trivy Operator,
zafiyet tarama, Pod Security Standards ve NetworkPolicy kapsam analizi.

21 route:
  GET /configmap-secrets, GET /configmap-secrets-data
  GET /rbac-risky-roles
  GET /privileged-containers, GET /privileged-containers-page
  GET /exec-events-page, GET /exec-events
  GET /vulnerabilities
  GET /yaml-linter, POST /yaml-lint-api
  GET /trivy-operator, GET /trivy-operator/status
  POST /trivy-operator/install
  GET /trivy-operator/list-vulnerabilityreports
  POST /trivy-operator/scan
  GET /trivy-operator/get-vulnerabilityreport
  GET /pod-security-standards
  GET /k8s-explorer/pss-summary, GET /k8s-explorer/pss-namespace-detail
  GET /k8s-explorer/netpol-coverage-summary, GET /k8s-explorer/netpol-coverage-ns-detail

Bağımlılık zinciri: kubeconfig_manager <- background <- bu modül <- app.py
"""

import os
import sys
import subprocess
import time
import yaml

from datetime import datetime
from flask import Blueprint, jsonify, render_template, request
from kubernetes import client
from kubernetes.client.rest import ApiException

import web.background as _bg
from web.background import (
    update_pss_cache,
    update_netpol_coverage_cache,
    _evaluate_pod_pss_compliance,
    _pod_matches_pod_selector,
    _netpol_pod_selector_summary,
)
from web.kubeconfig_manager import load_kube_config_active, get_active_kubeconfig_path
from web.audit_log import record_audit_event, _short_session_id
from scanner.k8s_scanner import K8sScanner

bp_security = Blueprint('security', __name__)


# =============================================================================
# YAML Linter — yardımcı sabitler ve fonksiyonlar
# =============================================================================

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


# =============================================================================
# Trivy Operator — yardımcı fonksiyonlar
# =============================================================================

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


# =============================================================================
# Route'lar
# =============================================================================

@bp_security.route('/yaml-linter')
def yaml_linter_page():
    return render_template('yaml_linter.html')


@bp_security.route('/yaml-lint-api', methods=['POST'])
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


@bp_security.route('/configmap-secrets')
def configmap_secrets():
    return render_template('configmap_secrets.html')


@bp_security.route('/configmap-secrets-data')
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


@bp_security.route('/rbac-risky-roles')
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


@bp_security.route('/privileged-containers')
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


@bp_security.route('/privileged-containers-page')
def privileged_containers_page():
    return render_template('privileged_containers.html')


@bp_security.route('/exec-events-page')
def exec_events_page():
    return render_template('exec_events.html')


@bp_security.route('/exec-events')
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


@bp_security.route('/vulnerabilities')
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


# ---- Trivy Operator: Install, Status, Reports ----

@bp_security.route('/trivy-operator')
def trivy_operator_page():
    return render_template('trivy_operator.html')


@bp_security.route('/trivy-operator/status')
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


@bp_security.route('/trivy-operator/install', methods=['POST'])
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
            # helm doesn't support --kubeconfig directly; set env KUBECONFIG
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
            record_audit_event(
                action='install',
                resource_type='TrivyOperator',
                resource_name='trivy-operator',
                namespace='trivy-system',
                session_id=_short_session_id(request.cookies.get('session')),
                details='method=helm',
            )
            return jsonify({'ok': True, 'method': 'helm', 'output': out})
        else:
            # Fallback to static manifest apply from GitHub raw (requires network on client)
            # Prefer kubectl apply -f with local cached path if exists under yaml/
            manifest_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'yaml', 'trivy-operator.yaml')
            if not os.path.exists(manifest_path):
                # Try to apply remote manifest url via kubectl
                url = 'https://raw.githubusercontent.com/aquasecurity/trivy-operator/main/deploy/static/trivy-operator.yaml'
                cmd = _kubectl_base_args() + ["apply", "-f", url]
                code, out, err = _run_cmd(cmd, timeout=300)
                if code != 0:
                    return jsonify({'error': f'kubectl apply failed: {err or out}'}), 500
                record_audit_event(
                    action='install',
                    resource_type='TrivyOperator',
                    resource_name='trivy-operator',
                    namespace='trivy-system',
                    session_id=_short_session_id(request.cookies.get('session')),
                    details='method=kubectl-url',
                )
                return jsonify({'ok': True, 'method': 'kubectl-url', 'output': out})
            else:
                cmd = _kubectl_base_args() + ["apply", "-f", manifest_path]
                code, out, err = _run_cmd(cmd, timeout=300)
                if code != 0:
                    return jsonify({'error': f'kubectl apply failed: {err or out}'}), 500
                record_audit_event(
                    action='install',
                    resource_type='TrivyOperator',
                    resource_name='trivy-operator',
                    namespace='trivy-system',
                    session_id=_short_session_id(request.cookies.get('session')),
                    details='method=kubectl-file',
                )
                return jsonify({'ok': True, 'method': 'kubectl-file', 'output': out})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp_security.route('/trivy-operator/list-vulnerabilityreports')
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


@bp_security.route('/trivy-operator/scan', methods=['POST'])
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

        _scan_detail_parts = [f'target={target}']
        if namespace:
            _scan_detail_parts.append(f'namespace={namespace}')
        if kind:
            _scan_detail_parts.append(f'kind={kind}')
        if name:
            _scan_detail_parts.append(f'name={name}')
        record_audit_event(
            action='scan_trigger',
            resource_type='TrivyOperator',
            resource_name='trivy-operator',
            namespace=namespace or None,
            session_id=_short_session_id(request.cookies.get('session')),
            details=', '.join(_scan_detail_parts),
        )
        return jsonify({'ok': True, 'patched': patched, 'errors': errors})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp_security.route('/trivy-operator/get-vulnerabilityreport')
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


# =============================================================================
# PSS / PSA (Pod Security Standards / Pod Security Admission) Analizi
# _evaluate_pod_pss_compliance -> background.py'den import
# =============================================================================

@bp_security.route('/k8s-explorer/pss-summary')
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


@bp_security.route('/k8s-explorer/pss-namespace-detail')
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


@bp_security.route('/pod-security-standards')
def pod_security_standards():
    """Pod Security Standards analiz sayfasını render eder."""
    return render_template('pod_security_standards.html')


# =============================================================================
# NetworkPolicy Kapsam Analizi
# _pod_matches_pod_selector, _netpol_pod_selector_summary -> background.py'den import
# =============================================================================

@bp_security.route('/k8s-explorer/netpol-coverage-summary')
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


@bp_security.route('/k8s-explorer/netpol-coverage-ns-detail')
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
