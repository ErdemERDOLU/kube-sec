"""tests/test_auth.py — Auth katmani ve ag erisim kontrolu testleri (backlog #21).

Kapsanan kabul kriterleri (AC-14 tablosu):
- T1: Localhost modunda (env var yok) auth hook devredisi; tum istekler gecerli.
- T2: Ag modunda auth'suz istek reddedilir (login'e redirect veya 401).
- T3: Ag modunda dogru token ile login basarili; session auth isaretcisi set edilir.
- T4: Ag modunda yanlis token ile login basarisiz; auth isaretcisi set edilmez.
- T5: Ag modunda beyaz listedeki yollar auth'suz erisilebilir.
- T6: KUBESEC_ACCESS_PASSWORD env var'i ile parola modu calisir.

NOT: CSRF koruması (WTF_CSRF_ENABLED) BILEREK devre disi birakilmiyor — login formunun
gercek CSRF akisiyla calistigini dogrulamak icin tum POST testleri once GET /login ile
gercek bir CSRF token'i cekip formda gonderiyor (bkz. _get_csrf_token). Bu, code review'da
bulunan "login formunda csrf_token eksik, production'da form CSRF hatasiyla calismiyor"
regresyonuna karsi bir koruma saglar.
"""

import os
import re
import sys

import pytest

# src/ yolunu ekle (conftest.py bunu yapiyor; dogrudan calistirma durumu icin de ekle)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import web.app as _web_app
from web.app import app


def _get_csrf_token(client):
    """GET /login ile render edilen formdan csrf_token gizli alanini ceker."""
    resp = client.get('/login')
    match = re.search(
        r'name="csrf_token"\s+value="([^"]+)"', resp.get_data(as_text=True)
    )
    assert match, "login.html formunda csrf_token gizli alani bulunamadi (regresyon!)."
    return match.group(1)


@pytest.fixture
def network_client(monkeypatch):
    """Ag modunu simule eden Flask test client'i.

    _NETWORK_BIND_ACTIVE=True ve _ACCESS_TOKEN='test-token-abc' olarak patch'lenir.
    CSRF korumasi GERCEK (aktif) birakilir — testler gercek CSRF token'i kullanir.
    """
    monkeypatch.setattr(_web_app, '_NETWORK_BIND_ACTIVE', True)
    monkeypatch.setattr(_web_app, '_ACCESS_TOKEN', 'test-token-abc')

    app.config['TESTING'] = True

    with app.test_client() as c:
        yield c

    app.config['TESTING'] = False


@pytest.fixture
def localhost_client(monkeypatch):
    """Localhost modunu simule eden Flask test client'i.

    _NETWORK_BIND_ACTIVE=False olarak patch'lenir; auth hook devredisidir.
    """
    monkeypatch.setattr(_web_app, '_NETWORK_BIND_ACTIVE', False)
    monkeypatch.setattr(_web_app, '_ACCESS_TOKEN', None)

    app.config['TESTING'] = True

    with app.test_client() as c:
        yield c

    app.config['TESTING'] = False


# ---------------------------------------------------------------------------
# T1 — Localhost modunda auth hook devredisi; tum istekler gecerli (AC-8)
# ---------------------------------------------------------------------------

def test_localhost_mode_no_auth_required(localhost_client):
    """Localhost modunda (_NETWORK_BIND_ACTIVE=False) auth hook hicbir kontrol yapmaz.

    /k8s-explorer/app-health saglik endpoint'i 401 veya 302 donmemeli;
    dogrudan yanit donmeli (200 veya baska bir uygulama kodunun donecegi kod).
    """
    resp = localhost_client.get('/k8s-explorer/app-health')
    assert resp.status_code not in (401, 302), (
        f"Localhost modunda auth hook aktif olmamali; ama status={resp.status_code} alindi."
    )


# ---------------------------------------------------------------------------
# T2 — Ag modunda auth'suz istek reddedilir (AC-3)
# ---------------------------------------------------------------------------

def test_network_mode_unauthenticated_request_rejected(network_client):
    """Ag modunda session'siz bir GET istegi /login'e redirect (302) veya 401 doner.

    HTML istegi (varsayilan Accept) /login'e yonlendirilmeli.
    """
    resp = network_client.get('/', follow_redirects=False)
    assert resp.status_code in (302, 401), (
        f"Ag modunda auth'suz istek reddedilmeli (302 veya 401); ama {resp.status_code} alindi."
    )
    if resp.status_code == 302:
        location = resp.headers.get('Location', '')
        assert 'login' in location, (
            f"Redirect hedefi /login olmali; ama '{location}' alindi."
        )


# ---------------------------------------------------------------------------
# T3 — Ag modunda dogru token ile login basarili (AC-4)
# ---------------------------------------------------------------------------

def test_network_mode_correct_token_login_succeeds(network_client):
    """POST /login ile dogru token girildiginde session auth isaretcisi set edilir.

    Gercek CSRF token'iyla gonderilir (regresyon korumasi). Basarili giriste
    / adresine (veya next'e) redirect beklenir.
    """
    csrf_token = _get_csrf_token(network_client)
    resp = network_client.post(
        '/login',
        data={'token': 'test-token-abc', 'next': '/', 'csrf_token': csrf_token},
        follow_redirects=False
    )
    assert resp.status_code == 302, (
        f"Dogru token ile login 302 redirect donmeli; ama {resp.status_code} alindi. "
        f"Body: {resp.get_data(as_text=True)[:300]}"
    )
    with network_client.session_transaction() as sess:
        assert sess.get('_kubesec_authenticated') is True, (
            "Dogru token ile giris sonrasi session['_kubesec_authenticated'] True olmali."
        )


# ---------------------------------------------------------------------------
# T4 — Ag modunda yanlis token ile login basarisiz (AC-5)
# ---------------------------------------------------------------------------

def test_network_mode_wrong_token_login_fails(network_client):
    """POST /login ile yanlis token girildiginde auth isaretcisi set edilmez.

    Login sayfasi hata mesajiyla yeniden gosterilmeli (200).
    """
    csrf_token = _get_csrf_token(network_client)
    resp = network_client.post(
        '/login',
        data={'token': 'yanlis-token-xyz', 'next': '/', 'csrf_token': csrf_token},
        follow_redirects=False
    )
    assert resp.status_code == 200, (
        f"Yanlis token ile login 200 donmeli (form yeniden gosterilir); ama {resp.status_code} alindi."
    )
    with network_client.session_transaction() as sess:
        assert not sess.get('_kubesec_authenticated'), (
            "Yanlis token ile giris sonrasi session['_kubesec_authenticated'] set edilmemeli."
        )


def test_login_form_contains_csrf_token(network_client):
    """Regresyon koruması: login.html formu her zaman bir csrf_token alani icermeli.

    Bu alan eksikse, CSRFProtect global koruması nedeniyle gercek kullanicilar
    login formunu HICBIR ZAMAN gonderemez (production'da auth tamamen kirilir).
    """
    resp = network_client.get('/login')
    body = resp.get_data(as_text=True)
    assert 'name="csrf_token"' in body, (
        "login.html formunda csrf_token gizli alani yok — form CSRF hatasiyla kirilir."
    )


# ---------------------------------------------------------------------------
# T5 — Ag modunda beyaz listedeki yollar auth'suz erisilebilir (AC-10)
# ---------------------------------------------------------------------------

def test_network_mode_whitelist_paths_accessible_without_auth(network_client):
    """Ag modunda auth aktifken beyaz listedeki yollar 401/redirect donmemeli.

    /k8s-explorer/app-health monitoring arac icin auth'suz erisebilir olmali (200).
    /static/ yolundan dosya istekleri auth'suz erisilebilir olmali (401/302 olmamali).
    """
    resp = network_client.get('/k8s-explorer/app-health')
    assert resp.status_code == 200, (
        f"/k8s-explorer/app-health beyaz listede; 200 donmeli ama {resp.status_code} alindi."
    )
    resp_static = network_client.get('/static/common.css')
    assert resp_static.status_code not in (401, 302), (
        f"/static/ yolu beyaz listede; 401/302 donmemeli ama {resp_static.status_code} alindi."
    )


# ---------------------------------------------------------------------------
# T6 — KUBESEC_ACCESS_PASSWORD env var'i ile parola modu calisir (AC-6)
# ---------------------------------------------------------------------------

def test_access_password_env_var_used_as_token(monkeypatch):
    """KUBESEC_ACCESS_PASSWORD set edilmisse login formunda bu parola kabul edilir.

    _ACCESS_TOKEN modül degiskenini KUBESEC_ACCESS_PASSWORD degeriyle patch'leyerek
    parola modunu simule eder.
    """
    monkeypatch.setattr(_web_app, '_NETWORK_BIND_ACTIVE', True)
    monkeypatch.setattr(_web_app, '_ACCESS_TOKEN', 'gizli-parola-123')

    app.config['TESTING'] = True

    try:
        with app.test_client() as c:
            csrf_token = _get_csrf_token(c)
            resp = c.post(
                '/login',
                data={'token': 'gizli-parola-123', 'next': '/', 'csrf_token': csrf_token},
                follow_redirects=False
            )
            assert resp.status_code == 302, (
                f"KUBESEC_ACCESS_PASSWORD modunda dogru parola ile login 302 donmeli; ama {resp.status_code} alindi."
            )
            with c.session_transaction() as sess:
                assert sess.get('_kubesec_authenticated') is True, (
                    "KUBESEC_ACCESS_PASSWORD modunda dogru parola ile giris sonrasi auth isaretcisi True olmali."
                )

            # Yanlis parola reddedilmeli (yeni CSRF token — session yenilendi, eskisi tukenmis olabilir)
            csrf_token2 = _get_csrf_token(c)
            resp2 = c.post(
                '/login',
                data={'token': 'yanlis-parola', 'next': '/', 'csrf_token': csrf_token2},
                follow_redirects=False
            )
            assert resp2.status_code == 200, (
                f"KUBESEC_ACCESS_PASSWORD modunda yanlis parola ile login 200 donmeli; ama {resp2.status_code} alindi."
            )
    finally:
        app.config['TESTING'] = False


# ---------------------------------------------------------------------------
# Ek: open-redirect korumasi (next parametresi)
# ---------------------------------------------------------------------------

def test_login_rejects_absolute_next_url_open_redirect(network_client):
    """`next` parametresi mutlak bir URL ise (open-redirect denemesi) yok sayilir.

    Basarili login sonrasi kullanici siteden disariya degil, '/'e yonlendirilmeli.
    """
    csrf_token = _get_csrf_token(network_client)
    resp = network_client.post(
        '/login',
        data={
            'token': 'test-token-abc',
            'next': 'https://evil.example.com/phishing',
            'csrf_token': csrf_token,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    location = resp.headers.get('Location', '')
    assert 'evil.example.com' not in location, (
        f"Open-redirect korumasi basarisiz — Location: {location}"
    )
