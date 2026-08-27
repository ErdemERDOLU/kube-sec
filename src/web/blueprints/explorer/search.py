"""explorer/search.py — Global kaynak arama endpoint'i.

İçerik: global-search (GET /k8s-explorer/global-search)

Backlog #20, Faz 2: Global Kaynak Arama.
"""

from __future__ import annotations

from flask import jsonify, request
from kubernetes import client
from kubernetes.client.rest import ApiException

from web.kubeconfig_manager import configure_kube_client
from web.blueprints.explorer import bp_explorer
from web.validators import validate_k8s_namespace

# Her kaynak türü için hedef URL (frontend navigasyonu için)
_RESOURCE_URLS = {
    "pod":         "/workloads#pods",
    "deployment":  "/workloads#deployments",
    "statefulset": "/workloads#statefulsets",
    "daemonset":   "/workloads#daemonsets",
    "service":     "/network#services",
}

# Tür başına maksimum izin verilen limit
_MAX_LIMIT = 100
_DEFAULT_LIMIT = 50


def _search_resource(fetch_fn, resource_type: str, query: str, limit: int) -> tuple[list, str | None]:
    """Tek bir Kubernetes kaynak türü üzerinde isim bazlı arama yapar.

    Args:
        fetch_fn: Parametresiz çağrılabilir; Kubernetes kaynak listesi döner.
        resource_type: Sonuç objesindeki 'type' alanı (örn. 'pod').
        query: Küçük harfe çevrilmiş arama terimi.
        limit: Bu tür için maksimum sonuç sayısı.

    Returns:
        (sonuç listesi, hata mesajı veya None)
    """
    results: list = []
    error: str | None = None
    try:
        items = fetch_fn()
        url = _RESOURCE_URLS.get(resource_type, "/workloads")
        count = 0
        for item in items:
            if count >= limit:
                break
            name: str = item.metadata.name or ""
            if query in name.lower():
                results.append({
                    "type":      resource_type,
                    "name":      name,
                    "namespace": item.metadata.namespace or "",
                    "url":       url,
                })
                count += 1
    except ApiException as exc:
        error = f"{resource_type}: Kubernetes API hatası {exc.status} — {exc.reason}"
    except Exception as exc:  # noqa: BLE001
        error = f"{resource_type}: {exc}"
    return results, error


@bp_explorer.route('/k8s-explorer/global-search')
def global_search():
    """Küme kaynaklarında ad bazlı global arama yapar.

    ---
    tags:
      - search
    parameters:
      - name: q
        in: query
        type: string
        required: true
        description: Arama terimi (minimum 2 karakter).
      - name: ns
        in: query
        type: string
        required: false
        description: Namespace filtresi. Boş = tüm namespace'ler.
      - name: limit
        in: query
        type: integer
        required: false
        default: 50
        description: Tür başına maksimum sonuç sayısı (max 100).
    responses:
      200:
        description: Arama sonuçları
        schema:
          type: object
          properties:
            query:
              type: string
            namespace:
              type: string
            results:
              type: array
              items:
                type: object
                properties:
                  type:
                    type: string
                  name:
                    type: string
                  namespace:
                    type: string
                  url:
                    type: string
            total:
              type: integer
            truncated:
              type: boolean
            errors:
              type: array
              items:
                type: string
      400:
        description: Geçersiz istek — q parametresi eksik veya çok kısa.
    """
    # ----- Input doğrulama -----
    query_raw: str = request.args.get("q", "").strip()
    if len(query_raw) < 2:
        return jsonify({
            "error": {
                "code": "QUERY_TOO_SHORT",
                "message": "q parametresi zorunludur ve en az 2 karakter içermelidir.",
                "details": {"q": query_raw or None},
            }
        }), 400

    ns: str = request.args.get("ns", "").strip()
    if ns and not validate_k8s_namespace(ns):
        return jsonify({
            "error": {
                "code": "INVALID_NAMESPACE",
                "message": "ns parametresi gecerli bir Kubernetes namespace adi olmalidir.",
                "details": {"ns": ns},
            }
        }), 400

    raw_limit = request.args.get("limit", str(_DEFAULT_LIMIT))
    try:
        limit = int(raw_limit)
        if limit < 1:
            raise ValueError
        if limit > _MAX_LIMIT:
            limit = _MAX_LIMIT
    except ValueError:
        return jsonify({
            "error": {
                "code": "INVALID_LIMIT",
                "message": f"limit sayısal ve 1-{_MAX_LIMIT} arasında olmalıdır.",
                "details": {"limit": raw_limit},
            }
        }), 400

    # ----- Kubeconfig yükle -----
    try:
        configure_kube_client()
    except Exception as exc:
        return jsonify({
            "error": {
                "code": "KUBECONFIG_ERROR",
                "message": "Aktif kubeconfig yüklenemedi.",
                "details": {"reason": str(exc)},
            }
        }), 500

    # ----- API istemcileri -----
    core_v1 = client.CoreV1Api()
    apps_v1 = client.AppsV1Api()
    query = query_raw.lower()

    # Her kaynak türü için (tür_adı, fetch_fn) çifti
    if ns:
        resource_fetchers = [
            ("pod",         lambda: core_v1.list_namespaced_pod(ns).items),
            ("deployment",  lambda: apps_v1.list_namespaced_deployment(ns).items),
            ("statefulset", lambda: apps_v1.list_namespaced_stateful_set(ns).items),
            ("daemonset",   lambda: apps_v1.list_namespaced_daemon_set(ns).items),
            ("service",     lambda: core_v1.list_namespaced_service(ns).items),
        ]
    else:
        resource_fetchers = [
            ("pod",         lambda: core_v1.list_pod_for_all_namespaces().items),
            ("deployment",  lambda: apps_v1.list_deployment_for_all_namespaces().items),
            ("statefulset", lambda: apps_v1.list_stateful_set_for_all_namespaces().items),
            ("daemonset",   lambda: apps_v1.list_daemon_set_for_all_namespaces().items),
            ("service",     lambda: core_v1.list_service_for_all_namespaces().items),
        ]

    # ----- Arama — her tür bağımsız olarak çalışır; biri hata verirse diğerleri engellenmez -----
    all_results: list = []
    errors: list = []
    truncated = False

    for resource_type, fetch_fn in resource_fetchers:
        partial, err = _search_resource(fetch_fn, resource_type, query, limit)
        if err:
            errors.append(err)
        all_results.extend(partial)
        if len(partial) >= limit:
            truncated = True

    # Sonuçları tür adına göre (spec: türe göre gruplanmış), sonra isme göre sırala
    all_results.sort(key=lambda r: (r["type"], r["name"]))

    return jsonify({
        "query":     query_raw,
        "namespace": ns or None,
        "results":   all_results,
        "total":     len(all_results),
        "truncated": truncated,
        "errors":    errors,
    })
