"""tests/test_logs_endpoint.py — /k8s-explorer/logs endpoint testleri (AC-1, AC-2, AC-3).

k8s_explorer_logs() fonksiyonunun davranışını doğrular:
  - container query parametresi read_namespaced_pod_log'a doğru iletiliyor mu (AC-1)
  - ApiException(status=400) → HTTP 400 dönüyor mu, 500 değil (AC-3)
  - ApiException(status=404) → HTTP 404 dönüyor mu, 500 değil (AC-3)
  - Genel Exception → JSON formatında HTTP 500 dönüyor mu (AC-3 tutarlılık)
  - Yanıtlar JSON formatında mı (AC-3)

Kubernetes cluster bağlantısı `unittest.mock.patch` ile simüle edilir;
gerçek cluster'a ağ çağrısı yapılmaz.
"""

from unittest.mock import MagicMock, patch

from kubernetes.client.rest import ApiException


# ---------------------------------------------------------------------------
# Yardımcı fonksiyon
# ---------------------------------------------------------------------------

def _make_api_exception(status: int, reason: str = "Test Error") -> ApiException:
    """Verilen HTTP status koduyla bir ApiException örneği oluşturur.

    Args:
        status: K8s API'nin döndürdüğü HTTP status kodu (örn. 400, 404).
        reason: Kısa hata açıklaması.

    Returns:
        body alanı dolu bir ApiException örneği.
    """
    exc = ApiException(status=status, reason=reason)
    exc.body = f'{{"message": "{reason}"}}'
    return exc


# ---------------------------------------------------------------------------
# AC-1: container query parametresi K8s API çağrısına iletiliyor mu?
# ---------------------------------------------------------------------------

class TestLogsContainerParameter:
    """AC-1: container query parametresi read_namespaced_pod_log'a iletiliyor mu?"""

    def test_with_container_param_passes_container_to_k8s(self, client):
        """container=mycontainer verildiğinde K8s API çağrısında container=mycontainer olmalı."""
        mock_core_v1 = MagicMock()
        mock_core_v1.read_namespaced_pod_log.return_value = "log line 1\nlog line 2"

        with patch('web.blueprints.explorer.core.configure_kube_client'), \
             patch('web.blueprints.explorer.core.client.CoreV1Api', return_value=mock_core_v1):
            resp = client.get(
                '/k8s-explorer/logs'
                '?type=pod&namespace=default&name=mypod&container=mycontainer'
            )

        assert resp.status_code == 200
        mock_core_v1.read_namespaced_pod_log.assert_called_once_with(
            name='mypod',
            namespace='default',
            container='mycontainer',
            tail_lines=500,
        )

    def test_without_container_param_omits_container_kwarg(self, client):
        """container parametresi verilmediğinde K8s API çağrısında 'container' kwarg olmamalı.

        Tek container'lı pod'larda K8s API container'ı otomatik seçer;
        bu davranışı bozmamak için container kwarg iletilmemelidir.
        """
        mock_core_v1 = MagicMock()
        mock_core_v1.read_namespaced_pod_log.return_value = "single container log"

        with patch('web.blueprints.explorer.core.configure_kube_client'), \
             patch('web.blueprints.explorer.core.client.CoreV1Api', return_value=mock_core_v1):
            resp = client.get(
                '/k8s-explorer/logs?type=pod&namespace=default&name=mypod'
            )

        assert resp.status_code == 200
        call_kwargs = mock_core_v1.read_namespaced_pod_log.call_args.kwargs
        assert 'container' not in call_kwargs

    def test_log_content_returned_as_plain_text(self, client):
        """Başarılı çağrıda log içeriği text/plain olarak dönmeli."""
        mock_core_v1 = MagicMock()
        mock_core_v1.read_namespaced_pod_log.return_value = "INFO starting up\nINFO ready"

        with patch('web.blueprints.explorer.core.configure_kube_client'), \
             patch('web.blueprints.explorer.core.client.CoreV1Api', return_value=mock_core_v1):
            resp = client.get(
                '/k8s-explorer/logs?type=pod&namespace=default&name=mypod&container=app'
            )

        assert resp.status_code == 200
        assert 'text/plain' in resp.content_type
        assert b'INFO starting up' in resp.data


# ---------------------------------------------------------------------------
# AC-3: ApiException ayrı yakalanıp doğru HTTP status kodu dönüyor mu?
# ---------------------------------------------------------------------------

class TestLogsApiExceptionHandling:
    """AC-3: ApiException ayrı yakalanıp K8s API'nin status kodu HTTP yanıtına yansıyor mu?"""

    def test_api_exception_400_returns_http_400(self, client):
        """K8s API 400 fırlattığında route HTTP 400 dönmeli (500 değil).

        Multi-container pod'da container belirtilmediğinde K8s API
        'a container name must be specified' mesajıyla 400 fırlatır.
        """
        exc = _make_api_exception(400, "a container name must be specified for pod mypod")

        with patch('web.blueprints.explorer.core.configure_kube_client'), \
             patch('web.blueprints.explorer.core.client.CoreV1Api') as mock_api_cls:
            mock_api_cls.return_value.read_namespaced_pod_log.side_effect = exc
            resp = client.get(
                '/k8s-explorer/logs?type=pod&namespace=default&name=multi-container-pod'
            )

        assert resp.status_code == 400
        data = resp.get_json()
        assert data is not None
        assert 'error' in data
        assert 'details' in data

    def test_api_exception_404_returns_http_404(self, client):
        """K8s API 404 fırlattığında route HTTP 404 dönmeli (500 değil).

        Var olmayan bir pod için istek yapıldığında K8s API 404 fırlatır.
        """
        exc = _make_api_exception(404, "pod nonexistent-pod not found")

        with patch('web.blueprints.explorer.core.configure_kube_client'), \
             patch('web.blueprints.explorer.core.client.CoreV1Api') as mock_api_cls:
            mock_api_cls.return_value.read_namespaced_pod_log.side_effect = exc
            resp = client.get(
                '/k8s-explorer/logs?type=pod&namespace=default&name=nonexistent-pod'
            )

        assert resp.status_code == 404
        data = resp.get_json()
        assert data is not None
        assert 'error' in data
        assert 'details' in data

    def test_api_exception_response_content_type_is_json(self, client):
        """ApiException durumunda yanıt Content-Type application/json olmalı."""
        exc = _make_api_exception(400, "bad request")

        with patch('web.blueprints.explorer.core.configure_kube_client'), \
             patch('web.blueprints.explorer.core.client.CoreV1Api') as mock_api_cls:
            mock_api_cls.return_value.read_namespaced_pod_log.side_effect = exc
            resp = client.get(
                '/k8s-explorer/logs?type=pod&namespace=default&name=mypod'
            )

        assert resp.content_type.startswith('application/json')

    def test_api_exception_not_converted_to_500(self, client):
        """ApiException'ın status kodu ne olursa olsun, 500'e dönüştürülmemeli."""
        for status in (400, 403, 404, 422):
            exc = _make_api_exception(status, f"error {status}")

            with patch('web.blueprints.explorer.core.configure_kube_client'), \
                 patch('web.blueprints.explorer.core.client.CoreV1Api') as mock_api_cls:
                mock_api_cls.return_value.read_namespaced_pod_log.side_effect = exc
                resp = client.get(
                    '/k8s-explorer/logs?type=pod&namespace=default&name=mypod'
                )

            assert resp.status_code == status, (
                f"ApiException(status={status}) için beklenen HTTP {status}, alınan {resp.status_code}"
            )


# ---------------------------------------------------------------------------
# Genel Exception: JSON formatında 500 dönüyor mu?
# ---------------------------------------------------------------------------

class TestLogsGeneralExceptionHandling:
    """Genel (non-ApiException) hatalarda JSON formatında 500 dönüyor mu?"""

    def test_unexpected_exception_returns_json_500(self, client):
        """Beklenmeyen RuntimeError'da route JSON formatında HTTP 500 dönmeli."""
        with patch('web.blueprints.explorer.core.configure_kube_client'), \
             patch('web.blueprints.explorer.core.client.CoreV1Api') as mock_api_cls:
            mock_api_cls.return_value.read_namespaced_pod_log.side_effect = RuntimeError(
                "unexpected internal crash"
            )
            resp = client.get(
                '/k8s-explorer/logs?type=pod&namespace=default&name=mypod'
            )

        assert resp.status_code == 500
        data = resp.get_json()
        assert data is not None
        assert 'error' in data
        assert 'details' in data

    def test_unexpected_exception_response_is_json(self, client):
        """Beklenmeyen hata yanıtının Content-Type application/json olmalı."""
        with patch('web.blueprints.explorer.core.configure_kube_client'), \
             patch('web.blueprints.explorer.core.client.CoreV1Api') as mock_api_cls:
            mock_api_cls.return_value.read_namespaced_pod_log.side_effect = ValueError("oops")
            resp = client.get(
                '/k8s-explorer/logs?type=pod&namespace=default&name=mypod'
            )

        assert resp.content_type.startswith('application/json')


# ---------------------------------------------------------------------------
# Input validasyonu
# ---------------------------------------------------------------------------

class TestLogsInputValidation:
    """Zorunlu query parametreleri eksik olduğunda 400 dönüyor mu?"""

    def test_missing_namespace_returns_400(self, client):
        """namespace verilmediğinde HTTP 400 dönmeli."""
        resp = client.get('/k8s-explorer/logs?type=pod&name=mypod')
        assert resp.status_code == 400

    def test_missing_name_returns_400(self, client):
        """name verilmediğinde HTTP 400 dönmeli."""
        resp = client.get('/k8s-explorer/logs?type=pod&namespace=default')
        assert resp.status_code == 400

    def test_wrong_type_returns_400(self, client):
        """type=pod dışında bir değer verildiğinde HTTP 400 dönmeli."""
        resp = client.get(
            '/k8s-explorer/logs?type=deployment&namespace=default&name=mydeployment'
        )
        assert resp.status_code == 400
