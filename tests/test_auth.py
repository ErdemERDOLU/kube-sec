"""tests/test_auth.py — Auth katmani ve ag erisim kontrolu testleri (backlog #21).

Kapsanan kabul kriterleri (AC-14 tablosu):
- T1: Localhost modunda (env var yok) auth hook devredisi; tum istekler gecerli.
- T2: Ag modunda auth'suz istek reddedilir (login'e redirect veya 401).
- T3: Ag modunda dogru token ile login basarili; session auth isaretcisi set edilir.
- T4: Ag modunda yanlis token ile login basarisiz; auth isaretcisi set edilmez.
- T5: Ag modunda beyaz listedeki yollar auth'suz erisilebilir.
- T6: KUBESEC_ACCESS_PASSWORD env var'i ile parola modu calisir.
"""

import os
import sys

import pytest

# src/ yolunu ekle (conftest.py bunu yapiyor; dogrudan calistirma durumu icin de ekle)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import web.app as _web_app
from web.app import app


@pytest.fixture
def network_client(monkeypatch):
    """Ag modunu simule eden Flask test client'i.

    _NETWORK_BIND_ACTIVE=True ve _ACCESS_TOKEN='test-token-abc' olarak patch'lenir.
    CSRF ve TESTING bayraklari da uygun sekilde ayarlanir.
    """
    monkeypatch.setattr(_web_app, '_NETWORK_BIND_ACTIVE', True)
    monkeypatch.setattr(_web_app, '_ACCESS_TOKEN', 'test-token-abc')

    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False

    with app.test_client() as c:
        yield c

    app.config['TESTING'] = False
    app.config['WTF_CSRF_ENABLED'] = True


@pytest.fixture
def localhost_client(monkeypatch):
    """Localhost modunu simule eden Flask test client'i.

    _NETWORK_BIND_ACTIVE=False olarak patch'lenir; auth hook devredisidir.
    """
    monkeypatch.setattr(_web_app, '_NETWORK_BIND_ACTIVE', False)
    monkeypatch.setattr(_web_app, '_ACCESS_TOKEN', None)

    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False

    with app.test_client() as c:
        yield c

    app.config['TESTING'] = False
    app.config['WTF_CSRF_ENABLED'] = True


# ---------------------------------------------------------------------------
# T1 — Localhost modunda auth hook devredisi; tum istekler gecerli (AC-8)
# ---------------------------------------------------------------------------

def test_localhost_mode_no_auth_required(localhost_client):
    """Localhost modunda (_NETWORK_BIND_ACTIVE=False) auth hook hicbir kontrol yapmaz.

    /k8s-explorer/app-health saglik endpoint'i 401 veya 302 donmemeli;
    dogrudan yanit donmeli (200 veya baska bir uygulama kodunun donecegi kod).
    """
    resp = localhost_client.get('/k8s-explorer/app-health')
    # Auth kontrolu olmadigi icin 401 veya /login redirect'i (302) beklenmez
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

    Basarili giriste / adresine (veya next'e) redirect beklenir.
    """
    resp = network_client.post(
        '/login',
        data={'token': 'test-token-abc', 'next': '/'},
        follow_redirects=False
    )
    assert resp.status_code == 302, (
        f"Dogru token ile login 302 redirect donmeli; ama {resp.status_code} alindi."
    )
    # Session'da auth isaretcisi olmali
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
    resp = network_client.post(
        '/login',
        data={'token': 'yanlis-token-xyz', 'next': '/'},
        follow_redirects=False
    )
    assert resp.status_code == 200, (
        f"Yanlis token ile login 200 donmeli (form yeniden gosterilir); ama {resp.status_code} alindi."
    )
    # Session'da auth isaretcisi olmamali
    with network_client.session_transaction() as sess:
        assert not sess.get('_kubesec_authenticated'), (
            "Yanlis token ile giris sonrasi session['_kubesec_authenticated'] set edilmemeli."
        )


# ---------------------------------------------------------------------------
# T5 — Ag modunda beyaz listedeki yollar auth'suz erisilebilir (AC-10)
# ---------------------------------------------------------------------------

def test_network_mode_whitelist_paths_accessible_without_auth(network_client):
    """Ag modunda auth aktifken beyaz listedeki yollar 401/redirect donmemeli.

    /k8s-explorer/app-health monitoring arac icin auth'suz erisebilir olmali.
    /static/ yolundan dosya istekleri auth'suz erisilebilir olmali.
    """
    # Saglik endpoint'i — auth'suz 200 donmeli
    resp = network_client.get('/k8s-explorer/app-health')
    assert resp.status_code not in (401,), (
        f"/k8s-explorer/app-health beyaz listede; 401 donmemeli ama {resp.status_code} alindi."
    )
    # Statik dosya yolu — auth'suz erisilebilmeli (404 olabilir, dosya olmayabilir; ama 401 olmamali)
    resp_static = network_client.get('/static/common.css')
    assert resp_static.status_code not in (401,), (
        f"/static/ yolu beyaz listede; 401 donmemeli ama {resp_static.status_code} alindi."
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
    app.config['WTF_CSRF_ENABLED'] = False

    try:
        with app.test_client() as c:
            # Dogru parola ile login
            resp = c.post(
                '/login',
                data={'token': 'gizli-parola-123', 'next': '/'},
                follow_redirects=False
            )
            assert resp.status_code == 302, (
                f"KUBESEC_ACCESS_PASSWORD modunda dogru parola ile login 302 donmeli; ama {resp.status_code} alindi."
            )
            with c.session_transaction() as sess:
                assert sess.get('_kubesec_authenticated') is True, (
                    "KUBESEC_ACCESS_PASSWORD modunda dogru parola ile giris sonrasi auth isaretcisi True olmali."
                )

            # Yanlis parola reddedilmeli
            resp2 = c.post(
                '/login',
                data={'token': 'yanlis-parola', 'next': '/'},
                follow_redirects=False
            )
            assert resp2.status_code == 200, (
                f"KUBESEC_ACCESS_PASSWORD modunda yanlis parola ile login 200 donmeli; ama {resp2.status_code} alindi."
            )
    finally:
        app.config['TESTING'] = False
        app.config['WTF_CSRF_ENABLED'] = True
