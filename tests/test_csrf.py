"""tests/test_csrf.py — CSRF korumasının (Flask-WTF CSRFProtect) doğru çalıştığını doğrular (backlog #6).

Bu testler canlı bir Kubernetes cluster'ı GEREKTİRMEZ; CSRF kontrolü,
Flask-WTF'in ``before_request`` hook'u sayesinde view fonksiyonu hiç
çalışmadan ÖNCE devreye girer. Bu yüzden gerçek bir cluster'a bağlanan
bir endpoint (`/kubeconfigs`) kullanılsa bile, token eksikse istek
view koduna hiç ulaşmadan reddedilir.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest

from web.app import app


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


def _extract_csrf_token(html):
    """Render edilmiş bir sayfanın <head>'indeki csrf-token meta tag'inden token'ı çıkarır."""
    match = re.search(r'<meta name="csrf-token" content="([^"]+)">', html)
    assert match, "csrf-token meta tag'i bulunamadı (base.html doğru render edilmiş mi?)"
    return match.group(1)


def test_post_without_csrf_token_rejected(client):
    """Token gönderilmeden yapılan POST isteği CSRF hatasıyla HTTP 400 döner."""
    resp = client.post('/kubeconfigs', json={'name': 'test', 'content': 'foo'})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data is not None
    assert 'CSRF' in data.get('error', '')


def test_get_requests_not_affected_by_csrf(client):
    """GET istekleri CSRF korumasından etkilenmez (WTF_CSRF_METHODS varsayılanı POST/PUT/PATCH/DELETE)."""
    resp = client.get('/k8s-explorer/app-health')
    assert resp.status_code != 400 or 'CSRF' not in (resp.get_json() or {}).get('error', '')


def test_post_with_valid_csrf_token_passes_csrf_layer(client):
    """Geçerli token ile yapılan POST isteği CSRF katmanını geçer.

    Not: İstek yine de 400 dönebilir (ör. eksik 'content' alanı), ancak bu durumda
    hata mesajı iş mantığına (`name ve content zorunlu`) ait olmalı — CSRF hatası
    OLMAMALI. Bu, CSRF kontrolünün doğru token'ı GERÇEKTEN kabul ettiğini kanıtlar.
    """
    page = client.get('/')
    token = _extract_csrf_token(page.get_data(as_text=True))

    resp = client.post(
        '/kubeconfigs',
        json={},  # bilerek eksik body -> iş mantığı hatası bekleniyor, CSRF hatası değil
        headers={'X-CSRFToken': token},
    )
    data = resp.get_json()
    assert data is not None
    # CSRF katmanı geçildi: hata mesajı CSRF'e değil, eksik alanlara işaret etmeli.
    assert 'CSRF' not in data.get('error', '')


def test_csrf_error_response_is_json(client):
    """CSRF hatası HTML hata sayfası değil, JSON formatında döner (fetch()'in resp.json() ile parse edebilmesi için)."""
    resp = client.post('/kubeconfigs', json={'name': 'test', 'content': 'foo'})
    assert resp.status_code == 400
    assert resp.content_type.startswith('application/json')
