"""background.py — Arka plan cache thread'leri ve yardımcı fonksiyonlar.

Bu modül Flask'a bağımlı değildir; sadece kubernetes client, threading ve
kubeconfig_manager'a bağımlıdır.

Import zinciri:  kubeconfig_manager  <-  background.py  <-  blueprint'ler  <-  app.py

UYARI: start_*() fonksiyonları bu modül yüklendiğinde OTOMATİK çağrılmaz.
       Çağrı app.py'nin sonunda yapılır (tüm import'lar bittikten sonra).
"""

import os
import sys
import threading
import time
from collections import deque

from kubernetes import client

from web.kubeconfig_manager import configure_kube_client


# =============================================================================
# Backoff sabitleri — KUBESEC_* env değişkenleriyle override edilebilir (AC-7)
# =============================================================================

def _parse_backoff_env(name: str, default: int, min_val: int = 1) -> int:
    """Ortam değişkenini int'e çevirir; geçersiz değerde varsayılan döner, stderr'e uyarı yazar."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        val = int(raw)
        if val < min_val:
            raise ValueError(f"değer {val} < minimum {min_val}")
        return val
    except (ValueError, TypeError) as exc:
        print(
            f'BACKOFF UYARI: {name}={raw!r} geçersiz ({exc}); varsayılan {default} kullanılıyor.',
            file=sys.stderr
        )
        return default


BACKOFF_INITIAL: int = _parse_backoff_env('KUBESEC_BACKOFF_INITIAL', 5)
BACKOFF_MAX: int = _parse_backoff_env('KUBESEC_BACKOFF_MAX', 300)
MAX_CONSECUTIVE_ERRORS: int = _parse_backoff_env('KUBESEC_MAX_CONSECUTIVE_ERRORS', 10)


def compute_backoff_sleep(consecutive_errors: int, base_ttl: float) -> float:
    """Ardışık hata sayısına göre bekleme süresini hesaplar (AC-1).

    - consecutive_errors <= 0: ``base_ttl`` döner (normal durum).
    - consecutive_errors > 0: ``min(BACKOFF_INITIAL * 2^(n-1), BACKOFF_MAX)`` döner.

    :param consecutive_errors: Ardışık hata sayısı (0'dan küçükse normal TTL döner).
    :param base_ttl: Başarılı durumda bekleme süresi (saniye).
    :returns: Uygulanacak bekleme süresi (saniye).
    """
    if consecutive_errors <= 0:
        return float(base_ttl)
    delay = BACKOFF_INITIAL * (2 ** (consecutive_errors - 1))
    return float(min(delay, BACKOFF_MAX))


def _should_log(consecutive_errors: int) -> bool:
    """Throttled logging: 1., 2., 5., 10. ve sonrasında her 10.'da True döner (AC-8)."""
    if consecutive_errors in (1, 2, 5):
        return True
    if consecutive_errors >= 10 and consecutive_errors % 10 == 0:
        return True
    return False


# =============================================================================
# Workload Stats In-Memory Cache
# =============================================================================

workload_stats_cache = None
workload_stats_cache_time = 0
WORKLOAD_STATS_CACHE_TTL = 20  # 20 saniye
_wsc_last_error = None           # str | None -- son workload-stats yenileme hatası (başarılı ise None)
_wsc_consecutive_errors: int = 0  # ardışık hata sayacı (AC-3)


def update_workload_stats_cache():
    global workload_stats_cache, workload_stats_cache_time, _wsc_last_error
    try:
        configure_kube_client()
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
        _wsc_last_error = None  # başarılı güncelleme -- hata durumunu sıfırla
    except Exception as e:
        _wsc_last_error = str(e)  # başarısız güncelleme -- hatayı kaydet (cache değişmez); refresher loglar


def workload_stats_cache_refresher():
    """Workload stats cache'ini TTL aralıklarla yenileyen daemon döngüsü (AC-2)."""
    global _wsc_consecutive_errors
    while True:
        prev_error = _wsc_last_error
        update_workload_stats_cache()
        if _wsc_last_error is None:
            # Başarılı güncelleme
            if prev_error is not None and _wsc_consecutive_errors > 0:
                print(
                    f'WORKLOAD STATS CACHE: kurtarıldı ({_wsc_consecutive_errors} ardışık hata sonrası).',
                    file=sys.stderr
                )
            _wsc_consecutive_errors = 0
            time.sleep(WORKLOAD_STATS_CACHE_TTL)
        else:
            # Başarısız güncelleme
            _wsc_consecutive_errors += 1
            if _should_log(_wsc_consecutive_errors):
                print(
                    f'WORKLOAD STATS CACHE: ardışık hata #{_wsc_consecutive_errors}: {_wsc_last_error}',
                    file=sys.stderr
                )
            time.sleep(compute_backoff_sleep(_wsc_consecutive_errors, WORKLOAD_STATS_CACHE_TTL))


def start_workload_stats_cache():
    """Workload stats cache arka plan thread'ini başlatır."""
    t = threading.Thread(target=workload_stats_cache_refresher, daemon=True)
    t.start()


# =============================================================================
# Pods Summary In-Memory Cache
# =============================================================================

pods_summary_cache = None
pods_summary_cache_time = 0
PODS_SUMMARY_CACHE_TTL = 180  # 3 dakika
_psc_last_error = None           # str | None -- son pods-summary yenileme hatası (başarılı ise None)
_psc_consecutive_errors: int = 0  # ardışık hata sayacı (AC-3)


def update_pods_summary_cache():
    global pods_summary_cache, pods_summary_cache_time, _psc_last_error
    try:
        configure_kube_client()
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
        _psc_last_error = None  # başarılı güncelleme -- hata durumunu sıfırla
    except Exception as e:
        _psc_last_error = str(e)  # başarısız güncelleme -- hatayı kaydet (cache değişmez); refresher loglar


def pods_summary_cache_refresher():
    """Pods summary cache'ini TTL aralıklarla yenileyen daemon döngüsü (AC-2)."""
    global _psc_consecutive_errors
    while True:
        prev_error = _psc_last_error
        update_pods_summary_cache()
        if _psc_last_error is None:
            if prev_error is not None and _psc_consecutive_errors > 0:
                print(
                    f'PODS SUMMARY CACHE: kurtarıldı ({_psc_consecutive_errors} ardışık hata sonrası).',
                    file=sys.stderr
                )
            _psc_consecutive_errors = 0
            time.sleep(PODS_SUMMARY_CACHE_TTL)
        else:
            _psc_consecutive_errors += 1
            if _should_log(_psc_consecutive_errors):
                print(
                    f'PODS SUMMARY CACHE: ardışık hata #{_psc_consecutive_errors}: {_psc_last_error}',
                    file=sys.stderr
                )
            time.sleep(compute_backoff_sleep(_psc_consecutive_errors, PODS_SUMMARY_CACHE_TTL))


def start_pods_summary_cache():
    """Pods summary cache arka plan thread'ini başlatır."""
    t = threading.Thread(target=pods_summary_cache_refresher, daemon=True)
    t.start()


# =============================================================================
# Metrics-server Zaman Serisi Fallback Tamponu
# =============================================================================

# Yapı: {(namespace, pod_name): deque([(ts_sec, cpu_mcores, mem_bytes)], maxlen=N)}
_METRICS_TS = {}
_METRICS_TS_LOCK = threading.Lock()
_METRICS_TS_MAXLEN = 600  # ~600 örnek (ör: 10s interval ile ~100 dakika)
_METRICS_TS_INTERVAL = float(os.environ.get('METRICS_TS_INTERVAL_SEC', '10'))

# Metrics sampler durum izleme (AC-3)
_msl_last_error = None           # str | None -- son metrics-sampler hatası (başarılı ise None)
_msl_last_success_time: float = 0.0  # son başarılı örnekleme zamanı (epoch saniye)
_msl_consecutive_errors: int = 0  # ardışık hata sayacı


def _parse_cpu_to_mcores(cpu_str: str) -> float:
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


def _parse_mem_to_bytes(mem_str: str) -> float:
    s = str(mem_str or '').strip()
    if not s:
        return 0.0
    try:
        units = {
            'Ki': 1024, 'Mi': 1024**2, 'Gi': 1024**3, 'Ti': 1024**4, 'Pi': 1024**5, 'Ei': 1024**6,
            'K': 1000, 'M': 1000**2, 'G': 1000**3, 'T': 1000**4, 'P': 1000**5, 'E': 1000**6
        }
        for u, mul in units.items():
            if s.endswith(u):
                return float(s[:-len(u)]) * mul
        return float(s)
    except Exception:
        return 0.0


def _metrics_sampler_loop():
    """Arka planda metrics.k8s.io'dan tüm podlar için CPU/Memory kullanımlarını örnekler (AC-2)."""
    global _msl_last_error, _msl_last_success_time, _msl_consecutive_errors
    base_interval = max(5.0, _METRICS_TS_INTERVAL)
    while True:
        sleep_time = base_interval
        try:
            configure_kube_client()
            co = client.CustomObjectsApi()
            core_v1 = client.CoreV1Api()
            # Tüm namespace'leri dolaş ve pod metriklerini al
            ns_list = [ns.metadata.name for ns in core_v1.list_namespace().items]
            now = time.time()
            for ns in ns_list:
                try:
                    pods_metrics = co.list_namespaced_custom_object('metrics.k8s.io', 'v1beta1', ns, 'pods')
                except Exception:
                    continue
                items = pods_metrics.get('items', []) if isinstance(pods_metrics, dict) else []
                with _METRICS_TS_LOCK:
                    for it in items:
                        m = it or {}
                        md = m.get('metadata', {}) or {}
                        pod_name = md.get('name')
                        if not pod_name:
                            continue
                        key = (ns, pod_name)
                        containers = m.get('containers', []) or []
                        total_cpu_m = 0.0
                        total_mem_b = 0.0
                        for ct in containers:
                            usage = ct.get('usage', {}) or {}
                            total_cpu_m += _parse_cpu_to_mcores(usage.get('cpu'))
                            total_mem_b += _parse_mem_to_bytes(usage.get('memory'))
                        dq = _METRICS_TS.get(key)
                        if dq is None:
                            dq = deque(maxlen=_METRICS_TS_MAXLEN)
                            _METRICS_TS[key] = dq
                        dq.append((now, int(round(total_cpu_m)), int(round(total_mem_b))))
            # Başarılı örnekleme
            if _msl_last_error is not None and _msl_consecutive_errors > 0:
                print(
                    f'METRICS SAMPLER: kurtarıldı ({_msl_consecutive_errors} ardışık hata sonrası).',
                    file=sys.stderr
                )
            _msl_last_success_time = time.time()
            _msl_last_error = None
            _msl_consecutive_errors = 0
            sleep_time = base_interval
        except Exception as e:
            _msl_consecutive_errors += 1
            _msl_last_error = str(e)
            if _should_log(_msl_consecutive_errors):
                try:
                    print(
                        f'METRICS SAMPLER: ardışık hata #{_msl_consecutive_errors}: {e}',
                        file=sys.stderr
                    )
                except Exception:
                    pass
            sleep_time = compute_backoff_sleep(_msl_consecutive_errors, base_interval)
        # bir sonraki örnekleme
        time.sleep(sleep_time)


def start_metrics_sampler():
    """Metrics sampler arka plan thread'ini başlatır."""
    t = threading.Thread(target=_metrics_sampler_loop, daemon=True)
    t.start()


# =============================================================================
# PSS / PSA Kural Değerlendirme Yardımcı Fonksiyonu
# =============================================================================

def _evaluate_pod_pss_compliance(pod, profile):
    """Bir pod'u verilen PSS profiline karşı R1-R9 kurallarına göre değerlendirir.

    :param pod: kubernetes.client.models.V1Pod nesnesi
    :param profile: 'privileged' | 'baseline' | 'restricted'
    :returns: (compliant: bool, violations: list[str])
              violations içeriği insan-okunabilir ihlal açıklamalarıdır.

    Kural profil tablosu:
      Baseline (R1-R5): R1 privileged, R2 hostNetwork, R3 hostPID,
                        R4 hostIPC, R5 hostPorts
      Restricted (R1-R9): Baseline kurallarına ek olarak
                        R6 allowPrivilegeEscalation, R7 runAsNonRoot,
                        R8 capabilities.drop ALL, R9 capabilities.add kısıtlama
    Hem spec.containers hem de spec.initContainers kontrol edilir.
    """
    if profile == 'privileged':
        # Privileged profilinde kısıtlama yok; tüm pod'lar uyumlu
        return (True, [])

    violations = []
    spec = pod.spec

    # Tüm container'ları birleştir: normal + init
    all_containers = list(getattr(spec, 'containers', None) or [])
    init_containers = list(getattr(spec, 'init_containers', None) or [])
    all_containers_combined = all_containers + init_containers

    # --- Baseline + Restricted kuralları (R1-R5) ---

    # R1: Privileged container — her container/initContainer için
    for c in all_containers_combined:
        sc = getattr(c, 'security_context', None)
        if sc and getattr(sc, 'privileged', False):
            violations.append(f"privileged=true (container: {c.name})")

    # R2: Host network — pod spec seviyesinde
    if getattr(spec, 'host_network', False):
        violations.append("hostNetwork=true")

    # R3: Host PID — pod spec seviyesinde
    if getattr(spec, 'host_pid', False):
        violations.append("hostPID=true")

    # R4: Host IPC — pod spec seviyesinde
    if getattr(spec, 'host_ipc', False):
        violations.append("hostIPC=true")

    # R5: Host ports — her container/initContainer için
    for c in all_containers_combined:
        ports = getattr(c, 'ports', None) or []
        for port in ports:
            host_port = getattr(port, 'host_port', None)
            if host_port:
                violations.append(f"hostPort={host_port} (container: {c.name})")

    # --- Restricted-only kuralları (R6-R9) ---
    if profile == 'restricted':

        # R6: allowPrivilegeEscalation — her container'da explicit olarak False olmalı
        for c in all_containers_combined:
            sc = getattr(c, 'security_context', None)
            ape = getattr(sc, 'allow_privilege_escalation', None) if sc else None
            if ape is not False:
                violations.append(f"allowPrivilegeEscalation=true (container: {c.name})")

        # R7: runAsNonRoot — pod veya container seviyesinde en az birinde True olmalı
        pod_sc = getattr(spec, 'security_context', None)
        pod_run_as_non_root = getattr(pod_sc, 'run_as_non_root', None) if pod_sc else None
        for c in all_containers_combined:
            c_sc = getattr(c, 'security_context', None)
            c_run_as_non_root = getattr(c_sc, 'run_as_non_root', None) if c_sc else None
            if pod_run_as_non_root is not True and c_run_as_non_root is not True:
                violations.append(f"runAsNonRoot not set to true (container: {c.name})")

        # R8: capabilities.drop "ALL" içermeli — her container için
        for c in all_containers_combined:
            sc = getattr(c, 'security_context', None)
            caps = getattr(sc, 'capabilities', None) if sc else None
            drop = getattr(caps, 'drop', None) if caps else None
            drop_upper = [d.upper() for d in (drop or [])]
            if 'ALL' not in drop_upper:
                violations.append(f"capabilities.drop does not include ALL (container: {c.name})")

        # R9: capabilities.add yalnızca boş veya ["NET_BIND_SERVICE"] olabilir — her container için
        _allowed_add = {'NET_BIND_SERVICE'}
        for c in all_containers_combined:
            sc = getattr(c, 'security_context', None)
            caps = getattr(sc, 'capabilities', None) if sc else None
            add = getattr(caps, 'add', None) if caps else None
            add_upper = {a.upper() for a in (add or [])}
            disallowed = add_upper - _allowed_add
            if disallowed:
                violations.append(
                    f"capabilities.add contains disallowed caps: {sorted(disallowed)} (container: {c.name})"
                )

    return (len(violations) == 0, violations)


# =============================================================================
# PSS In-Memory Cache
# =============================================================================

pss_cache = None
pss_cache_time = 0
PSS_CACHE_TTL = 30  # 30 saniye; büyük cluster'larda artırılabilir
_pss_last_error = None           # str | None -- son PSS yenileme hatası (başarılı ise None) (AC-3)
_pss_consecutive_errors: int = 0  # ardışık hata sayacı (AC-3)


def update_pss_cache():
    """Tüm namespace'ler için PSA etiketlerini ve pod uyumluluk sayılarını hesaplar,
    sonucu modül seviyesi pss_cache dict'ine yazar.

    kubeconfigs_activate() tarafından kubeconfig değişiminde de çağrılır.
    """
    global pss_cache, pss_cache_time, _pss_last_error
    try:
        configure_kube_client()
        core_v1 = client.CoreV1Api()

        namespaces = core_v1.list_namespace().items
        result = []

        for ns in namespaces:
            ns_name = ns.metadata.name
            labels = ns.metadata.labels or {}
            _prefix = 'pod-security.kubernetes.io/'

            enforce = labels.get(f'{_prefix}enforce')
            enforce_version = labels.get(f'{_prefix}enforce-version')
            warn = labels.get(f'{_prefix}warn')
            warn_version = labels.get(f'{_prefix}warn-version')
            audit = labels.get(f'{_prefix}audit')
            audit_version = labels.get(f'{_prefix}audit-version')

            has_psa = any(v is not None for v in [enforce, warn, audit])
            ns_labels = None
            if has_psa:
                ns_labels = {
                    'enforce': enforce,
                    'enforce_version': enforce_version,
                    'warn': warn,
                    'warn_version': warn_version,
                    'audit': audit,
                    'audit_version': audit_version,
                }

            # Pod'ları listele — hata olursa boş liste kullan
            try:
                pods = core_v1.list_namespaced_pod(ns_name).items
            except Exception as _pod_err:
                print(f'PSS CACHE: pod list error for ns {ns_name}: {_pod_err}', file=sys.stderr)
                pods = []

            total_pods = len(pods)
            compliant_pods = None
            noncompliant_pods = None

            # Uyumluluk hesabı yalnızca enforce etiketi varsa yapılır
            if enforce is not None:
                compliant_count = 0
                noncompliant_count = 0
                for pod in pods:
                    try:
                        compliant, _ = _evaluate_pod_pss_compliance(pod, enforce)
                        if compliant:
                            compliant_count += 1
                        else:
                            noncompliant_count += 1
                    except Exception as _eval_err:
                        print(
                            f'PSS CACHE: eval error pod {pod.metadata.name} ns {ns_name}: {_eval_err}',
                            file=sys.stderr
                        )
                        noncompliant_count += 1
                compliant_pods = compliant_count
                noncompliant_pods = noncompliant_count

            result.append({
                'name': ns_name,
                'labels': ns_labels,
                'total_pods': total_pods,
                'compliant_pods': compliant_pods,
                'noncompliant_pods': noncompliant_pods,
            })

        pss_cache = {'namespaces': result}
        pss_cache_time = time.time()
        _pss_last_error = None  # başarılı güncelleme -- hata durumunu sıfırla
    except Exception as e:
        _pss_last_error = str(e)  # başarısız güncelleme -- hatayı kaydet; refresher loglar


def pss_cache_refresher():
    """PSS cache'ini TTL aralıklarla yenileyen daemon döngüsü (AC-2)."""
    global _pss_consecutive_errors
    while True:
        prev_error = _pss_last_error
        update_pss_cache()
        if _pss_last_error is None:
            if prev_error is not None and _pss_consecutive_errors > 0:
                print(
                    f'PSS CACHE: kurtarıldı ({_pss_consecutive_errors} ardışık hata sonrası).',
                    file=sys.stderr
                )
            _pss_consecutive_errors = 0
            time.sleep(PSS_CACHE_TTL)
        else:
            _pss_consecutive_errors += 1
            if _should_log(_pss_consecutive_errors):
                print(
                    f'PSS CACHE: ardışık hata #{_pss_consecutive_errors}: {_pss_last_error}',
                    file=sys.stderr
                )
            time.sleep(compute_backoff_sleep(_pss_consecutive_errors, PSS_CACHE_TTL))


def start_pss_cache():
    """PSS cache arka plan thread'ini başlatır."""
    t = threading.Thread(target=pss_cache_refresher, daemon=True)
    t.start()


# =============================================================================
# NetworkPolicy Kapsam Analizi — Yardımcı Fonksiyonlar
# =============================================================================

def _pod_matches_pod_selector(pod_labels: dict, pod_selector) -> bool:
    """Bir pod'un `pod_selector` nesnesine (V1LabelSelector) uyup uymadığını döner.

    Eşleştirme mantığı:
    - podSelector boşsa (matchLabels None/{} ve matchExpressions None/[]) → tüm pod'lar seçilir.
    - matchLabels tanımlıysa → pod tüm key-value çiftlerini içermelidir (AND).
    - matchExpressions tanımlıysa → her expression sağlanmalıdır (AND).
    - Her ikisi de tanımlıysa → her ikisinin tüm koşulları sağlanmalıdır (AND).

    :param pod_labels: Pod'un metadata.labels dict'i (boş dict kabul edilir).
    :param pod_selector: kubernetes client V1LabelSelector nesnesi.
    :returns: True ise pod bu policy kapsamında, False ise dışında.
    """
    if pod_selector is None:
        return True

    match_labels = getattr(pod_selector, 'match_labels', None) or {}
    match_expressions = getattr(pod_selector, 'match_expressions', None) or []

    # Tamamen boş podSelector → namespace'teki tüm pod'ları seç
    if not match_labels and not match_expressions:
        return True

    # --- matchLabels kontrolü (AND) ---
    for key, value in match_labels.items():
        if pod_labels.get(key) != value:
            return False

    # --- matchExpressions kontrolü (AND) ---
    for expr in match_expressions:
        key = getattr(expr, 'key', None)
        # operator değerini küçük harfe normalize et
        operator = (getattr(expr, 'operator', '') or '').lower()
        values = list(getattr(expr, 'values', None) or [])

        if operator == 'in':
            # key mevcut olmalı VE değeri values listesinde olmalı
            if pod_labels.get(key) not in values:
                return False
        elif operator == 'notin':
            # key mevcut değilse → koşul sağlanmış sayılır
            # key mevcutsa → değeri values listesinde OLMAMALI
            if key in pod_labels and pod_labels[key] in values:
                return False
        elif operator == 'exists':
            # key pod'da mevcut olmalı
            if key not in pod_labels:
                return False
        elif operator == 'doesnotexist':
            # key pod'da mevcut OLMAMALI
            if key in pod_labels:
                return False
        # Tanınmayan operator → güvenli taraf: koşul sağlanmamış say
        else:
            return False

    return True


def _netpol_pod_selector_summary(pod_selector) -> str:
    """NetworkPolicy podSelector'ının kısa metin özetini döner (UI için).

    :param pod_selector: V1LabelSelector nesnesi veya None.
    :returns: Örn. 'app=web, tier=frontend' ya da '(tümü)'.
    """
    if pod_selector is None:
        return '(tümü)'
    match_labels = getattr(pod_selector, 'match_labels', None) or {}
    match_expressions = getattr(pod_selector, 'match_expressions', None) or []
    if not match_labels and not match_expressions:
        return '(tümü)'
    parts = [f'{k}={v}' for k, v in match_labels.items()]
    for expr in match_expressions:
        key = getattr(expr, 'key', '')
        operator = getattr(expr, 'operator', '')
        values = list(getattr(expr, 'values', None) or [])
        if values:
            parts.append(f'{key} {operator} [{",".join(values)}]')
        else:
            parts.append(f'{key} {operator}')
    return ', '.join(parts) if parts else '(tümü)'


# =============================================================================
# NetworkPolicy Kapsam Analizi — In-Memory Cache
# =============================================================================

netpol_coverage_cache = None        # dict veya None
netpol_coverage_cache_time = 0      # epoch seconds
NETPOL_COVERAGE_CACHE_TTL = 30      # saniye; büyük cluster'larda artırılabilir
_npc_last_error = None              # str | None -- son netpol-coverage hatası (başarılı ise None) (AC-3)
_npc_consecutive_errors: int = 0   # ardışık hata sayacı (AC-3)


def update_netpol_coverage_cache():
    """Tüm namespace'ler için NetworkPolicy + Pod listesini çekip kapsam analizini hesaplar,
    sonucu modül seviyesi netpol_coverage_cache dict'ine yazar.

    kubeconfigs_activate() tarafından kubeconfig değişiminde de çağrılır.
    Toplam süre 5 saniyeyi aşarsa stderr'e uyarı yazar.
    """
    global netpol_coverage_cache, netpol_coverage_cache_time, _npc_last_error
    _start = time.time()
    try:
        configure_kube_client()
        core_v1 = client.CoreV1Api()
        net_v1 = client.NetworkingV1Api()

        # Tüm namespace'leri listele
        namespaces = core_v1.list_namespace().items

        # Tüm NetworkPolicy'leri tek seferde çek; namespace başına grup oluştur
        all_netpols = net_v1.list_network_policy_for_all_namespaces().items
        netpols_by_ns: dict = {}
        for np in all_netpols:
            ns_name = np.metadata.namespace
            netpols_by_ns.setdefault(ns_name, []).append(np)

        ns_results = []
        total_covered_ns = 0
        total_uncovered_ns = 0
        total_pods_all = 0
        total_covered_pods_all = 0

        for ns in namespaces:
            ns_name = ns.metadata.name
            ns_netpols = netpols_by_ns.get(ns_name, [])
            policy_count = len(ns_netpols)

            # Pod'ları listele — hata olursa boş liste kullan
            try:
                pods = core_v1.list_namespaced_pod(ns_name).items
            except Exception as _pod_err:
                print(
                    f'NETPOL COVERAGE CACHE: pod list error for ns {ns_name}: {_pod_err}',
                    file=sys.stderr
                )
                pods = []

            total_pods = len(pods)

            if policy_count == 0:
                # Hiç NetworkPolicy yok → tüm pod'lar korumasız
                covered_pods = 0
                uncovered_pods = total_pods
                status = 'unprotected'
                total_uncovered_ns += 1
            else:
                covered_count = 0
                for pod in pods:
                    pod_labels = pod.metadata.labels or {}
                    matched = False
                    for np in ns_netpols:
                        pod_selector = getattr(np.spec, 'pod_selector', None) if np.spec else None
                        if _pod_matches_pod_selector(pod_labels, pod_selector):
                            matched = True
                            break
                    if matched:
                        covered_count += 1

                covered_pods = covered_count
                uncovered_pods = total_pods - covered_count

                if uncovered_pods == 0:
                    status = 'protected'
                else:
                    status = 'partial'

                total_covered_ns += 1

            total_pods_all += total_pods
            total_covered_pods_all += covered_pods

            ns_results.append({
                'name': ns_name,
                'policy_count': policy_count,
                'total_pods': total_pods,
                'covered_pods': covered_pods,
                'uncovered_pods': uncovered_pods,
                'status': status,
            })

        total_ns = len(namespaces)
        uncovered_ns = total_ns - total_covered_ns

        ns_coverage_pct = round((total_covered_ns / total_ns) * 100, 1) if total_ns > 0 else 0.0
        pod_coverage_pct = (
            round((total_covered_pods_all / total_pods_all) * 100, 1)
            if total_pods_all > 0 else 100.0
        )

        netpol_coverage_cache = {
            'cluster_summary': {
                'total_namespaces': total_ns,
                'covered_namespaces': total_covered_ns,
                'uncovered_namespaces': uncovered_ns,
                'namespace_coverage_pct': ns_coverage_pct,
                'total_pods': total_pods_all,
                'covered_pods': total_covered_pods_all,
                'uncovered_pods': total_pods_all - total_covered_pods_all,
                'pod_coverage_pct': pod_coverage_pct,
            },
            'namespaces': ns_results,
        }
        netpol_coverage_cache_time = time.time()
        _npc_last_error = None  # başarılı güncelleme -- hata durumunu sıfırla

        elapsed = time.time() - _start
        if elapsed > 5:
            print(
                f'NETPOL COVERAGE CACHE WARNING: hesaplama süresi {elapsed:.1f}s (>5s)',
                file=sys.stderr
            )
    except Exception as e:
        _npc_last_error = str(e)  # başarısız güncelleme -- hatayı kaydet; refresher loglar


def netpol_coverage_cache_refresher():
    """Daemon thread döngüsü: TTL aralıklarla netpol kapsam cache'ini yeniler (AC-2)."""
    global _npc_consecutive_errors
    while True:
        prev_error = _npc_last_error
        update_netpol_coverage_cache()
        if _npc_last_error is None:
            if prev_error is not None and _npc_consecutive_errors > 0:
                print(
                    f'NETPOL COVERAGE CACHE: kurtarıldı ({_npc_consecutive_errors} ardışık hata sonrası).',
                    file=sys.stderr
                )
            _npc_consecutive_errors = 0
            time.sleep(NETPOL_COVERAGE_CACHE_TTL)
        else:
            _npc_consecutive_errors += 1
            if _should_log(_npc_consecutive_errors):
                print(
                    f'NETPOL COVERAGE CACHE: ardışık hata #{_npc_consecutive_errors}: {_npc_last_error}',
                    file=sys.stderr
                )
            time.sleep(compute_backoff_sleep(_npc_consecutive_errors, NETPOL_COVERAGE_CACHE_TTL))


def start_netpol_coverage_cache():
    """Arka plan cache thread'ini başlatır (daemon, uygulama ömrü boyunca yaşar)."""
    t = threading.Thread(target=netpol_coverage_cache_refresher, daemon=True)
    t.start()
