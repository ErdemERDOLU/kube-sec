"""explorer/cluster.py — Küme yönetim route'ları.

İçerik: nodes+cordon/uncordon/drain, rbac-summary/detail,
priority-class*, runtime-class*, leases, webhooks.
HPA ve PDB route'ları explorer/scaling.py dosyasına taşındı.
"""

import json

from flask import jsonify, request
from kubernetes import client
from kubernetes.client.rest import ApiException

from web.kubeconfig_manager import load_kube_config_active
from web.audit_log import record_audit_event, _short_session_id

from web.blueprints.explorer import bp_explorer


@bp_explorer.route('/k8s-explorer/nodes')
def k8s_explorer_nodes():
    try:
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        kube_client = type('KubeClient', (), {})()
        kube_client.core_v1 = client.CoreV1Api()
        nodes = kube_client.core_v1.list_node().items
        result = []
        for n in nodes:
            status = 'Ready'
            unschedulable = getattr(n.spec, 'unschedulable', False)
            for cond in n.status.conditions or []:
                if cond.type == 'Ready' and cond.status != 'True':
                    status = 'NotReady'
            # unschedulable ise status'ü Cordoned olarak göster
            if unschedulable:
                status = 'Cordoned'
            result.append({'name': n.metadata.name, 'status': status, 'unschedulable': unschedulable})
        return jsonify({'nodes': result})
    except Exception as e:
        return jsonify({'error': str(e)})


# Node uncordon endpoint
@bp_explorer.route('/k8s-explorer/node-uncordon', methods=['POST'])
def k8s_explorer_node_uncordon():
    try:
        data = request.get_json(force=True)
        node_name = data.get('node')
        if not node_name:
            return 'Node adı zorunlu', 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        kube_client = type('KubeClient', (), {})()
        kube_client.core_v1 = client.CoreV1Api()
        # Node'u uncordon et
        body = {"spec": {"unschedulable": False}}
        kube_client.core_v1.patch_node(node_name, body)
        record_audit_event(
            action='uncordon',
            resource_type='Node',
            resource_name=node_name,
            namespace=None,
            session_id=_short_session_id(request.cookies.get('session')),
        )
        return 'Node uncordon (schedulable) yapıldı.'
    except Exception as e:
        return str(e), 500


# Node cordon endpoint
@bp_explorer.route('/k8s-explorer/node-cordon', methods=['POST'])
def k8s_explorer_node_cordon():
    try:
        data = request.get_json(force=True)
        node_name = data.get('node')
        if not node_name:
            return 'Node adı zorunlu', 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        kube_client = type('KubeClient', (), {})()
        kube_client.core_v1 = client.CoreV1Api()
        # Node'u cordon et
        body = {"spec": {"unschedulable": True}}
        kube_client.core_v1.patch_node(node_name, body)
        record_audit_event(
            action='cordon',
            resource_type='Node',
            resource_name=node_name,
            namespace=None,
            session_id=_short_session_id(request.cookies.get('session')),
        )
        return 'Node cordon (unschedulable) yapıldı.'
    except Exception as e:
        return str(e), 500


# Node drain endpoint
@bp_explorer.route('/k8s-explorer/node-drain', methods=['POST'])
def k8s_explorer_node_drain():
    try:
        data = request.get_json(force=True)
        node_name = data.get('node')
        if not node_name:
            return 'Node adı zorunlu', 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        kube_client = type('KubeClient', (), {})()
        kube_client.core_v1 = client.CoreV1Api()
        log_lines = []
        # Node'u cordon et
        body = {"spec": {"unschedulable": True}}
        kube_client.core_v1.patch_node(node_name, body)
        log_lines.append(f"Node '{node_name}' cordon (unschedulable) yapıldı.")
        # Node'daki podları evict et
        pods = kube_client.core_v1.list_pod_for_all_namespaces(field_selector=f'spec.nodeName={node_name}').items
        for pod in pods:
            owner_refs = getattr(pod.metadata, 'owner_references', []) or []
            is_daemonset = any(getattr(ref, 'kind', '') == 'DaemonSet' for ref in owner_refs)
            if is_daemonset:
                log_lines.append(f"Pod {pod.metadata.name} (ns: {pod.metadata.namespace}) bir DaemonSet'e ait, atlanıyor.")
                continue
            try:
                kube_client.core_v1.delete_namespaced_pod(pod.metadata.name, pod.metadata.namespace, grace_period_seconds=30)
                log_lines.append(f"Pod {pod.metadata.name} (ns: {pod.metadata.namespace}) drain/evict edildi.")
            except Exception as ex:
                log_lines.append(f"Pod {pod.metadata.name} (ns: {pod.metadata.namespace}) drain edilirken hata: {str(ex)}")
        log_lines.append("Drain işlemi tamamlandı.")
        record_audit_event(
            action='drain',
            resource_type='Node',
            resource_name=node_name,
            namespace=None,
            session_id=_short_session_id(request.cookies.get('session')),
        )
        return {"logs": log_lines}, 200
    except Exception as e:
        return {"logs": [str(e)]}, 500


@bp_explorer.route('/k8s-explorer/rbac-summary')
def rbac_summary():
    """Return summaries for ServiceAccounts (namespaced), Roles (namespaced), RoleBindings (namespaced), ClusterRoles (cluster), ClusterRoleBindings (cluster).
       Optional namespace param filters namespaced sets, default=default."""
    try:
        namespace = request.args.get('namespace') or 'default'
        load_kube_config_active()
        c = client.Configuration.get_default_copy(); c.verify_ssl=False; c.assert_hostname=False; client.Configuration.set_default(c)
        core_v1 = client.CoreV1Api()
        rbac_v1 = client.RbacAuthorizationV1Api()

        # ServiceAccounts
        if namespace == 'all':
            sas = core_v1.list_service_account_for_all_namespaces().items
        else:
            sas = core_v1.list_namespaced_service_account(namespace).items
        sa_list = []
        for sa in sas:
            sa_list.append({
                'namespace': getattr(sa.metadata,'namespace',None),
                'name': getattr(sa.metadata,'name',None),
                'secrets': len(getattr(sa,'secrets',[]) or []),
                'age': sa.metadata.creation_timestamp.isoformat() if getattr(sa.metadata,'creation_timestamp',None) else None
            })

        # Roles
        if namespace == 'all':
            roles_items = []
            for ns in [n.metadata.name for n in core_v1.list_namespace().items]:
                try:
                    roles_items += rbac_v1.list_namespaced_role(ns).items
                except Exception:
                    continue
        else:
            roles_items = rbac_v1.list_namespaced_role(namespace).items
        roles = []
        for r in roles_items:
            rules = getattr(r,'rules',[]) or []
            roles.append({
                'namespace': getattr(r.metadata,'namespace',None),
                'name': getattr(r.metadata,'name',None),
                'rules_count': len(rules),
                'age': r.metadata.creation_timestamp.isoformat() if getattr(r.metadata,'creation_timestamp',None) else None
            })

        # RoleBindings
        if namespace == 'all':
            rbs_items = []
            for ns in [n.metadata.name for n in core_v1.list_namespace().items]:
                try:
                    rbs_items += rbac_v1.list_namespaced_role_binding(ns).items
                except Exception:
                    continue
        else:
            rbs_items = rbac_v1.list_namespaced_role_binding(namespace).items
        role_bindings = []
        for rb in rbs_items:
            subs = getattr(rb,'subjects',[]) or []
            role_ref = getattr(rb,'role_ref',None)
            role_bindings.append({
                'namespace': getattr(rb.metadata,'namespace',None),
                'name': getattr(rb.metadata,'name',None),
                'subjects': len(subs),
                'roleRef': {'kind': getattr(role_ref,'kind',None), 'name': getattr(role_ref,'name',None)} if role_ref else None,
                'age': rb.metadata.creation_timestamp.isoformat() if getattr(rb.metadata,'creation_timestamp',None) else None
            })

        # ClusterRoles
        cr_items = rbac_v1.list_cluster_role().items
        cluster_roles = []
        for cr in cr_items:
            cluster_roles.append({
                'name': getattr(cr.metadata,'name',None),
                'rules_count': len(getattr(cr,'rules',[]) or []),
                'age': cr.metadata.creation_timestamp.isoformat() if getattr(cr.metadata,'creation_timestamp',None) else None
            })

        # ClusterRoleBindings
        crb_items = rbac_v1.list_cluster_role_binding().items
        cluster_role_bindings = []
        for crb in crb_items:
            subs = getattr(crb,'subjects',[]) or []
            role_ref = getattr(crb,'role_ref',None)
            cluster_role_bindings.append({
                'name': getattr(crb.metadata,'name',None),
                'subjects': len(subs),
                'roleRef': {'kind': getattr(role_ref,'kind',None), 'name': getattr(role_ref,'name',None)} if role_ref else None,
                'age': crb.metadata.creation_timestamp.isoformat() if getattr(crb.metadata,'creation_timestamp',None) else None
            })
        return jsonify({'service_accounts': sa_list, 'roles': roles, 'role_bindings': role_bindings, 'cluster_roles': cluster_roles, 'cluster_role_bindings': cluster_role_bindings})
    except Exception as e:
        return jsonify({'error': str(e), 'service_accounts': [], 'roles': [], 'role_bindings': [], 'cluster_roles': [], 'cluster_role_bindings': []}), 500


@bp_explorer.route('/k8s-explorer/rbac-detail')
def rbac_detail():
    try:
        kind = (request.args.get('kind') or '').lower()
        name = request.args.get('name')
        namespace = request.args.get('namespace')
        if not kind or not name:
            return jsonify({'error': 'kind ve name zorunlu'}), 400
        load_kube_config_active(); c = client.Configuration.get_default_copy(); c.verify_ssl=False; c.assert_hostname=False; client.Configuration.set_default(c)
        core_v1 = client.CoreV1Api(); rbac_v1 = client.RbacAuthorizationV1Api()
        obj = None
        if kind == 'serviceaccount':
            if not namespace: return jsonify({'error': 'namespace zorunlu'}), 400
            obj = core_v1.read_namespaced_service_account(name, namespace)
        elif kind == 'role':
            if not namespace: return jsonify({'error': 'namespace zorunlu'}), 400
            obj = rbac_v1.read_namespaced_role(name, namespace)
        elif kind == 'rolebinding':
            if not namespace: return jsonify({'error': 'namespace zorunlu'}), 400
            obj = rbac_v1.read_namespaced_role_binding(name, namespace)
        elif kind == 'clusterrole':
            obj = rbac_v1.read_cluster_role(name)
        elif kind == 'clusterrolebinding':
            obj = rbac_v1.read_cluster_role_binding(name)
        else:
            return jsonify({'error': 'desteklenmeyen kind'}), 400
        # convert via to_dict if exists
        data = getattr(obj,'to_dict',lambda: obj)()
        return jsonify({'object': data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# PriorityClasses summary endpoint (cluster-scoped)
@bp_explorer.route('/k8s-explorer/priority-classes-summary')
def priority_classes_summary():
    try:
        _ = request.args.get('namespace')  # ignored
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        scheduling_v1 = client.SchedulingV1Api()
        pcs = scheduling_v1.list_priority_class().items
        result = []
        for pc in pcs:
            md = pc.metadata
            result.append({
                'name': getattr(md, 'name', None),
                'value': getattr(pc, 'value', None),
                'global_default': getattr(pc, 'global_default', None),
                'description': getattr(pc, 'description', None),
                'preemption_policy': getattr(pc, 'preemption_policy', None),
                'creation_timestamp': md.creation_timestamp.isoformat() if getattr(md, 'creation_timestamp', None) else None
            })
        return jsonify({'priority_classes': result})
    except Exception as e:
        return jsonify({'priority_classes': [], 'error': str(e)})


# Get a single PriorityClass details (cluster-scoped)
@bp_explorer.route('/k8s-explorer/priority-class')
def get_priority_class():
    try:
        name = request.args.get('name')
        if not name:
            return jsonify({'error': 'name is required'}), 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        scheduling_v1 = client.SchedulingV1Api()
        pc = scheduling_v1.read_priority_class(name=name)
        md = pc.metadata
        return jsonify({'priority_class': {
            'name': getattr(md, 'name', None),
            'value': getattr(pc, 'value', None),
            'global_default': getattr(pc, 'global_default', None),
            'description': getattr(pc, 'description', None),
            'preemption_policy': getattr(pc, 'preemption_policy', None),
            'creation_timestamp': md.creation_timestamp.isoformat() if getattr(md, 'creation_timestamp', None) else None
        }})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Update PriorityClass (cluster-scoped)
@bp_explorer.route('/k8s-explorer/update-priority-class', methods=['POST'])
def update_priority_class():
    try:
        data = request.get_json(force=True) or {}
        name = data.get('name')
        if not name:
            return jsonify({'error': 'name is required'}), 400

        # Optional fields
        value = data.get('value')
        global_default = data.get('global_default')
        preemption_policy = data.get('preemption_policy')
        description = data.get('description')

        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        scheduling_v1 = client.SchedulingV1Api()

        patch_body = {}

        # PriorityClass.spec.value field is immutable and cannot be updated
        if value not in (None, ''):
            return jsonify({'error': 'PriorityClass.value güncellenemez. Yeni bir PriorityClass oluşturun veya mevcut nesneyi silip yeniden yaratın.'}), 400

        # Only set globalDefault if provided and not empty string
        if global_default is not None and global_default != '':
            if isinstance(global_default, str):
                gd = global_default.strip().lower() in ['true', '1', 'yes', 'on']
            else:
                gd = bool(global_default)
            patch_body['globalDefault'] = gd

        # preemptionPolicy: empty string clears the field, None means no change
        if preemption_policy is not None:
            patch_body['preemptionPolicy'] = preemption_policy if preemption_policy != '' else None

        # description: empty string clears
        if description is not None:
            patch_body['description'] = description if description != '' else None

        if not patch_body:
            return jsonify({'error': 'nothing to update'}), 400

        scheduling_v1.patch_priority_class(name=name, body=patch_body)
        record_audit_event(
            action='update',
            resource_type='PriorityClass',
            resource_name=name,
            namespace=None,
            session_id=_short_session_id(request.cookies.get('session')),
        )
        return jsonify({'status': 'ok', 'name': name})
    except ApiException as e:
        try:
            return jsonify({'error': e.body}), e.status
        except Exception:
            return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Delete PriorityClass (cluster-scoped)
@bp_explorer.route('/k8s-explorer/delete-priority-class', methods=['POST'])
def delete_priority_class():
    try:
        data = request.get_json(force=True) or {}
        name = data.get('name')
        if not name:
            return jsonify({'error': 'name is required'}), 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        scheduling_v1 = client.SchedulingV1Api()
        scheduling_v1.delete_priority_class(name=name)
        record_audit_event(
            action='delete',
            resource_type='PriorityClass',
            resource_name=name,
            namespace=None,
            session_id=_short_session_id(request.cookies.get('session')),
        )
        return jsonify({'status': 'deleted', 'name': name})
    except ApiException as e:
        try:
            return jsonify({'error': e.body}), e.status
        except Exception:
            return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# RuntimeClasses summary endpoint (cluster-scoped)
@bp_explorer.route('/k8s-explorer/runtime-classes-summary')
def runtime_classes_summary():
    try:
        _ = request.args.get('namespace')  # ignored
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        co = client.CustomObjectsApi()
        objs = co.list_cluster_custom_object(group="node.k8s.io", version="v1", plural="runtimeclasses")
        items = objs.get('items', [])
        result = []
        for rc in items:
            md = rc.get('metadata', {})
            spec = rc.get('spec', {})
            scheduling = spec.get('scheduling') or {}
            overhead = spec.get('overhead') or {}
            result.append({
                'name': md.get('name'),
                'handler': spec.get('handler'),
                'scheduling': {
                    'node_selector': scheduling.get('nodeSelector'),
                    'tolerations': scheduling.get('tolerations'),
                },
                'overhead': overhead,
                'creation_timestamp': md.get('creationTimestamp')
            })
        return jsonify({'runtime_classes': result})
    except Exception as e:
        return jsonify({'runtime_classes': [], 'error': str(e)})


# Get a single RuntimeClass details (cluster-scoped)
@bp_explorer.route('/k8s-explorer/runtime-class')
def get_runtime_class():
    try:
        name = request.args.get('name')
        if not name:
            return jsonify({'error': 'name is required'}), 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        co = client.CustomObjectsApi()
        rc = co.get_cluster_custom_object(group="node.k8s.io", version="v1", plural="runtimeclasses", name=name)
        md = rc.get('metadata', {})
        spec = rc.get('spec', {})
        scheduling = spec.get('scheduling') or {}
        overhead = spec.get('overhead') or {}
        return jsonify({'runtime_class': {
            'name': md.get('name'),
            'handler': spec.get('handler'),
            'scheduling': {
                'node_selector': scheduling.get('nodeSelector'),
                'tolerations': scheduling.get('tolerations'),
            },
            'overhead': overhead,
            'creation_timestamp': md.get('creationTimestamp')
        }})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Update RuntimeClass (cluster-scoped)
@bp_explorer.route('/k8s-explorer/update-runtime-class', methods=['POST'])
def update_runtime_class():
    try:
        data = request.get_json(force=True) or {}
        name = data.get('name')
        if not name:
            return jsonify({'error': 'name is required'}), 400

        # Handler genelde değiştirilmeyen bir alandır; güvenli tarafta kalarak reddedelim
        if 'handler' in data and data.get('handler') not in (None, ''):
            return jsonify({'error': 'RuntimeClass.handler güncellenemez. Gerekirse yeni bir RuntimeClass oluşturun.'}), 400

        node_selector_str = data.get('node_selector')  # e.g. "k=v,k2=v2"
        tolerations_json = data.get('tolerations')     # array or JSON string
        overhead_json = data.get('overhead')           # dict or JSON string

        # Build patch
        patch_spec = {}
        sched = {}

        # nodeSelector parse
        if node_selector_str is not None:
            if node_selector_str == '':
                sched['nodeSelector'] = None
            else:
                try:
                    node_selector = {}
                    for pair in [p.strip() for p in node_selector_str.split(',') if p.strip()]:
                        if '=' in pair:
                            k, v = pair.split('=', 1)
                            node_selector[k.strip()] = v.strip()
                        else:
                            return jsonify({'error': f'Geçersiz nodeSelector girdisi: {pair} (k=v formatı)'}), 400
                    sched['nodeSelector'] = node_selector
                except Exception as pe:
                    return jsonify({'error': f'nodeSelector parse hatası: {pe}'}), 400

        # tolerations parse
        if tolerations_json is not None:
            if isinstance(tolerations_json, str):
                if tolerations_json.strip() == '':
                    sched['tolerations'] = None
                else:
                    try:
                        parsed = json.loads(tolerations_json)
                        if not isinstance(parsed, list):
                            return jsonify({'error': 'tolerations JSON bir dizi olmalı'}), 400
                        sched['tolerations'] = parsed
                    except Exception as je:
                        return jsonify({'error': f'tolerations JSON hatası: {je}'}), 400
            else:
                # assume array or None
                if tolerations_json == '':
                    sched['tolerations'] = None
                else:
                    sched['tolerations'] = tolerations_json

        if sched:
            patch_spec['scheduling'] = sched

        # overhead parse
        if overhead_json is not None:
            if isinstance(overhead_json, str):
                if overhead_json.strip() == '':
                    patch_spec['overhead'] = None
                else:
                    try:
                        parsed = json.loads(overhead_json)
                        if not isinstance(parsed, dict):
                            return jsonify({'error': 'overhead JSON bir nesne olmalı'}), 400
                        patch_spec['overhead'] = parsed
                    except Exception as je:
                        return jsonify({'error': f'overhead JSON hatası: {je}'}), 400
            else:
                if overhead_json == '':
                    patch_spec['overhead'] = None
                else:
                    patch_spec['overhead'] = overhead_json

        if not patch_spec:
            return jsonify({'error': 'nothing to update'}), 400

        patch_body = { 'spec': patch_spec }

        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        co = client.CustomObjectsApi()
        co.patch_cluster_custom_object(group="node.k8s.io", version="v1", plural="runtimeclasses", name=name, body=patch_body)
        record_audit_event(
            action='update',
            resource_type='RuntimeClass',
            resource_name=name,
            namespace=None,
            session_id=_short_session_id(request.cookies.get('session')),
        )
        return jsonify({'status': 'ok', 'name': name})
    except ApiException as e:
        try:
            return jsonify({'error': e.body}), e.status
        except Exception:
            return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Delete RuntimeClass (cluster-scoped)
@bp_explorer.route('/k8s-explorer/delete-runtime-class', methods=['POST'])
def delete_runtime_class():
    try:
        data = request.get_json(force=True) or {}
        name = data.get('name')
        if not name:
            return jsonify({'error': 'name is required'}), 400
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        co = client.CustomObjectsApi()
        co.delete_cluster_custom_object(group="node.k8s.io", version="v1", plural="runtimeclasses", name=name)
        record_audit_event(
            action='delete',
            resource_type='RuntimeClass',
            resource_name=name,
            namespace=None,
            session_id=_short_session_id(request.cookies.get('session')),
        )
        return jsonify({'status': 'deleted', 'name': name})
    except ApiException as e:
        try:
            return jsonify({'error': e.body}), e.status
        except Exception:
            return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Leases summary endpoint (namespaced)
@bp_explorer.route('/k8s-explorer/leases-summary')
def leases_summary():
    try:
        namespace = request.args.get('namespace')
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        coord_v1 = client.CoordinationV1Api()
        if namespace and namespace not in ('all', None):
            leases = coord_v1.list_namespaced_lease(namespace).items
        else:
            leases = coord_v1.list_lease_for_all_namespaces().items
        def dt_to_iso(x):
            try:
                return x.isoformat() if getattr(x, 'isoformat', None) else (str(x) if x else None)
            except Exception:
                return None
        result = []
        for le in leases:
            md = le.metadata
            spec = getattr(le, 'spec', None)
            result.append({
                'namespace': getattr(md, 'namespace', None),
                'name': getattr(md, 'name', None),
                'holder_identity': getattr(spec, 'holder_identity', None) if spec else None,
                'lease_duration_seconds': getattr(spec, 'lease_duration_seconds', None) if spec else None,
                'acquire_time': dt_to_iso(getattr(spec, 'acquire_time', None)) if spec else None,
                'renew_time': dt_to_iso(getattr(spec, 'renew_time', None)) if spec else None,
                'lease_transitions': getattr(spec, 'lease_transitions', None) if spec else None,
                'creation_timestamp': md.creation_timestamp.isoformat() if getattr(md, 'creation_timestamp', None) else None
            })
        return jsonify({'leases': result})
    except Exception as e:
        return jsonify({'leases': [], 'error': str(e)})


# Mutating Webhooks summary (cluster-scoped; optional namespace filter by service namespace)
@bp_explorer.route('/k8s-explorer/mutating-webhooks-summary')
def mutating_webhooks_summary():
    try:
        namespace = request.args.get('namespace')
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        ar = client.AdmissionregistrationV1Api()
        items = ar.list_mutating_webhook_configuration().items
        result = []
        for cfg in items:
            md = cfg.metadata
            webhooks = getattr(cfg, 'webhooks', []) or []
            services = []
            rules_count = 0
            failure_policies = set()
            for wh in webhooks:
                cc = getattr(wh, 'client_config', None)
                svc = getattr(cc, 'service', None) if cc else None
                if svc:
                    services.append({
                        'namespace': getattr(svc, 'namespace', None),
                        'name': getattr(svc, 'name', None),
                        'path': getattr(svc, 'path', None),
                        'port': getattr(svc, 'port', None),
                    })
                rules = getattr(wh, 'rules', None) or []
                rules_count += len(rules)
                if getattr(wh, 'failure_policy', None):
                    failure_policies.add(wh.failure_policy)
            if namespace and namespace not in ('all', None):
                if not any(s.get('namespace') == namespace for s in services):
                    continue
            result.append({
                'name': getattr(md, 'name', None),
                'webhooks_count': len(webhooks),
                'services': services,
                'rules_count': rules_count,
                'failure_policy': ','.join(sorted(failure_policies)) if failure_policies else None,
                'creation_timestamp': md.creation_timestamp.isoformat() if getattr(md, 'creation_timestamp', None) else None
            })
        return jsonify({'mutating_webhooks': result})
    except Exception as e:
        return jsonify({'mutating_webhooks': [], 'error': str(e)})


# Validating Webhooks summary (cluster-scoped; optional namespace filter by service namespace)
@bp_explorer.route('/k8s-explorer/validating-webhooks-summary')
def validating_webhooks_summary():
    try:
        namespace = request.args.get('namespace')
        load_kube_config_active()
        c = client.Configuration.get_default_copy()
        c.verify_ssl = False
        c.assert_hostname = False
        client.Configuration.set_default(c)
        ar = client.AdmissionregistrationV1Api()
        items = ar.list_validating_webhook_configuration().items
        result = []
        for cfg in items:
            md = cfg.metadata
            webhooks = getattr(cfg, 'webhooks', []) or []
            services = []
            rules_count = 0
            failure_policies = set()
            for wh in webhooks:
                cc = getattr(wh, 'client_config', None)
                svc = getattr(cc, 'service', None) if cc else None
                if svc:
                    services.append({
                        'namespace': getattr(svc, 'namespace', None),
                        'name': getattr(svc, 'name', None),
                        'path': getattr(svc, 'path', None),
                        'port': getattr(svc, 'port', None),
                    })
                rules = getattr(wh, 'rules', None) or []
                rules_count += len(rules)
                if getattr(wh, 'failure_policy', None):
                    failure_policies.add(wh.failure_policy)
            if namespace and namespace not in ('all', None):
                if not any(s.get('namespace') == namespace for s in services):
                    continue
            result.append({
                'name': getattr(md, 'name', None),
                'webhooks_count': len(webhooks),
                'services': services,
                'rules_count': rules_count,
                'failure_policy': ','.join(sorted(failure_policies)) if failure_policies else None,
                'creation_timestamp': md.creation_timestamp.isoformat() if getattr(md, 'creation_timestamp', None) else None
            })
        return jsonify({'validating_webhooks': result})
    except Exception as e:
        return jsonify({'validating_webhooks': [], 'error': str(e)})
