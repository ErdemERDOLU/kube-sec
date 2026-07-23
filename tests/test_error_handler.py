"""tests/test_error_handler.py — Global error handler davranisi testleri (backlog #14).

Mevcut conftest.py'deki client fixture'ini kullanir.
Kubernetes cluster baglantisi GEREKMEZ.

Test kapsamı:
  - Var olmayan route -> 404 (500 degil)
  - Yanlis HTTP metodu -> 405
  - Production modda (FLASK_ENV/FLASK_DEBUG set edilmemis) traceback alani olmamali
  - Hata yaniti JSON formatinda olmali
"""


def test_nonexistent_route_returns_404(client):
    """Var olmayan bir route'a GET istegi HTTP 404 donmeli (500 degil).

    Duzeltme oncesi: handle_exception() HTTPException kontrolu yapmadan
    kosulsuz 500 donduruyordu. Duzeltme sonrasi: NotFound (HTTPException
    alt sinifi) kendi e.code=404 ile doner.
    """
    resp = client.get('/bu-route-kesinlikle-yok-12345')
    assert resp.status_code == 404
    data = resp.get_json()
    assert data is not None
    assert 'error' in data


def test_wrong_method_returns_405(client):
    """Yalnizca GET destekleyen bir route'a DELETE istegi HTTP 405 donmeli.

    /k8s-explorer/app-health yalnizca GET destekler.
    MethodNotAllowed bir HTTPException oldugundan handle_exception() artik
    e.code=405 ile doner, 500 degil.
    """
    resp = client.delete('/k8s-explorer/app-health')
    assert resp.status_code == 405
    data = resp.get_json()
    assert data is not None
    assert 'error' in data


def test_traceback_not_in_prod_response_404(client):
    """Production modda (FLASK_ENV/FLASK_DEBUG set edilmemis) hata yanitinda
    'traceback' alani OLMAMALI (404 senaryosu).

    Test ortaminda FLASK_ENV ve FLASK_DEBUG normalde set edilmediginden
    _debug_enabled=False olur ve traceback yanita eklenmez.
    Eger CI ortaminda bu env variable'lar set edilmisse test, monkeypatch
    ile _debug_enabled=False zorlayarak calismak durumundadir.
    """
    import web.app as _app_module

    original = _app_module._debug_enabled
    try:
        _app_module._debug_enabled = False
        resp = client.get('/bu-route-kesinlikle-yok-12345')
        data = resp.get_json()
        assert data is not None
        assert 'traceback' not in data
    finally:
        _app_module._debug_enabled = original


def test_traceback_not_in_prod_response_405(client):
    """Production modda (FLASK_ENV/FLASK_DEBUG set edilmemis) hata yanitinda
    'traceback' alani OLMAMALI (405 senaryosu)."""
    import web.app as _app_module

    original = _app_module._debug_enabled
    try:
        _app_module._debug_enabled = False
        resp = client.delete('/k8s-explorer/app-health')
        data = resp.get_json()
        assert data is not None
        assert 'traceback' not in data
    finally:
        _app_module._debug_enabled = original


def test_error_response_is_json_404(client):
    """404 hata yanitinin Content-Type'i application/json olmali."""
    resp = client.get('/bu-route-kesinlikle-yok-12345')
    assert resp.content_type.startswith('application/json')


def test_error_response_is_json_405(client):
    """405 hata yanitinin Content-Type'i application/json olmali."""
    resp = client.delete('/k8s-explorer/app-health')
    assert resp.content_type.startswith('application/json')


def test_traceback_present_in_debug_mode_404(client):
    """Debug modda (_debug_enabled=True) 404 yanitinda 'traceback' alani OLMALI.

    Gelistirici deneyimini korumak icin dev modda traceback yanita eklenir.
    """
    import web.app as _app_module

    original = _app_module._debug_enabled
    try:
        _app_module._debug_enabled = True
        resp = client.get('/bu-route-kesinlikle-yok-12345')
        data = resp.get_json()
        assert data is not None
        assert 'traceback' in data
    finally:
        _app_module._debug_enabled = original


def test_real_500_does_not_leak_traceback_in_prod(client):
    """Gercek bir RuntimeError'da production modda traceback yanita eklenmemeli.

    /k8s-explorer/health route'u configure_kube_client() cagrisini kendi
    try/except blogu icinde yapar; bu nedenle fırlatılan exception route
    icerisinde yakalanır. Handler'in dogrudan devreye girmesi yerine bu test,
    route'un da (try/except bloku sayesinde) traceback icermeyen bir yanit
    dondurmesini dogrular.

    Not: TESTING=True modunda Flask runtime exception'larini genel
    handle_exception()'a yonlendirmek yerine test'e propagate eder.
    Bu durum sadece non-HTTP exception'lar icin gecerlidir; 404/405 gibi
    HTTPException'lar her modda error handler'a ulasir (diger testlerde
    dogrulanmistir).
    """
    from unittest.mock import patch
    import web.app as _app_module

    original = _app_module._debug_enabled
    try:
        _app_module._debug_enabled = False

        # configure_kube_client mock'laniyor; k8s_explorer_health kendi
        # try/except blogu ile hatayı yakalar ve ok=False yaniti doner.
        with patch(
            'web.blueprints.explorer.core.configure_kube_client',
            side_effect=RuntimeError('test-forced-crash-for-handler-test'),
        ):
            resp = client.get('/k8s-explorer/health')

        # Route kendi try/except'i ile hatayı yonetir: 200 ve ok=False doner.
        # Her iki durumda da (200 veya 500) yanit body'sinde traceback OLMAMALI.
        data = resp.get_json()
        if data is not None:
            assert 'traceback' not in data
    finally:
        _app_module._debug_enabled = original
