"""blueprints/security/scanning.py — Trivy Operator, Vulnerabilities, PSS ve NetworkPolicy route'ları.

12 route:
  GET /trivy-operator, GET /trivy-operator/status
  POST /trivy-operator/install
  GET /trivy-operator/list-vulnerabilityreports
  POST /trivy-operator/scan
  GET /trivy-operator/get-vulnerabilityreport
  GET /vulnerabilities
  GET /pod-security-standards
  GET /k8s-explorer/pss-summary, GET /k8s-explorer/pss-namespace-detail
  GET /k8s-explorer/netpol-coverage-summary, GET /k8s-explorer/netpol-coverage-ns-detail
"""

import os
import sys
import subprocess
import time

from datetime import datetime
from flask import jsonify, render_template, request
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
from web.i18n import translate
from web.blueprints.security._vuln_checks import scan_pod_template

from web.blueprints.security import bp_security


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

@bp_security.route('/vulnerabilities')
def vulnerabilities():
    """Canli cluster uzerinde Deployment, StatefulSet ve DaemonSet'leri tayan zafiyet sayfasini render eder.

    Her workload icin scan_pod_template() cagirilir; i18n anahtarlari route seviyesinde
    cevrilerek template'e list[dict] olarak iletilir.

    NetworkPolicy kontrolu namespace basina bir kez yapilir (spec risk #4: tekrar API cagrisi yok).

    Template degiskenleri:
        vulnerabilities: dict[str, list[dict]]  — key: "ns/Kind/name", value: finding listesi
        pod_images:      dict[str, str]         — key: ayni format, value: imaj isimleri
        all_namespaces:  list[str]
        selected_namespace: str
    """
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        apps_v1 = client.AppsV1Api()
        core_v1 = client.CoreV1Api()
        networking_v1 = client.NetworkingV1Api()
    except Exception as e:
        return render_template('vulnerabilities.html', error=str(e))

    lang = request.cookies.get('lang') or 'tr'
    all_vulnerabilities = {}
    pod_images = {}

    selected_namespace = request.args.get('namespace', 'all')
    namespaces = [ns.metadata.name for ns in core_v1.list_namespace().items]

    if selected_namespace != 'all' and selected_namespace in namespaces:
        target_namespaces = [selected_namespace]
    else:
        target_namespaces = namespaces

    # Namespace basina NetworkPolicy varligini once kontrol et (bir kez API cagrisi, cache'le).
    # scan_pod_template'e networking_v1=None iletilir; netpol findingini route burada ekler.
    netpol_cache = {}  # ns -> bool (True: NetworkPolicy var, False: yok)

    def _ns_has_netpol(ns):
        if ns not in netpol_cache:
            try:
                policies = networking_v1.list_namespaced_network_policy(ns)
                netpol_cache[ns] = bool(policies.items)
            except Exception:
                # API hatasi varsa false-positive olusmasini onlemek icin True kabul et
                netpol_cache[ns] = True
        return netpol_cache[ns]

    def _resolve_findings(raw_findings, ns):
        """i18n_key + i18n_params'i cevirilmis mesaja donusturur ve netpol finding'i ekler."""
        result = []
        for f in raw_findings:
            msg = translate(f['i18n_key'], lang)
            if f['i18n_params']:
                msg = msg.format(**f['i18n_params'])
            result.append({
                'check_id': f['check_id'],
                'severity': f['severity'],
                'message': msg,
                'container': f['container'],
            })

        # Check 13: NetworkPolicy (namespace basina bir kez; cached)
        if not _ns_has_netpol(ns):
            netpol_msg = translate('vuln.check.no_network_policy', lang).format(namespace=ns)
            result.append({
                'check_id': 'no-network-policy',
                'severity': 'medium',
                'message': netpol_msg,
                'container': None,
            })

        return result

    for ns in target_namespaces:
        # --- Deployment'lar ---
        try:
            deployments = apps_v1.list_namespaced_deployment(ns).items
        except Exception:
            deployments = []
        for dep in deployments:
            key = f"{ns}/Deployment/{dep.metadata.name}"
            raw = scan_pod_template(dep.spec.template, ns, 'Deployment', dep.metadata.name)
            findings = _resolve_findings(raw, ns)
            if findings:
                all_vulnerabilities[key] = findings
            if dep.spec.template.spec.containers:
                pod_images[key] = ', '.join([ct.image for ct in dep.spec.template.spec.containers])

        # --- StatefulSet'ler ---
        try:
            statefulsets = apps_v1.list_namespaced_stateful_set(ns).items
        except Exception:
            statefulsets = []
        for sts in statefulsets:
            key = f"{ns}/StatefulSet/{sts.metadata.name}"
            raw = scan_pod_template(sts.spec.template, ns, 'StatefulSet', sts.metadata.name)
            findings = _resolve_findings(raw, ns)
            if findings:
                all_vulnerabilities[key] = findings
            if sts.spec.template.spec.containers:
                pod_images[key] = ', '.join([ct.image for ct in sts.spec.template.spec.containers])

        # --- DaemonSet'ler ---
        try:
            daemonsets = apps_v1.list_namespaced_daemon_set(ns).items
        except Exception:
            daemonsets = []
        for ds in daemonsets:
            key = f"{ns}/DaemonSet/{ds.metadata.name}"
            raw = scan_pod_template(ds.spec.template, ns, 'DaemonSet', ds.metadata.name)
            findings = _resolve_findings(raw, ns)
            if findings:
                all_vulnerabilities[key] = findings
            if ds.spec.template.spec.containers:
                pod_images[key] = ', '.join([ct.image for ct in ds.spec.template.spec.containers])

    return render_template(
        'vulnerabilities.html',
        vulnerabilities=all_vulnerabilities,
        pod_images=pod_images,
        all_namespaces=namespaces,
        selected_namespace=selected_namespace,
    )


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
