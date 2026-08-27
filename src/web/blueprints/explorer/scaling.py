"""explorer/scaling.py — Ölçeklendirme politika route'ları.

İçerik: hpa-summary, hpa, update-hpa, delete-hpa,
pdb-summary, pdb, update-pdb, delete-pdb.
"""

from flask import jsonify, request
from kubernetes import client
from kubernetes.client.rest import ApiException

from web.kubeconfig_manager import configure_kube_client
from web.audit_log import record_audit_event, _short_session_id
from web.confirmation import require_confirm_name

from web.blueprints.explorer import bp_explorer


@bp_explorer.route('/k8s-explorer/hpa-summary')
def hpa_summary():
    try:
        namespace = request.args.get('namespace')
        configure_kube_client()
        autoscaling_v1 = client.AutoscalingV1Api()
        if namespace and namespace != 'all':
            hpas = autoscaling_v1.list_namespaced_horizontal_pod_autoscaler(namespace).items
        else:
            hpas = autoscaling_v1.list_horizontal_pod_autoscaler_for_all_namespaces().items
        result = []
        for hpa in hpas:
            md = hpa.metadata
            spec = hpa.spec
            status = hpa.status
            result.append({
                'namespace': getattr(md, 'namespace', None),
                'name': getattr(md, 'name', None),
                'min_replicas': getattr(spec, 'min_replicas', None),
                'max_replicas': getattr(spec, 'max_replicas', None),
                'current_replicas': getattr(status, 'current_replicas', None),
                'desired_replicas': getattr(status, 'desired_replicas', None),
                'creation_timestamp': md.creation_timestamp.isoformat() if getattr(md, 'creation_timestamp', None) else None,
                'metrics': getattr(spec, 'metrics', None),
                'target_kind': getattr(spec.scale_target_ref, 'kind', None) if getattr(spec, 'scale_target_ref', None) else None,
                'target_name': getattr(spec.scale_target_ref, 'name', None) if getattr(spec, 'scale_target_ref', None) else None
            })
        return jsonify({'hpas': result})
    except Exception as e:
        return jsonify({'hpas': [], 'error': str(e)})


# Get a single HPA details
@bp_explorer.route('/k8s-explorer/hpa')
def get_hpa():
    try:
        name = request.args.get('name')
        namespace = request.args.get('namespace')
        if not name or not namespace:
            return jsonify({'error': 'name and namespace are required'}), 400
        configure_kube_client()
        autoscaling_v1 = client.AutoscalingV1Api()
        hpa = autoscaling_v1.read_namespaced_horizontal_pod_autoscaler(name=name, namespace=namespace)
        md = hpa.metadata
        spec = hpa.spec
        status = hpa.status
        return jsonify({'hpa': {
            'namespace': getattr(md, 'namespace', None),
            'name': getattr(md, 'name', None),
            'min_replicas': getattr(spec, 'min_replicas', None),
            'max_replicas': getattr(spec, 'max_replicas', None),
            'current_replicas': getattr(status, 'current_replicas', None),
            'desired_replicas': getattr(status, 'desired_replicas', None),
            'creation_timestamp': md.creation_timestamp.isoformat() if getattr(md, 'creation_timestamp', None) else None,
            'metrics': getattr(spec, 'metrics', None),
            'target_kind': getattr(spec.scale_target_ref, 'kind', None) if getattr(spec, 'scale_target_ref', None) else None,
            'target_name': getattr(spec.scale_target_ref, 'name', None) if getattr(spec, 'scale_target_ref', None) else None
        }})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Update HPA (min/max replicas)
@bp_explorer.route('/k8s-explorer/update-hpa', methods=['POST'])
def update_hpa():
    try:
        data = request.get_json(force=True) or {}
        name = data.get('name')
        namespace = data.get('namespace')
        min_r = data.get('min_replicas')
        max_r = data.get('max_replicas')
        if not name or not namespace:
            return jsonify({'error': 'name and namespace are required'}), 400
        if min_r is None and max_r is None:
            return jsonify({'error': 'nothing to update'}), 400
        configure_kube_client()
        autoscaling_v1 = client.AutoscalingV1Api()
        patch_spec = {}
        if min_r is not None:
            try:
                patch_spec['minReplicas'] = int(min_r)
            except Exception:
                return jsonify({'error': 'min_replicas must be an integer'}), 400
        if max_r is not None:
            try:
                patch_spec['maxReplicas'] = int(max_r)
            except Exception:
                return jsonify({'error': 'max_replicas must be an integer'}), 400
        patch_body = {'spec': patch_spec}
        autoscaling_v1.patch_namespaced_horizontal_pod_autoscaler(name=name, namespace=namespace, body=patch_body)
        record_audit_event(
            action='update',
            resource_type='HPA',
            resource_name=name,
            namespace=namespace,
            session_id=_short_session_id(request.cookies.get('session')),
            details=f'min_replicas={min_r}, max_replicas={max_r}',
        )
        return jsonify({'status': 'ok', 'name': name, 'namespace': namespace})
    except ApiException as e:
        try:
            return jsonify({'error': e.body}), e.status
        except Exception:
            return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Delete HPA
@bp_explorer.route('/k8s-explorer/delete-hpa', methods=['POST'])
def delete_hpa():
    try:
        data = request.get_json(force=True) or {}
        name = data.get('name')
        namespace = data.get('namespace')
        if not name or not namespace:
            return jsonify({'error': 'name and namespace are required'}), 400
        err = require_confirm_name(data)
        if err:
            return err
        configure_kube_client()
        autoscaling_v1 = client.AutoscalingV1Api()
        autoscaling_v1.delete_namespaced_horizontal_pod_autoscaler(name=name, namespace=namespace)
        record_audit_event(
            action='delete',
            resource_type='HPA',
            resource_name=name,
            namespace=namespace,
            session_id=_short_session_id(request.cookies.get('session')),
        )
        return jsonify({'status': 'deleted', 'name': name, 'namespace': namespace})
    except ApiException as e:
        try:
            return jsonify({'error': e.body}), e.status
        except Exception:
            return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# PDB summary endpoint
@bp_explorer.route('/k8s-explorer/pdb-summary')
def pdb_summary():
    try:
        namespace = request.args.get('namespace')
        configure_kube_client()
        policy_v1 = client.PolicyV1Api()
        if namespace and namespace not in ('all', None):
            pdbs = policy_v1.list_namespaced_pod_disruption_budget(namespace).items
        else:
            pdbs = policy_v1.list_pod_disruption_budget_for_all_namespaces().items
        result = []
        for pdb in pdbs:
            md = pdb.metadata
            spec = pdb.spec or {}
            status = pdb.status or {}
            min_avail = getattr(spec, 'min_available', None)
            max_unavail = getattr(spec, 'max_unavailable', None)
            def int_or_str(val):
                try:
                    return str(val)
                except Exception:
                    return None
            result.append({
                'namespace': getattr(md, 'namespace', None),
                'name': getattr(md, 'name', None),
                'min_available': int_or_str(min_avail),
                'max_unavailable': int_or_str(max_unavail),
                'disruptions_allowed': getattr(status, 'disruptions_allowed', None),
                'current_healthy': getattr(status, 'current_healthy', None),
                'desired_healthy': getattr(status, 'desired_healthy', None),
                'expected_pods': getattr(status, 'expected_pods', None),
                'creation_timestamp': md.creation_timestamp.isoformat() if getattr(md, 'creation_timestamp', None) else None,
                'selector': getattr(spec, 'selector', None).to_dict() if getattr(spec, 'selector', None) else None
            })
        return jsonify({'pdbs': result})
    except Exception as e:
        return jsonify({'pdbs': [], 'error': str(e)})


# Get a single PDB details
@bp_explorer.route('/k8s-explorer/pdb')
def get_pdb():
    try:
        name = request.args.get('name')
        namespace = request.args.get('namespace')
        if not name or not namespace:
            return jsonify({'error': 'name and namespace are required'}), 400
        configure_kube_client()
        policy_v1 = client.PolicyV1Api()
        pdb = policy_v1.read_namespaced_pod_disruption_budget(name=name, namespace=namespace)
        md = pdb.metadata
        spec = pdb.spec or {}
        status = pdb.status or {}
        def int_or_str(val):
            try:
                return str(val) if val is not None else None
            except Exception:
                return None
        return jsonify({'pdb': {
            'namespace': getattr(md, 'namespace', None),
            'name': getattr(md, 'name', None),
            'min_available': int_or_str(getattr(spec, 'min_available', None)),
            'max_unavailable': int_or_str(getattr(spec, 'max_unavailable', None)),
            'disruptions_allowed': getattr(status, 'disruptions_allowed', None),
            'current_healthy': getattr(status, 'current_healthy', None),
            'desired_healthy': getattr(status, 'desired_healthy', None),
            'expected_pods': getattr(status, 'expected_pods', None),
            'creation_timestamp': md.creation_timestamp.isoformat() if getattr(md, 'creation_timestamp', None) else None,
            'selector': getattr(spec, 'selector', None).to_dict() if getattr(spec, 'selector', None) else None
        }})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Update PDB (minAvailable/maxUnavailable)
@bp_explorer.route('/k8s-explorer/update-pdb', methods=['POST'])
def update_pdb():
    try:
        data = request.get_json(force=True) or {}
        name = data.get('name')
        namespace = data.get('namespace')
        min_av = data.get('min_available')
        max_un = data.get('max_unavailable')
        if not name or not namespace:
            return jsonify({'error': 'name and namespace are required'}), 400
        if (min_av is None or min_av == '') and (max_un is None or max_un == ''):
            return jsonify({'error': 'nothing to update'}), 400
        configure_kube_client()
        policy_v1 = client.PolicyV1Api()

        def parse_int_or_str(v):
            if v is None or v == '':
                return None
            # If purely digits, send as int; else keep as string (supports percentages like '50%')
            try:
                if isinstance(v, (int, float)) or (isinstance(v, str) and v.strip().isdigit()):
                    return int(v)
            except Exception:
                pass
            return str(v)

        patch_spec = {}
        pav = parse_int_or_str(min_av)
        pmax = parse_int_or_str(max_un)

        # Validate: Kubernetes PDB allows only one of minAvailable or maxUnavailable
        if pav is not None and pmax is not None:
            return jsonify({'error': 'min_available ve max_unavailable aynı anda ayarlanamaz. Yalnızca birini doldurun.'}), 400

        # If setting one, ensure the other is cleared to avoid server-side validation errors
        if pav is not None:
            patch_spec['minAvailable'] = pav
            # If max was provided as empty or missing, explicitly clear it
            if max_un == '' or max_un is None:
                patch_spec['maxUnavailable'] = None
        if pmax is not None:
            patch_spec['maxUnavailable'] = pmax
            if min_av == '' or min_av is None:
                patch_spec['minAvailable'] = None

        patch_body = {'spec': patch_spec}
        policy_v1.patch_namespaced_pod_disruption_budget(name=name, namespace=namespace, body=patch_body)
        record_audit_event(
            action='update',
            resource_type='PDB',
            resource_name=name,
            namespace=namespace,
            session_id=_short_session_id(request.cookies.get('session')),
            details=f'min_available={min_av}, max_unavailable={max_un}',
        )
        return jsonify({'status': 'ok', 'name': name, 'namespace': namespace})
    except ApiException as e:
        try:
            return jsonify({'error': e.body}), e.status
        except Exception:
            return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Delete PDB
@bp_explorer.route('/k8s-explorer/delete-pdb', methods=['POST'])
def delete_pdb():
    try:
        data = request.get_json(force=True) or {}
        name = data.get('name')
        namespace = data.get('namespace')
        if not name or not namespace:
            return jsonify({'error': 'name and namespace are required'}), 400
        err = require_confirm_name(data)
        if err:
            return err
        configure_kube_client()
        policy_v1 = client.PolicyV1Api()
        policy_v1.delete_namespaced_pod_disruption_budget(name=name, namespace=namespace)
        record_audit_event(
            action='delete',
            resource_type='PDB',
            resource_name=name,
            namespace=namespace,
            session_id=_short_session_id(request.cookies.get('session')),
        )
        return jsonify({'status': 'deleted', 'name': name, 'namespace': namespace})
    except ApiException as e:
        try:
            return jsonify({'error': e.body}), e.status
        except Exception:
            return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp_explorer.route('/k8s-explorer/create-hpa', methods=['POST'])
def create_hpa():
    """Yeni bir HorizontalPodAutoscaler oluşturur (autoscaling/v2, tek CPU metriği).

    Method: POST
    Path:   /k8s-explorer/create-hpa

    Body (JSON):
        name               (str): HPA adı (zorunlu).
        namespace          (str): Hedef namespace (zorunlu).
        target_kind        (str): Hedef kaynak türü — Deployment, StatefulSet veya ReplicaSet (zorunlu).
        target_name        (str): Hedef kaynak adı (zorunlu).
        min_replicas       (int): Minimum replika sayısı (zorunlu, >= 1).
        max_replicas       (int): Maksimum replika sayısı (zorunlu, >= min_replicas).
        cpu_target_percent (int): Hedef CPU kullanım yüzdesi (zorunlu, 1-100).

    Yanıt (201):
        {"status": "ok"}

    Hatalar:
        400: Zorunlu alan eksik veya min_replicas > max_replicas.
        ApiException HTTP kodu: Kubernetes API hatası.
        500: Beklenmedik sunucu hatası.
    """
    try:
        data = request.get_json() or {}
        name = data.get('name')
        namespace = data.get('namespace')
        target_kind = data.get('target_kind')
        target_name = data.get('target_name')
        min_replicas = data.get('min_replicas')
        max_replicas = data.get('max_replicas')
        cpu_target_percent = data.get('cpu_target_percent')
        if not name or not namespace or not target_kind or not target_name:
            return jsonify({'error': 'name, namespace, target_kind and target_name are required'}), 400
        if min_replicas is None or max_replicas is None or cpu_target_percent is None:
            return jsonify({'error': 'min_replicas, max_replicas and cpu_target_percent are required'}), 400
        try:
            min_replicas = int(min_replicas)
            max_replicas = int(max_replicas)
            cpu_target_percent = int(cpu_target_percent)
        except (ValueError, TypeError):
            return jsonify({'error': 'min_replicas, max_replicas and cpu_target_percent must be integers'}), 400
        if min_replicas > max_replicas:
            return jsonify({'error': 'min_replicas, max_replicas degerinden buyuk olamaz'}), 400
        configure_kube_client()
        autoscaling_v2 = client.AutoscalingV2Api()
        body = client.V2HorizontalPodAutoscaler(
            metadata=client.V1ObjectMeta(name=name, namespace=namespace),
            spec=client.V2HorizontalPodAutoscalerSpec(
                scale_target_ref=client.V2CrossVersionObjectReference(
                    api_version='apps/v1',
                    kind=target_kind,
                    name=target_name
                ),
                min_replicas=min_replicas,
                max_replicas=max_replicas,
                metrics=[
                    client.V2MetricSpec(
                        type='Resource',
                        resource=client.V2ResourceMetricSource(
                            name='cpu',
                            target=client.V2MetricTarget(
                                type='Utilization',
                                average_utilization=cpu_target_percent
                            )
                        )
                    )
                ]
            )
        )
        autoscaling_v2.create_namespaced_horizontal_pod_autoscaler(namespace, body)
        record_audit_event(
            action='create',
            resource_type='HPA',
            resource_name=name,
            namespace=namespace,
            session_id=_short_session_id(request.cookies.get('session')),
        )
        return jsonify({'status': 'ok'}), 201
    except ApiException as e:
        try:
            return jsonify({'error': e.body}), e.status
        except Exception:
            return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp_explorer.route('/k8s-explorer/create-pdb', methods=['POST'])
def create_pdb():
    """Yeni bir PodDisruptionBudget oluşturur.

    Method: POST
    Path:   /k8s-explorer/create-pdb

    Body (JSON):
        name         (str):  PDB adı (zorunlu).
        namespace    (str):  Hedef namespace (zorunlu).
        match_labels (dict): Selector etiketleri — en az 1 çift zorunlu.
        policy       (str):  "minAvailable" veya "maxUnavailable" (zorunlu).
                             Seçime göre yalnızca ilgili spec alanı doldurulur.
        value        (str):  Sayı ("1") veya yüzde ("50%") (zorunlu).

    Yanıt (201):
        {"status": "ok"}

    Hatalar:
        400: Zorunlu alan eksik veya match_labels boş.
        ApiException HTTP kodu: Kubernetes API hatası.
        500: Beklenmedik sunucu hatası.
    """
    try:
        data = request.get_json() or {}
        name = data.get('name')
        namespace = data.get('namespace')
        match_labels = data.get('match_labels') or {}
        policy = data.get('policy')
        value = data.get('value')
        if not name or not namespace:
            return jsonify({'error': 'name and namespace are required'}), 400
        if not match_labels:
            return jsonify({'error': 'en az bir match_labels cifti gereklidir'}), 400
        if not policy or value is None or value == '':
            return jsonify({'error': 'policy and value are required'}), 400
        # Değeri sayı ise int, yüzde ise string ("50%") olarak gönder
        str_value = str(value).strip()
        try:
            parsed_value = int(str_value) if str_value.isdigit() else str_value
        except Exception:
            parsed_value = str_value
        # policy'e göre SADECE ilgili alan doldurulur, diğeri DAHIL EDİLMEZ
        min_available = None
        max_unavailable = None
        if policy == 'minAvailable':
            min_available = parsed_value
        else:
            max_unavailable = parsed_value
        configure_kube_client()
        policy_v1 = client.PolicyV1Api()
        body = client.V1PodDisruptionBudget(
            metadata=client.V1ObjectMeta(name=name, namespace=namespace),
            spec=client.V1PodDisruptionBudgetSpec(
                selector=client.V1LabelSelector(match_labels=match_labels),
                min_available=min_available,
                max_unavailable=max_unavailable
            )
        )
        policy_v1.create_namespaced_pod_disruption_budget(namespace, body)
        record_audit_event(
            action='create',
            resource_type='PDB',
            resource_name=name,
            namespace=namespace,
            session_id=_short_session_id(request.cookies.get('session')),
        )
        return jsonify({'status': 'ok'}), 201
    except ApiException as e:
        try:
            return jsonify({'error': e.body}), e.status
        except Exception:
            return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500
