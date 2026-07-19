"""blueprints/security/analysis.py — YAML linter, ConfigMap/Secret analizi, RBAC, Privileged ve Exec Events route'ları.

9 route:
  GET /yaml-linter, POST /yaml-lint-api
  GET /configmap-secrets, GET /configmap-secrets-data
  GET /rbac-risky-roles
  GET /privileged-containers, GET /privileged-containers-page
  GET /exec-events-page, GET /exec-events
"""

import yaml

from flask import jsonify, render_template, request
from kubernetes import client

from web.kubeconfig_manager import load_kube_config_active

from web.blueprints.security import bp_security


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
