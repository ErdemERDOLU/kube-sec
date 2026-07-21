"""blueprints/security/_vuln_checks.py — Canli cluster pod template guvenlik tarama fonksiyonu.

Bu modul, K8sScanner sinifinin yerini alan tek public fonksiyonu icerir.
K8sScanner'in aksine:
  - Dogrudan PodTemplateSpec alir (workload tipi route seviyesinde ayrismis olur).
  - Hardcoded mesaj string'i icermez; yalnizca i18n anahtar + parametre dondurir.
  - NetworkPolicy kontrolu calisan tarafa birakılir (spec risk #4).

Public API:
    scan_pod_template(pod_template_spec, namespace, workload_kind, workload_name,
                      networking_v1=None) -> list[dict]
"""

# Tehlikeli capability'lerin listesi (Kubernetes CRI / POSIX kaynakli)
_DANGEROUS_CAPABILITIES = frozenset({
    'NET_ADMIN',
    'SYS_ADMIN',
    'SYS_PTRACE',
    'SYS_MODULE',
    'SYS_RAWIO',
    'SYS_TIME',
    'NET_RAW',
    'SETUID',
    'SETGID',
    'DAC_OVERRIDE',
    'DAC_READ_SEARCH',
})

# Ortam degisken adlarinda hassas bilgi iceren anahtar kelimeler (kucuk harf)
_SENSITIVE_KEYWORDS = frozenset({'password', 'secret', 'key', 'token'})


def scan_pod_template(
    pod_template_spec,
    namespace: str,
    workload_kind: str,
    workload_name: str,
    networking_v1=None,
) -> list:
    """Pod template spec'ini guvenlik acisindan tarar ve finding listesi dondurir.

    Args:
        pod_template_spec: kubernetes.client.V1PodTemplateSpec —
            workload.spec.template olarak iletilir.
        namespace: Workload'un ait oldugu namespace adi.
        workload_kind: "Deployment", "StatefulSet" veya "DaemonSet" gibi kaynak tipi.
        workload_name: Workload'un metadata.name degeri.
        networking_v1: kubernetes.client.NetworkingV1Api ornegi.
            None iletildiginde NetworkPolicy kontrolu bu fonksiyon tarafindan
            YAPILMAZ; cagiran tarafin namespace bazinda ayri yonetmesi gerekir.

    Returns:
        Her oge bir finding olan list[dict]. Finding formati:
        {
            "check_id":    str,          # ornek: "no-pod-security-context"
            "severity":    str,          # "critical" | "high" | "medium" | "low" | "info"
            "i18n_key":    str,          # I18N dict anahtari
            "i18n_params": dict,         # mesaj sablonundaki degiskenler
            "container":   str | None,   # ilgili container adi; pod-level kontrollerde None
        }
    """
    findings = []

    # V1PodTemplateSpec -> V1PodSpec
    spec = pod_template_spec.spec

    # ------------------------------------------------------------------
    # Pod-level kontroller
    # ------------------------------------------------------------------

    # Check 1: Pod security context
    if not spec.security_context:
        findings.append({
            'check_id': 'no-pod-security-context',
            'severity': 'high',
            'i18n_key': 'vuln.check.no_pod_security_context',
            'i18n_params': {},
            'container': None,
        })

    # Check 6: hostPath volume (pod-level; bir kez eklenir — container dongusunda degil)
    for vol in getattr(spec, 'volumes', []) or []:
        if getattr(vol, 'host_path', None):
            findings.append({
                'check_id': 'hostpath-volume',
                'severity': 'high',
                'i18n_key': 'vuln.check.hostpath_volume',
                'i18n_params': {'volume_name': vol.name},
                'container': None,
            })

    # Check 12: Varsayilan service account (pod-level)
    sa = getattr(spec, 'service_account_name', None)
    if not sa or sa == 'default':
        findings.append({
            'check_id': 'default-service-account',
            'severity': 'medium',
            'i18n_key': 'vuln.check.default_service_account',
            'i18n_params': {},
            'container': None,
        })

    # ------------------------------------------------------------------
    # Container-level kontroller
    # ------------------------------------------------------------------

    for container in getattr(spec, 'containers', []) or []:
        cname = container.name
        sc = container.security_context

        # Check 2: Container security context eksikligi
        if sc is None:
            findings.append({
                'check_id': 'no-container-security-context',
                'severity': 'high',
                'i18n_key': 'vuln.check.no_container_security_context',
                'i18n_params': {'container': cname},
                'container': cname,
            })

        # Check 3: :latest imaj etiketi
        image = container.image or ''
        if ':latest' in image:
            findings.append({
                'check_id': 'image-latest-tag',
                'severity': 'medium',
                'i18n_key': 'vuln.check.image_latest_tag',
                'i18n_params': {'container': cname, 'image': image},
                'container': cname,
            })

        # Check 4: Resource limits / requests eksikligi
        resources = getattr(container, 'resources', None)
        limits_missing = not resources or not getattr(resources, 'limits', None)
        requests_missing = not resources or not getattr(resources, 'requests', None)
        if limits_missing or requests_missing:
            findings.append({
                'check_id': 'no-resource-limits',
                'severity': 'medium',
                'i18n_key': 'vuln.check.no_resource_limits',
                'i18n_params': {'container': cname},
                'container': cname,
            })

        # Check 5: Hassas ortam degiskenleri
        for env in getattr(container, 'env', []) or []:
            env_name = env.name or ''
            if any(kw in env_name.lower() for kw in _SENSITIVE_KEYWORDS):
                findings.append({
                    'check_id': 'sensitive-env-var',
                    'severity': 'critical',
                    'i18n_key': 'vuln.check.sensitive_env_var',
                    'i18n_params': {'container': cname, 'env_name': env_name},
                    'container': cname,
                })

        # Security context'e bagli kontroller (yalnizca sc varsa)
        if sc is not None:
            # Check 7: readOnlyRootFilesystem aktif degil
            if not getattr(sc, 'read_only_root_filesystem', False):
                findings.append({
                    'check_id': 'no-readonly-rootfs',
                    'severity': 'medium',
                    'i18n_key': 'vuln.check.no_readonly_rootfs',
                    'i18n_params': {'container': cname},
                    'container': cname,
                })

            # Check 8: Tehlikeli capability eklenmesi
            caps = getattr(sc, 'capabilities', None)
            if caps:
                for cap in getattr(caps, 'add', []) or []:
                    if cap in _DANGEROUS_CAPABILITIES:
                        findings.append({
                            'check_id': 'dangerous-capability',
                            'severity': 'critical',
                            'i18n_key': 'vuln.check.dangerous_capability',
                            'i18n_params': {'container': cname, 'capability': cap},
                            'container': cname,
                        })

            # Check 9: Privilege escalation izni
            if getattr(sc, 'allow_privilege_escalation', True):
                findings.append({
                    'check_id': 'allow-privilege-escalation',
                    'severity': 'high',
                    'i18n_key': 'vuln.check.allow_privilege_escalation',
                    'i18n_params': {'container': cname},
                    'container': cname,
                })

        # Check 10: Liveness probe eksikligi
        if not getattr(container, 'liveness_probe', None):
            findings.append({
                'check_id': 'no-liveness-probe',
                'severity': 'low',
                'i18n_key': 'vuln.check.no_liveness_probe',
                'i18n_params': {'container': cname},
                'container': cname,
            })

        # Check 11: Readiness probe eksikligi
        if not getattr(container, 'readiness_probe', None):
            findings.append({
                'check_id': 'no-readiness-probe',
                'severity': 'low',
                'i18n_key': 'vuln.check.no_readiness_probe',
                'i18n_params': {'container': cname},
                'container': cname,
            })

    # ------------------------------------------------------------------
    # Check 13: NetworkPolicy (namespace-level)
    # networking_v1=None ise bu kontrolu atlayip cagiran tarafa birak
    # (spec risk #4: namespace basina bir kez API cagrisi yapilmali).
    # ------------------------------------------------------------------
    if networking_v1 is not None:
        try:
            net_policies = networking_v1.list_namespaced_network_policy(namespace)
            if not net_policies.items:
                findings.append({
                    'check_id': 'no-network-policy',
                    'severity': 'medium',
                    'i18n_key': 'vuln.check.no_network_policy',
                    'i18n_params': {'namespace': namespace},
                    'container': None,
                })
        except Exception:
            # API hatasi durumunda bulgu eklenmiyor; eksik NetworkPolicy false-positive olusturmasin
            pass

    return findings
