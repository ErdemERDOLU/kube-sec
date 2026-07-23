"""tests/test_health.py — /k8s-explorer/app-health ve /k8s-explorer/health endpoint testleri (AC-2).

src/web/blueprints/explorer/core.py içindeki health route'larını Flask test client
ile test eder. Kubernetes cluster bağlantısı unittest.mock.patch ile simüle edilir.
"""

from unittest.mock import patch


def test_app_health_returns_ok(client):
    """GET /k8s-explorer/app-health HTTP 200 döner; JSON'da status='ok' ve
    boş olmayan bir version string içerir. Kubeconfig gerekmez.
    """
    resp = client.get('/k8s-explorer/app-health')
    assert resp.status_code == 200

    data = resp.get_json()
    assert data is not None
    assert data.get('status') == 'ok'
    assert isinstance(data.get('version'), str)
    assert len(data['version']) > 0


def test_health_cluster_connection_failure_returns_ok_false(client):
    """GET /k8s-explorer/health, Kubernetes cluster'a ulaşılamadığında
    HTTP 200 döner; JSON'da ok=false ve boş olmayan bir error string içerir.

    configure_kube_client() mock'lanarak bağlantı hatası simüle edilir.
    """
    with patch(
        'web.blueprints.explorer.core.configure_kube_client',
        side_effect=Exception('simulated: no cluster available'),
    ):
        resp = client.get('/k8s-explorer/health')

    assert resp.status_code == 200

    data = resp.get_json()
    assert data is not None
    assert data.get('ok') is False
    assert isinstance(data.get('error'), str)
    assert len(data['error']) > 0


def test_app_health_response_content_type_is_json(client):
    """GET /k8s-explorer/app-health response Content-Type application/json olmalı (AC-12)."""
    resp = client.get('/k8s-explorer/app-health')
    assert resp.content_type.startswith('application/json')
