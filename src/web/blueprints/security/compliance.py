"""blueprints/security/compliance.py — CIS Kubernetes Benchmark Uyumluluk Raporu.

2 route:
  GET /compliance        — Sayfa: compliance.html şablonunu render eder.
  GET /compliance-data   — JSON API: 7 CIS kontrolünü çalıştırır, skorla birlikte döndürür.

Her kontrol ayrı try/except bloğunda çalışır; biri hata verse diğerleri etkilenmez (AC-10).
Kubeconfig erişimi her istek başında configure_kube_client() ile yapılır;
kalıcı/paylaşımlı ApiClient cache'lenmez (AC-9).
"""

import time

from datetime import datetime, timezone

from flask import jsonify, render_template
from kubernetes import client, config

import web.background as _bg
from web.background import (
    PSS_CACHE_TTL,
    NETPOL_COVERAGE_CACHE_TTL,
    update_pss_cache,
    update_netpol_coverage_cache,
)
from web.kubeconfig_manager import configure_kube_client, get_active_kubeconfig_path

from web.blueprints.security import bp_security


# =============================================================================
# CIS kontrol meta-veri tablosu (spec'teki eşleme tablosu, sabit)
# =============================================================================

_CIS_CHECKS_META = [
    {
        'id': 'C1',
        'cis_id': '5.2.1',
        'cis_title': (
            'Ensure that the cluster has at least one active policy control mechanism in place'
        ),
        'category': 'Pod Security Policies / Standards',
    },
    {
        'id': 'C2',
        'cis_id': '5.2.6',
        'cis_title': 'Minimize the admission of root containers',
        'category': 'Pod Security Policies / Standards',
    },
    {
        'id': 'C3',
        'cis_id': '5.2.2',
        'cis_title': (
            'Minimize the admission of privileged containers (via PSA enforce)'
        ),
        'category': 'Pod Security Policies / Standards',
    },
    {
        'id': 'C4',
        'cis_id': '5.3.2',
        'cis_title': 'Ensure that all Namespaces have Network Policies defined',
        'category': 'Network Policies',
    },
    {
        'id': 'C5',
        'cis_id': '5.4.1',
        'cis_title': (
            'Prefer using Secrets rather than environment variables / ConfigMaps for credentials'
        ),
        'category': 'Secrets Management',
    },
    {
        'id': 'C6',
        'cis_id': '5.1.1',
        'cis_title': 'Ensure that the cluster-admin role is only used where required',
        'category': 'RBAC and Service Accounts',
    },
    {
        'id': 'C7',
        'cis_id': '5.2.7',
        'cis_title': 'Minimize the admission of containers without resource limits',
        'category': 'Pod Security Policies / Standards',
    },
]


# =============================================================================
# Yardımcı: Kubernetes istemci başlatma ve context okuma
# =============================================================================

def _init_k8s_clients():
    """Aktif kubeconfig'i yükler, SSL doğrulamasını devre dışı bırakır ve
    CoreV1Api ile RbacAuthorizationV1Api nesneleri döndürür.

    :returns: (core_v1, rbac_v1) tuple
    :raises: Exception — kubeconfig yüklenemezse veya API sunucusuna erişilemezse
    """
    configure_kube_client()
    return client.CoreV1Api(), client.RbacAuthorizationV1Api()


def _get_cluster_context():
    """Aktif kubeconfig'in mevcut context adını döndürür; alınamazsa None döner.

    :returns: str veya None
    """
    try:
        active_path = get_active_kubeconfig_path()
        if active_path:
            try:
                _, current_context = config.list_kube_config_contexts(
                    config_file=active_path
                )
            except TypeError:
                # Eski client sürümlerinde parametre adı farklı olabilir
                _, current_context = config.list_kube_config_contexts(  # type: ignore
                    config_filename=active_path
                )
            if isinstance(current_context, dict):
                return (
                    current_context.get('name')
                    or current_context.get('context', {}).get('cluster')
                )
            if isinstance(current_context, str):
                return current_context
    except Exception:
        pass
    return None


# =============================================================================
# C7 yardımcı: Spec'te birebir tanımlanan resource limits tarama fonksiyonu
# =============================================================================

def _check_resource_limits(core_v1):
    """Tüm pod'lardaki container'ların resources.limits tanımını kontrol eder.

    :param core_v1: kubernetes.client.CoreV1Api nesnesi
    :returns: violations listesi; her öğe {namespace, pod, container} şeklinde
    """
    pods = core_v1.list_pod_for_all_namespaces().items
    violations = []
    for pod in pods:
        for container in pod.spec.containers:
            resources = getattr(container, 'resources', None)
            limits = None
            if resources:
                limits = getattr(resources, 'limits', None)
            if not limits:
                violations.append({
                    'namespace': pod.metadata.namespace,
                    'pod': pod.metadata.name,
                    'container': container.name,
                })
    return violations


# =============================================================================
# Tek tek kontrol fonksiyonları — C1 ile C7
# Her fonksiyon {status, summary_key, details_count, details} döndürür.
# =============================================================================

def _check_c1_privileged_containers(core_v1):
    """C1 — CIS 5.2.1: Privileged container tespiti.

    securityContext.privileged=True olan container'ları listeler.
    Geçme koşulu: privileged listesi boş olmalı.

    :param core_v1: CoreV1Api
    :returns: kontrol sonuç dict'i
    """
    pods = core_v1.list_pod_for_all_namespaces().items
    privileged = []
    for pod in pods:
        for container in pod.spec.containers:
            sec_ctx = getattr(container, 'security_context', None)
            if sec_ctx and getattr(sec_ctx, 'privileged', False):
                privileged.append({
                    'namespace': pod.metadata.namespace,
                    'pod': pod.metadata.name,
                    'container': container.name,
                })
    count = len(privileged)
    status = 'PASS' if count == 0 else 'FAIL'
    return {
        'status': status,
        'summary': 'No privileged containers found' if count == 0 else f'{count} privileged containers found',
        'summary_key': 'check_c1_summary_pass' if status == 'PASS' else 'check_c1_summary_fail',
        'details_count': count,
        'details': privileged,
    }


def _check_c2_root_containers(core_v1):
    """C2 — CIS 5.2.6: Root container tespiti.

    runAsUser==0 veya runAsNonRoot==False olan container'ları listeler.
    Geçme koşulu: root_containers listesi tamamen boş olmalı.

    Kubernetes Python client her zaman snake_case döndürür; camelCase
    fallback gereksiz olduğundan kullanılmaz.

    :param core_v1: CoreV1Api
    :returns: kontrol sonuç dict'i
    """
    pods = core_v1.list_pod_for_all_namespaces().items
    root_list = []
    for pod in pods:
        for container in pod.spec.containers:
            sec_ctx = getattr(container, 'security_context', None)
            run_as_user = None
            run_as_non_root = None
            if sec_ctx:
                # Kubernetes Python client özellik adlarını her zaman snake_case döndürür
                run_as_user = getattr(sec_ctx, 'run_as_user', None)
                run_as_non_root = getattr(sec_ctx, 'run_as_non_root', None)
            if (run_as_user == 0) or (run_as_non_root is False):
                root_list.append({
                    'namespace': pod.metadata.namespace,
                    'pod': pod.metadata.name,
                    'container': container.name,
                })
    count = len(root_list)
    status = 'PASS' if count == 0 else 'FAIL'
    return {
        'status': status,
        'summary': 'No root containers found' if count == 0 else f'{count} root containers found',
        'summary_key': 'check_c2_summary_pass' if status == 'PASS' else 'check_c2_summary_fail',
        'details_count': count,
        'details': root_list,
    }


def _check_c3_pss_compliance():
    """C3 — CIS 5.2.2: PSA/PSS namespace uyumluluğu.

    background.py'deki pss_cache'den okur. Cache boşsa veya TTL aşıldıysa
    update_pss_cache() çağırılır. enforce etiketli namespace'lerde
    noncompliant_pods==0 ise PASS.

    :returns: kontrol sonuç dict'i
    :raises: RuntimeError — cache doldurulamadıysa
    """
    cache = _bg.pss_cache
    cache_time = _bg.pss_cache_time
    if cache is None or (time.time() - cache_time) > PSS_CACHE_TTL:
        update_pss_cache()
        cache = _bg.pss_cache  # update sonrası yeniden oku

    if cache is None:
        raise RuntimeError(
            'PSS cache doldurulamadi — cluster baglantisi veya RBAC izni kontrol edilmeli'
        )

    namespaces = cache.get('namespaces', [])
    # Yalnızca enforce etiketi olan namespace'ler değerlendirilir
    enforce_namespaces = [
        ns for ns in namespaces
        if ns.get('labels') and ns['labels'].get('enforce') is not None
    ]
    noncompliant = [
        {
            'namespace': ns['name'],
            'noncompliant_pods': ns.get('noncompliant_pods') or 0,
        }
        for ns in enforce_namespaces
        if (ns.get('noncompliant_pods') or 0) > 0
    ]
    count = len(noncompliant)
    status = 'PASS' if count == 0 else 'FAIL'
    return {
        'status': status,
        'summary': 'All namespaces PSA enforce compliant' if count == 0 else f'{count} namespace(s) have noncompliant pods',
        'summary_key': 'check_c3_summary_pass' if status == 'PASS' else 'check_c3_summary_fail',
        'details_count': count,
        'details': noncompliant,
    }


def _check_c4_netpol_coverage():
    """C4 — CIS 5.3.2: NetworkPolicy kapsam analizi.

    background.py'deki netpol_coverage_cache'den okur. Cache boşsa veya
    TTL aşıldıysa update_netpol_coverage_cache() çağırılır.
    namespace_coverage_pct==100 ise PASS.

    :returns: kontrol sonuç dict'i
    :raises: RuntimeError — cache doldurulamadıysa
    """
    cache = _bg.netpol_coverage_cache
    cache_time = _bg.netpol_coverage_cache_time
    if cache is None or (time.time() - cache_time) > NETPOL_COVERAGE_CACHE_TTL:
        update_netpol_coverage_cache()
        cache = _bg.netpol_coverage_cache  # update sonrası yeniden oku

    if cache is None:
        raise RuntimeError(
            'NetPol coverage cache doldurulamadi — cluster baglantisi veya RBAC izni kontrol edilmeli'
        )

    cluster_summary = cache.get('cluster_summary', {})
    ns_coverage_pct = cluster_summary.get('namespace_coverage_pct', 0)

    # Hiç NetworkPolicy'si olmayan (status='unprotected') namespace'ler
    uncovered = [
        {
            'namespace': ns['name'],
            'policy_count': ns.get('policy_count', 0),
        }
        for ns in cache.get('namespaces', [])
        if ns.get('status') == 'unprotected'
    ]
    count = len(uncovered)
    status = 'PASS' if ns_coverage_pct == 100 else 'FAIL'
    return {
        'status': status,
        'summary': 'All namespaces have NetworkPolicy' if count == 0 else f'{count} namespace(s) without NetworkPolicy',
        'summary_key': 'check_c4_summary_pass' if status == 'PASS' else 'check_c4_summary_fail',
        'details_count': count,
        'details': uncovered,
    }


def _check_c5_configmap_secrets(core_v1):
    """C5 — CIS 5.4.1: ConfigMap gizli bilgi taraması.

    Tüm namespace'lerdeki ConfigMap data key/value'larında hassas anahtar
    sözcükleri arar. Tek bir list_config_map_for_all_namespaces() çağrısı
    kullanılır; namespace başına ayrı çağrı yapan N+1 kalıbından kaçınılır.
    OWASP gereği: ham değerler loglara/yanıta yazılmaz.

    :param core_v1: CoreV1Api
    :returns: kontrol sonuç dict'i
    """
    keywords = [
        'password', 'passwd', 'secret', 'key', 'token', 'apikey',
        'api_key', 'auth', 'credential', 'private', 'jwt', 'access', 'refresh',
    ]
    suspects = []
    # Tek API çağrısıyla tüm namespace'lerdeki ConfigMap'leri al (N+1 önlemi)
    configmaps = core_v1.list_config_map_for_all_namespaces().items
    for cm in configmaps:
        ns = cm.metadata.namespace
        data = getattr(cm, 'data', {}) or {}
        for k, v in data.items():
            val = (v or '').lower()
            for kw in keywords:
                if kw in k.lower() or kw in val:
                    # Hassas değer loglanmaz / yanıtta yer almaz (OWASP)
                    suspects.append({
                        'namespace': ns,
                        'configmap': cm.metadata.name,
                        'key': k,
                    })
                    break
    count = len(suspects)
    status = 'PASS' if count == 0 else 'FAIL'
    return {
        'status': status,
        'summary': 'No sensitive data found in ConfigMaps' if count == 0 else f'{count} suspicious ConfigMap entries found',
        'summary_key': 'check_c5_summary_pass' if status == 'PASS' else 'check_c5_summary_fail',
        'details_count': count,
        'details': suspects,
    }


def _check_c6_rbac_risky_roles(rbac_v1):
    """C6 — CIS 5.1.1: Riskli RBAC rol tespiti (wildcard izin).

    Wildcard verb ('*') + wildcard resource ('*') kombinasyonuna sahip
    ClusterRole ve Role kaynaklarını listeler.

    Her iki API çağrısının başarı/başarısızlık durumu ayrı ayrı izlenir.
    Herhangi biri başarısız olursa (kısmi görünürlükle yanlış PASS vermemek
    için) RuntimeError fırlatılır; dış try/except bunu ERROR olarak yakalar.

    Kubernetes RBAC'ta geçerli wildcard değeri yalnızca '*'dır; 'all' asla
    dönmez ve bu kontrol hiçbir zaman match etmeyeceğinden kullanılmaz.

    :param rbac_v1: RbacAuthorizationV1Api
    :returns: kontrol sonuç dict'i
    :raises RuntimeError: ClusterRole veya Role listelenemediğinde
    """
    risky = []
    cluster_role_err: str | None = None
    role_err: str | None = None

    # ClusterRole'ları tara
    try:
        cluster_roles = rbac_v1.list_cluster_role().items
        for cr in cluster_roles:
            for rule in cr.rules or []:
                verbs = rule.verbs or []
                resources = rule.resources or []
                if '*' in verbs and '*' in resources:
                    risky.append({
                        'namespace': '',
                        'name': cr.metadata.name,
                        'type': 'ClusterRole',
                    })
                    break  # Her ClusterRole için tek kayıt
    except Exception as exc:
        cluster_role_err = str(exc)

    # Namespace kapsamlı Role'ları tara (list_role_for_all_namespaces — tek API çağrısı)
    try:
        all_roles = rbac_v1.list_role_for_all_namespaces().items
        for r in all_roles:
            for rule in r.rules or []:
                verbs = rule.verbs or []
                resources = rule.resources or []
                if '*' in verbs and '*' in resources:
                    risky.append({
                        'namespace': r.metadata.namespace,
                        'name': r.metadata.name,
                        'type': 'Role',
                    })
                    break  # Her Role için tek kayıt
    except Exception as exc:
        role_err = str(exc)

    # Herhangi bir API çağrısı başarısız olduysa kısmi veriyle PASS vermek
    # yanıltıcı olur — her iki durumda da ERROR olarak işaretle.
    # Dış try/except bu RuntimeError'ı yakalayıp status='ERROR' atar.
    if cluster_role_err and role_err:
        raise RuntimeError(
            f'ClusterRole listelenemedi: {cluster_role_err}; '
            f'Role listelenemedi: {role_err}'
        )
    if cluster_role_err:
        raise RuntimeError(f'ClusterRole listelenemedi: {cluster_role_err}')
    if role_err:
        raise RuntimeError(f'Role listelenemedi: {role_err}')

    count = len(risky)
    status = 'PASS' if count == 0 else 'FAIL'
    return {
        'status': status,
        'summary': 'No wildcard permission roles found' if count == 0 else f'{count} risky roles found',
        'summary_key': 'check_c6_summary_pass' if status == 'PASS' else 'check_c6_summary_fail',
        'details_count': count,
        'details': risky,
    }


def _check_c7_resource_limits(core_v1):
    """C7 — CIS 5.2.7: Resource limits kontrolü (canlı pod taraması).

    _check_resource_limits() yardımcısını kullanır (spec'te birebir
    tanımlanan fonksiyon). Hiç ihlal yoksa PASS.

    :param core_v1: CoreV1Api
    :returns: kontrol sonuç dict'i
    """
    violations = _check_resource_limits(core_v1)
    count = len(violations)
    status = 'PASS' if count == 0 else 'FAIL'
    return {
        'status': status,
        'summary': 'All containers have resource limits defined' if count == 0 else f'{count} containers missing resource limits',
        'summary_key': 'check_c7_summary_pass' if status == 'PASS' else 'check_c7_summary_fail',
        'details_count': count,
        'details': violations,
    }


# =============================================================================
# Route'lar
# =============================================================================

@bp_security.route('/compliance')
def compliance_page():
    """CIS Benchmark Uyumluluk Raporu sayfa route'u.

    :route: GET /compliance
    :returns: compliance.html şablonu, HTTP 200
    """
    return render_template('compliance.html')


@bp_security.route('/compliance-data')
def compliance_data():
    """CIS Benchmark Uyumluluk Kontrol Verileri (JSON API).

    7 CIS Kubernetes Benchmark kontrolünü (C1-C7) sırayla çalıştırır ve
    sonuçları tek bir JSON yanıtında döndürür. Her kontrol ayrı try/except
    bloğunda çalışır — biri hata verse diğerleri etkilenmez (AC-10).

    :route: GET /compliance-data
    :returns: JSON {generated_at, cluster_context, checks, score}

    Response şeması::

        {
          "generated_at": "2026-07-21T14:30:00Z",  // ISO 8601 UTC
          "cluster_context": "my-cluster",           // null olabilir
          "checks": [
            {
              "id": "C1",
              "cis_id": "5.2.1",
              "cis_title": "...",
              "category": "...",
              "status": "PASS" | "FAIL" | "ERROR",
              "summary_key": "check_c1_summary_pass" | null,  // i18n suffix
              "details_count": 0,
              "details": [],
              "error_message": null  // yalnızca ERROR durumunda dolu
            }
          ],
          "score": {
            "total": 7,
            "passed": 4,
            "failed": 2,
            "error": 1,
            "percentage": 67   // (passed / (total - error)) * 100, tam sayı
          }
        }
    """
    generated_at = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    # --- Kubeconfig yükleme (kalıcı ApiClient cache'lenmez — AC-9) ---
    core_v1 = None
    rbac_v1 = None
    kube_error_msg = None
    try:
        core_v1, rbac_v1 = _init_k8s_clients()
    except Exception as kube_err:
        kube_error_msg = str(kube_err)

    # Cluster context adı (alınamazsa None)
    cluster_context = _get_cluster_context()

    # --- Kontrol runner fonksiyonları ---
    # C1, C2, C5, C6, C7: core_v1/rbac_v1 gerektirir
    # C3, C4: background cache'lerini kullanır (bağımsız yenileme yapabilir)

    def _run_c1():
        if core_v1 is None:
            raise RuntimeError(kube_error_msg or 'Kubeconfig yuklenemedi')
        return _check_c1_privileged_containers(core_v1)

    def _run_c2():
        if core_v1 is None:
            raise RuntimeError(kube_error_msg or 'Kubeconfig yuklenemedi')
        return _check_c2_root_containers(core_v1)

    def _run_c3():
        return _check_c3_pss_compliance()

    def _run_c4():
        return _check_c4_netpol_coverage()

    def _run_c5():
        if core_v1 is None:
            raise RuntimeError(kube_error_msg or 'Kubeconfig yuklenemedi')
        return _check_c5_configmap_secrets(core_v1)

    def _run_c6():
        if rbac_v1 is None:
            raise RuntimeError(kube_error_msg or 'Kubeconfig yuklenemedi')
        return _check_c6_rbac_risky_roles(rbac_v1)

    def _run_c7():
        if core_v1 is None:
            raise RuntimeError(kube_error_msg or 'Kubeconfig yuklenemedi')
        return _check_c7_resource_limits(core_v1)

    runners = [_run_c1, _run_c2, _run_c3, _run_c4, _run_c5, _run_c6, _run_c7]

    # --- Kontrolleri sırayla çalıştır; her birini ayrı try/except ile sar (AC-10) ---
    checks = []
    for meta, runner in zip(_CIS_CHECKS_META, runners):
        try:
            result = runner()
            checks.append({
                'id': meta['id'],
                'cis_id': meta['cis_id'],
                'cis_title': meta['cis_title'],
                'category': meta['category'],
                'status': result['status'],
                'summary': result['summary'],          # AC-2: locale-agnostic düz İngilizce özet
                'summary_key': result['summary_key'],  # i18n için korunur
                'details_count': result['details_count'],
                'details': result['details'],
                'error_message': None,
            })
        except Exception as check_err:
            checks.append({
                'id': meta['id'],
                'cis_id': meta['cis_id'],
                'cis_title': meta['cis_title'],
                'category': meta['category'],
                'status': 'ERROR',
                'summary': None,
                'summary_key': None,
                'details_count': 0,
                'details': [],
                'error_message': str(check_err),
            })

    # --- Skor hesaplama (AC-4) ---
    # Formül: (passed / (total - error)) * 100, tam sayıya yuvarla
    # ERROR kontroller hem pay hem paydadan çıkarılır
    total = len(checks)
    error_count = sum(1 for ch in checks if ch['status'] == 'ERROR')
    passed = sum(1 for ch in checks if ch['status'] == 'PASS')
    failed = sum(1 for ch in checks if ch['status'] == 'FAIL')
    effective_total = total - error_count
    percentage = round((passed / effective_total) * 100) if effective_total > 0 else 0

    return jsonify({
        'generated_at': generated_at,
        'cluster_context': cluster_context,
        'checks': checks,
        'score': {
            'total': total,
            'passed': passed,
            'failed': failed,
            'error': error_count,
            'percentage': percentage,
        },
    })
