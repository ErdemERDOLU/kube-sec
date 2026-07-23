"""explorer/storage.py — Depolama kaynak route'ları.

İçerik: pvcs-summary, pvc-details, pvs-summary, pv-details,
storage-classes-summary, storage-class-details.
"""

from flask import jsonify, request
from kubernetes import client

from web.kubeconfig_manager import configure_kube_client

from web.blueprints.explorer import bp_explorer


# --- Storage summaries ---
@bp_explorer.route('/k8s-explorer/pvcs-summary')
def pvcs_summary():
    try:
        namespace = request.args.get('namespace')
        configure_kube_client()
        v1 = client.CoreV1Api()
        if namespace and namespace != 'all':
            items = v1.list_namespaced_persistent_volume_claim(namespace).items
        else:
            items = v1.list_persistent_volume_claim_for_all_namespaces().items
        result = []
        for pvc in items:
            spec = pvc.spec
            status = pvc.status
            result.append({
                'namespace': pvc.metadata.namespace,
                'name': pvc.metadata.name,
                'status': getattr(status, 'phase', None),
                'volume': getattr(spec, 'volume_name', None) if spec else None,
                'storage_class': getattr(spec, 'storage_class_name', None) or getattr(spec, 'storage_class', None),
                'access_modes': getattr(spec, 'access_modes', None) if spec else None,
                'capacity': getattr(getattr(status, 'capacity', None) or {}, 'get', lambda k, d=None: None)('storage', None) if status else None,
                'creation_timestamp': pvc.metadata.creation_timestamp.isoformat() if getattr(pvc.metadata, 'creation_timestamp', None) else None
            })
        return jsonify({'pvcs': result})
    except Exception as e:
        return jsonify({'pvcs': [], 'error': str(e)})


@bp_explorer.route('/k8s-explorer/pvs-summary')
def pvs_summary():
    try:
        configure_kube_client()
        v1 = client.CoreV1Api()
        items = v1.list_persistent_volume().items
        result = []
        for pv in items:
            spec = pv.spec
            status = pv.status
            claim_ref = getattr(spec, 'claim_ref', None)
            claim = f"{getattr(claim_ref,'namespace',None)}/{getattr(claim_ref,'name',None)}" if claim_ref else None
            cap = getattr(getattr(status, 'capacity', None) or {}, 'get', lambda k, d=None: None)('storage', None) if status else None
            result.append({
                'name': pv.metadata.name,
                'capacity': cap,
                'access_modes': getattr(spec, 'access_modes', None) if spec else None,
                'reclaim_policy': getattr(spec, 'persistent_volume_reclaim_policy', None) if spec else None,
                'storage_class': getattr(spec, 'storage_class_name', None) or getattr(spec, 'storage_class', None),
                'status': getattr(status, 'phase', None),
                'claim': claim,
                'creation_timestamp': pv.metadata.creation_timestamp.isoformat() if getattr(pv.metadata, 'creation_timestamp', None) else None
            })
        return jsonify({'pvs': result})
    except Exception as e:
        return jsonify({'pvs': [], 'error': str(e)})


@bp_explorer.route('/k8s-explorer/storage-classes-summary')
def storage_classes_summary():
    try:
        configure_kube_client()
        storage_v1 = client.StorageV1Api()
        items = storage_v1.list_storage_class().items
        result = []
        for sc in items:
            allow_expansion = getattr(sc.allow_volume_expansion, 'value', None) if hasattr(sc, 'allow_volume_expansion') else getattr(sc, 'allow_volume_expansion', None)
            result.append({
                'name': sc.metadata.name,
                'provisioner': getattr(sc, 'provisioner', None),
                'reclaim_policy': getattr(sc, 'reclaim_policy', None),
                'volume_binding_mode': getattr(sc, 'volume_binding_mode', None),
                'allow_expansion': allow_expansion,
                'creation_timestamp': sc.metadata.creation_timestamp.isoformat() if getattr(sc.metadata, 'creation_timestamp', None) else None
            })
        return jsonify({'storage_classes': result})
    except Exception as e:
        return jsonify({'storage_classes': [], 'error': str(e)})


# --- Storage detail endpoints ---
@bp_explorer.route('/k8s-explorer/pvc-details')
def pvc_details():
    try:
        name = request.args.get('name')
        namespace = request.args.get('namespace')
        if not name or not namespace:
            return jsonify({'error': 'name ve namespace zorunlu'}), 400
        configure_kube_client()
        v1 = client.CoreV1Api()
        pvc = v1.read_namespaced_persistent_volume_claim(name, namespace)
        md = pvc.metadata; spec = pvc.spec; status = pvc.status
        return jsonify({'pvc': {
            'name': getattr(md,'name',None),
            'namespace': getattr(md,'namespace',None),
            'labels': getattr(md,'labels',{}) or {},
            'annotations': getattr(md,'annotations',{}) or {},
            'creation_timestamp': getattr(md,'creation_timestamp',None).isoformat() if getattr(md,'creation_timestamp',None) else None,
            'volume': getattr(spec,'volume_name',None) if spec else None,
            'access_modes': getattr(spec,'access_modes',None) if spec else None,
            'resources': getattr(spec,'resources',None).to_dict() if getattr(spec,'resources',None) else None,
            'storage_class': getattr(spec,'storage_class_name',None) or getattr(spec,'storage_class',None),
            'status': getattr(status,'phase',None) if status else None,
            'capacity': getattr(getattr(status,'capacity',None) or {},'get',lambda k,d=None:None)('storage',None) if status else None
        }})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp_explorer.route('/k8s-explorer/pv-details')
def pv_details():
    try:
        name = request.args.get('name')
        if not name:
            return jsonify({'error': 'name zorunlu'}), 400
        configure_kube_client()
        v1 = client.CoreV1Api()
        pv = v1.read_persistent_volume(name)
        md = pv.metadata; spec = pv.spec; status = pv.status
        claim_ref = getattr(spec,'claim_ref',None)
        claim = f"{getattr(claim_ref,'namespace',None)}/{getattr(claim_ref,'name',None)}" if claim_ref else None
        return jsonify({'pv': {
            'name': getattr(md,'name',None),
            'labels': getattr(md,'labels',{}) or {},
            'annotations': getattr(md,'annotations',{}) or {},
            'creation_timestamp': getattr(md,'creation_timestamp',None).isoformat() if getattr(md,'creation_timestamp',None) else None,
            'capacity': getattr(getattr(status,'capacity',None) or {},'get',lambda k,d=None:None)('storage',None) if status else None,
            'access_modes': getattr(spec,'access_modes',None) if spec else None,
            'reclaim_policy': getattr(spec,'persistent_volume_reclaim_policy',None) if spec else None,
            'storage_class': getattr(spec,'storage_class_name',None) or getattr(spec,'storage_class',None),
            'status': getattr(status,'phase',None) if status else None,
            'claim': claim,
            'volume_mode': getattr(spec,'volume_mode',None) if spec else None,
            'node_affinity': getattr(getattr(spec,'node_affinity',None),'to_dict',lambda:None)()
        }})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp_explorer.route('/k8s-explorer/storage-class-details')
def storage_class_details():
    try:
        name = request.args.get('name')
        if not name:
            return jsonify({'error': 'name zorunlu'}), 400
        configure_kube_client()
        storage_v1 = client.StorageV1Api()
        sc = storage_v1.read_storage_class(name)
        md = sc.metadata
        return jsonify({'storage_class': {
            'name': getattr(md,'name',None),
            'labels': getattr(md,'labels',{}) or {},
            'annotations': getattr(md,'annotations',{}) or {},
            'creation_timestamp': getattr(md,'creation_timestamp',None).isoformat() if getattr(md,'creation_timestamp',None) else None,
            'provisioner': getattr(sc,'provisioner',None),
            'reclaim_policy': getattr(sc,'reclaim_policy',None),
            'volume_binding_mode': getattr(sc,'volume_binding_mode',None),
            'allow_expansion': getattr(sc,'allow_volume_expansion',None)
        }})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
