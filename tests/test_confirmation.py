"""tests/test_confirmation.py — Sunucu tarafi onay mekanizmasi testleri (AC-10).

Backlog #26: Yikici Kubernetes islemleri icin confirm_name / confirm_names
zorunlulugu. Her test sinifi en az 3 senaryo kapsar:
  1. confirm_name OLMADAN -> HTTP 400
  2. confirm_name YANLIS degerle -> HTTP 400
  3. confirm_name DOGRU degerle -> HTTP 400 DEGIL
     (K8s baglantisindan dolayi 500 beklenir, ama 400 degil)

CSRF conftest.py tarafindan WTF_CSRF_ENABLED=False ile devre disi birakilir.
Calistirmak icin:
    cd /Users/erdemerdolu/Desktop/kube-sec
    .venv/bin/python -m pytest tests/test_confirmation.py -v
"""

import json
import pytest


# =============================================================================
# node-drain — confirm_name, name_field='node' (AC-2)
# =============================================================================

class TestNodeDrainConfirmName:
    """node-drain endpoint'inde confirm_name zorunlulugunu dogrular."""

    ENDPOINT = '/k8s-explorer/node-drain'

    def test_missing_confirm_name_returns_400(self, client):
        """confirm_name olmadan POST -> HTTP 400 (AC-10, test 1)."""
        resp = client.post(
            self.ENDPOINT,
            data=json.dumps({'node': 'worker-1'}),
            content_type='application/json',
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body is not None, "Yanit JSON olmali"
        assert 'confirm_name' in body.get('error', ''), (
            "Hata mesajinda 'confirm_name' gecmeli (AC-7)"
        )

    def test_wrong_confirm_name_returns_400(self, client):
        """confirm_name yanlis degerle POST -> HTTP 400 (AC-10, test 2)."""
        resp = client.post(
            self.ENDPOINT,
            data=json.dumps({'node': 'worker-1', 'confirm_name': 'wrong-node'}),
            content_type='application/json',
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body is not None
        assert 'confirm_name' in body.get('error', '')

    def test_correct_confirm_name_does_not_return_400(self, client):
        """confirm_name dogru degerle POST -> 400 DEGIL (AC-10, test 3).

        K8s baglantisindan dolayi 500 beklenir; onay mekanizmasinin engeli
        degil, K8s hatasi oldugu dogrulanir.
        """
        resp = client.post(
            self.ENDPOINT,
            data=json.dumps({'node': 'worker-1', 'confirm_name': 'worker-1'}),
            content_type='application/json',
        )
        assert resp.status_code != 400, (
            f"Dogru confirm_name ile 400 donmemeli, alinan kod: {resp.status_code}"
        )

    def test_case_sensitive_confirm_name_returns_400(self, client):
        """confirm_name buyuk/kucuk harf duyarli eslestirme (AC-12)."""
        resp = client.post(
            self.ENDPOINT,
            data=json.dumps({'node': 'worker-1', 'confirm_name': 'Worker-1'}),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_error_response_is_json(self, client):
        """400 yaniti Content-Type: application/json olmali (AC-7)."""
        resp = client.post(
            self.ENDPOINT,
            data=json.dumps({'node': 'worker-1'}),
            content_type='application/json',
        )
        assert resp.status_code == 400
        assert 'application/json' in resp.content_type


# =============================================================================
# node-cordon / node-uncordon — confirm_name, name_field='node' (AC-1)
# =============================================================================

class TestNodeCordonConfirmName:
    """node-cordon endpoint'inde confirm_name zorunlulugunu dogrular (AC-1)."""

    def test_cordon_missing_confirm_name_returns_400(self, client):
        resp = client.post(
            '/k8s-explorer/node-cordon',
            data=json.dumps({'node': 'worker-2'}),
            content_type='application/json',
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert 'confirm_name' in body.get('error', '')

    def test_uncordon_missing_confirm_name_returns_400(self, client):
        resp = client.post(
            '/k8s-explorer/node-uncordon',
            data=json.dumps({'node': 'worker-2'}),
            content_type='application/json',
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert 'confirm_name' in body.get('error', '')

    def test_cordon_correct_confirm_name_not_400(self, client):
        resp = client.post(
            '/k8s-explorer/node-cordon',
            data=json.dumps({'node': 'worker-2', 'confirm_name': 'worker-2'}),
            content_type='application/json',
        )
        assert resp.status_code != 400


# =============================================================================
# delete-priority-class / delete-runtime-class (AC-1)
# =============================================================================

class TestDeleteClusterScopedConfirmName:
    """delete-priority-class ve delete-runtime-class icin confirm_name dogrular."""

    def test_delete_priority_class_missing_confirm_name_returns_400(self, client):
        resp = client.post(
            '/k8s-explorer/delete-priority-class',
            data=json.dumps({'name': 'high-priority'}),
            content_type='application/json',
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert 'confirm_name' in body.get('error', '')

    def test_delete_priority_class_wrong_confirm_name_returns_400(self, client):
        resp = client.post(
            '/k8s-explorer/delete-priority-class',
            data=json.dumps({'name': 'high-priority', 'confirm_name': 'wrong'}),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_delete_priority_class_correct_confirm_name_not_400(self, client):
        resp = client.post(
            '/k8s-explorer/delete-priority-class',
            data=json.dumps({'name': 'high-priority', 'confirm_name': 'high-priority'}),
            content_type='application/json',
        )
        assert resp.status_code != 400

    def test_delete_runtime_class_missing_confirm_name_returns_400(self, client):
        resp = client.post(
            '/k8s-explorer/delete-runtime-class',
            data=json.dumps({'name': 'gvisor'}),
            content_type='application/json',
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert 'confirm_name' in body.get('error', '')

    def test_delete_runtime_class_correct_confirm_name_not_400(self, client):
        resp = client.post(
            '/k8s-explorer/delete-runtime-class',
            data=json.dumps({'name': 'gvisor', 'confirm_name': 'gvisor'}),
            content_type='application/json',
        )
        assert resp.status_code != 400


# =============================================================================
# generic delete (POST) — core.py (AC-1)
# =============================================================================

class TestGenericDeleteConfirmName:
    """POST /k8s-explorer/delete icin confirm_name dogrular."""

    def test_missing_confirm_name_returns_400(self, client):
        resp = client.post(
            '/k8s-explorer/delete',
            data=json.dumps({'type': 'pod', 'name': 'my-pod', 'namespace': 'default'}),
            content_type='application/json',
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert 'confirm_name' in body.get('error', '')

    def test_wrong_confirm_name_returns_400(self, client):
        resp = client.post(
            '/k8s-explorer/delete',
            data=json.dumps({'type': 'pod', 'name': 'my-pod', 'namespace': 'default', 'confirm_name': 'other-pod'}),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_correct_confirm_name_not_400(self, client):
        resp = client.post(
            '/k8s-explorer/delete',
            data=json.dumps({'type': 'pod', 'name': 'my-pod', 'namespace': 'default', 'confirm_name': 'my-pod'}),
            content_type='application/json',
        )
        assert resp.status_code != 400

    def test_delete_method_query_string_confirm_name(self, client):
        """DELETE metodu icin confirm_name query string'den de kabul edilir (Acik Soru #1)."""
        resp = client.delete(
            '/k8s-explorer/delete?type=pod&name=my-pod&namespace=default&confirm_name=my-pod',
        )
        assert resp.status_code != 400

    def test_delete_method_missing_confirm_name_returns_400(self, client):
        """DELETE metodu, confirm_name yoksa 400 donmeli."""
        resp = client.delete(
            '/k8s-explorer/delete?type=pod&name=my-pod&namespace=default',
        )
        assert resp.status_code == 400


# =============================================================================
# delete-secret (AC-1)
# =============================================================================

class TestDeleteSecretConfirmName:
    """delete-secret icin confirm_name dogrular."""

    def test_missing_confirm_name_returns_400(self, client):
        resp = client.post(
            '/k8s-explorer/delete-secret',
            data=json.dumps({'name': 'my-secret', 'namespace': 'default'}),
            content_type='application/json',
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert 'confirm_name' in body.get('error', '')

    def test_wrong_confirm_name_returns_400(self, client):
        resp = client.post(
            '/k8s-explorer/delete-secret',
            data=json.dumps({'name': 'my-secret', 'namespace': 'default', 'confirm_name': 'other'}),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_correct_confirm_name_not_400(self, client):
        resp = client.post(
            '/k8s-explorer/delete-secret',
            data=json.dumps({'name': 'my-secret', 'namespace': 'default', 'confirm_name': 'my-secret'}),
            content_type='application/json',
        )
        assert resp.status_code != 400


# =============================================================================
# delete-hpa / delete-pdb (AC-1)
# =============================================================================

class TestDeleteScalingConfirmName:
    """delete-hpa ve delete-pdb icin confirm_name dogrular."""

    def test_delete_hpa_missing_confirm_name_returns_400(self, client):
        resp = client.post(
            '/k8s-explorer/delete-hpa',
            data=json.dumps({'name': 'my-hpa', 'namespace': 'default'}),
            content_type='application/json',
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert 'confirm_name' in body.get('error', '')

    def test_delete_hpa_correct_confirm_name_not_400(self, client):
        resp = client.post(
            '/k8s-explorer/delete-hpa',
            data=json.dumps({'name': 'my-hpa', 'namespace': 'default', 'confirm_name': 'my-hpa'}),
            content_type='application/json',
        )
        assert resp.status_code != 400

    def test_delete_pdb_missing_confirm_name_returns_400(self, client):
        resp = client.post(
            '/k8s-explorer/delete-pdb',
            data=json.dumps({'name': 'my-pdb', 'namespace': 'default'}),
            content_type='application/json',
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert 'confirm_name' in body.get('error', '')

    def test_delete_pdb_correct_confirm_name_not_400(self, client):
        resp = client.post(
            '/k8s-explorer/delete-pdb',
            data=json.dumps({'name': 'my-pdb', 'namespace': 'default', 'confirm_name': 'my-pdb'}),
            content_type='application/json',
        )
        assert resp.status_code != 400


# =============================================================================
# restart-pod / restart-deployment / restart-statefulset / restart-daemonset (AC-3)
# =============================================================================

class TestRestartConfirmName:
    """Restart endpoint'lerinde confirm_name zorunlulugunu dogrular (AC-3)."""

    @pytest.mark.parametrize('endpoint', [
        '/k8s-explorer/restart-pod',
        '/k8s-explorer/restart-deployment',
        '/k8s-explorer/restart-statefulset',
        '/k8s-explorer/restart-daemonset',
    ])
    def test_missing_confirm_name_returns_400(self, client, endpoint):
        """confirm_name olmadan POST -> HTTP 400 (AC-10, test 1)."""
        resp = client.post(
            endpoint,
            data=json.dumps({'name': 'my-resource', 'namespace': 'default'}),
            content_type='application/json',
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert 'confirm_name' in body.get('error', '')

    @pytest.mark.parametrize('endpoint', [
        '/k8s-explorer/restart-pod',
        '/k8s-explorer/restart-deployment',
        '/k8s-explorer/restart-statefulset',
        '/k8s-explorer/restart-daemonset',
    ])
    def test_wrong_confirm_name_returns_400(self, client, endpoint):
        """confirm_name yanlis degerle POST -> HTTP 400 (AC-10, test 2)."""
        resp = client.post(
            endpoint,
            data=json.dumps({'name': 'my-resource', 'namespace': 'default', 'confirm_name': 'wrong'}),
            content_type='application/json',
        )
        assert resp.status_code == 400

    @pytest.mark.parametrize('endpoint', [
        '/k8s-explorer/restart-pod',
        '/k8s-explorer/restart-deployment',
        '/k8s-explorer/restart-statefulset',
        '/k8s-explorer/restart-daemonset',
    ])
    def test_correct_confirm_name_not_400(self, client, endpoint):
        """confirm_name dogru degerle POST -> 400 DEGIL (AC-10, test 3)."""
        resp = client.post(
            endpoint,
            data=json.dumps({'name': 'my-resource', 'namespace': 'default', 'confirm_name': 'my-resource'}),
            content_type='application/json',
        )
        assert resp.status_code != 400


# =============================================================================
# delete-replicasets — confirm_names (toplu) (AC-4)
# =============================================================================

class TestDeleteReplicaSetsConfirmNames:
    """delete-replicasets icin confirm_names (toplu) zorunlulugunu dogrular (AC-4)."""

    ENDPOINT = '/k8s-explorer/delete-replicasets'

    def test_missing_confirm_names_returns_400(self, client):
        """confirm_names olmadan POST -> HTTP 400 (AC-10, test 1)."""
        resp = client.post(
            self.ENDPOINT,
            data=json.dumps({'items': [{'namespace': 'default', 'name': 'rs-1'}]}),
            content_type='application/json',
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body is not None
        assert 'confirm_name' in body.get('error', '')

    def test_wrong_confirm_names_returns_400(self, client):
        """confirm_names yanlis liste ile POST -> HTTP 400 (AC-10, test 2)."""
        resp = client.post(
            self.ENDPOINT,
            data=json.dumps({
                'items': [{'namespace': 'default', 'name': 'rs-1'}],
                'confirm_names': ['rs-2'],
            }),
            content_type='application/json',
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert 'confirm_name' in body.get('error', '')

    def test_correct_confirm_names_not_400(self, client):
        """confirm_names dogru liste ile POST -> 400 DEGIL (AC-10, test 3)."""
        resp = client.post(
            self.ENDPOINT,
            data=json.dumps({
                'items': [{'namespace': 'default', 'name': 'rs-1'}],
                'confirm_names': ['rs-1'],
            }),
            content_type='application/json',
        )
        assert resp.status_code != 400

    def test_partial_confirm_names_returns_400(self, client):
        """Eksik eleman iceren confirm_names -> HTTP 400."""
        resp = client.post(
            self.ENDPOINT,
            data=json.dumps({
                'items': [
                    {'namespace': 'default', 'name': 'rs-1'},
                    {'namespace': 'default', 'name': 'rs-2'},
                ],
                'confirm_names': ['rs-1'],  # rs-2 eksik
            }),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_multi_item_correct_confirm_names_not_400(self, client):
        """Coklu item ile dogru confirm_names -> 400 DEGIL."""
        resp = client.post(
            self.ENDPOINT,
            data=json.dumps({
                'items': [
                    {'namespace': 'default', 'name': 'rs-1'},
                    {'namespace': 'default', 'name': 'rs-2'},
                ],
                'confirm_names': ['rs-2', 'rs-1'],  # siralama farklı, gecmeli
            }),
            content_type='application/json',
        )
        assert resp.status_code != 400

    def test_confirm_names_not_list_returns_400(self, client):
        """confirm_names string olarak gonderilirse -> HTTP 400."""
        resp = client.post(
            self.ENDPOINT,
            data=json.dumps({
                'items': [{'namespace': 'default', 'name': 'rs-1'}],
                'confirm_names': 'rs-1',  # string, list degil
            }),
            content_type='application/json',
        )
        assert resp.status_code == 400
