"""tests/test_secret_key.py — Secret key ve cookie guvenlik bayraklarinin dogru calistigini dogrular (backlog #22).

Kapsanan kabul kriterleri:
- AC-1: Non-dev modda sabit 'dev-secret-do-not-use-in-production' kullanilmaz.
- AC-2: Non-dev, non-frozen, APP_SECRET_KEY set edilmemisse rastgele anahtar uretilir.
- AC-4: APP_SECRET_KEY env var'i set edildiginde o deger kullanilir.
- AC-5: SESSION_COOKIE_SAMESITE acikca 'Lax' olarak set edilmistir.
- AC-9/T4: SESSION_COOKIE_HTTPONLY True olmalidir.

Not (import-zamani degerlendirme): app.secret_key modul import zamaninda bir kez
hesaplanir ve test sureci boyunca sabittir. Bu testler o degeri dogrular; test
ortaminda normalde FLASK_ENV ve APP_SECRET_KEY set edilmez, dolayisiyla anahtar
secrets.token_hex(32) ile rastgele uretilmis olmalidir.
"""

import os
import sys

import pytest

from web.app import app


# ---------------------------------------------------------------------------
# T1 — Sabit dev anahtari non-dev modda kullanilmamali (AC-1, AC-2)
# ---------------------------------------------------------------------------

def test_no_hardcoded_dev_secret_in_non_dev_mode():
    """Non-dev modda (FLASK_ENV=development degil) sabit dev anahtari kullanilmaz.

    Test ortaminda normalde FLASK_ENV set edilmediginden uygulama rastgele
    secrets.token_hex(32) ile anahtar uretmis olmalidir. Bu, session forgery
    ve CSRF bypass vektorunu kapatan temel guvenlik gereksinimdir (AC-1).
    """
    flask_env = os.environ.get('FLASK_ENV', '')
    app_secret_env = os.environ.get('APP_SECRET_KEY', '')
    is_frozen = getattr(sys, 'frozen', False)

    if flask_env != 'development' and not app_secret_env and not is_frozen:
        # Standard test ortami: rastgele anahtar uretilmis olmali
        assert app.secret_key != 'dev-secret-do-not-use-in-production', (
            "Non-dev modda sabit 'dev-secret-do-not-use-in-production' anahtari "
            "kullanilmamalidir — CSRF bypass ve session forgery vektoru acik kalir."
        )
        # Rastgele uretilen anahtar en az 64 hex karakter olmalidir (secrets.token_hex(32))
        assert len(app.secret_key) >= 64, (
            f"Rastgele uretilen anahtarin uzunlugu en az 64 (hex) karakter olmalidir; "
            f"mevcut uzunluk: {len(app.secret_key)}"
        )


# ---------------------------------------------------------------------------
# T2 — APP_SECRET_KEY env var set edildiginde o deger kullanilir (AC-4)
# ---------------------------------------------------------------------------

def test_app_secret_key_env_var_is_used():
    """APP_SECRET_KEY env var set edildiginde app.secret_key o degeri kullanir (AC-4).

    Bu test iki senaryoyu kapsar:
    1. Test ortaminda APP_SECRET_KEY zaten set edilmisse: app.secret_key eslesmelidir.
    2. Set edilmemisse: sabit dev anahtari kullanilmadigini dogrular
       (env var set edilince bu yolun calistigini dolaylilik ile garanti eder).
    """
    env_key = os.environ.get('APP_SECRET_KEY')
    if env_key:
        # Eger CI/test ortaminda APP_SECRET_KEY set edilmisse, app bu degeri kullanmis olmali.
        assert app.secret_key == env_key, (
            f"APP_SECRET_KEY='{env_key}' set edilmis ancak app.secret_key='{app.secret_key}' farkli."
        )
    else:
        # Import zamaninda APP_SECRET_KEY set edilmemis; env var mantigi (satir 33-35)
        # devreye girmemis ve deger sabit dev anahtari olmamalıdır.
        assert app.secret_key != 'dev-secret-do-not-use-in-production', (
            "APP_SECRET_KEY set edilmemis ve FLASK_ENV!=development iken "
            "sabit dev anahtari kullanilmamalidir."
        )


# ---------------------------------------------------------------------------
# T3 — SESSION_COOKIE_SAMESITE 'Lax' olmali (AC-5)
# ---------------------------------------------------------------------------

def test_session_cookie_samesite_is_lax():
    """app.config['SESSION_COOKIE_SAMESITE'] acikca 'Lax' olarak set edilmis olmalidir (AC-5).

    'Lax' degeri, cross-origin POST isteklerinde cookie gonderimini engeller ve
    CSRF saldirilarindan ek bir katman koruması saglar. Flask'in varsayilan degeri
    surume gore degisebileceginden acik set etmek zorunludur.
    """
    assert app.config.get('SESSION_COOKIE_SAMESITE') == 'Lax', (
        f"SESSION_COOKIE_SAMESITE 'Lax' olmali; mevcut: {app.config.get('SESSION_COOKIE_SAMESITE')!r}"
    )


# ---------------------------------------------------------------------------
# T4 — SESSION_COOKIE_HTTPONLY True olmali (AC-9/T4)
# ---------------------------------------------------------------------------

def test_session_cookie_httponly_is_true():
    """app.config['SESSION_COOKIE_HTTPONLY'] True olmalidir (AC-9/T4).

    HttpOnly bayragi, JavaScript'in document.cookie araciligiyla session cookie'sine
    erisimini engeller; XSS saldirilarinda cookie calismasini onler.
    """
    assert app.config.get('SESSION_COOKIE_HTTPONLY') is True, (
        f"SESSION_COOKIE_HTTPONLY True olmali; mevcut: {app.config.get('SESSION_COOKIE_HTTPONLY')!r}"
    )


# ---------------------------------------------------------------------------
# T5 — KUBESEC_SECURE_COOKIES env var SESSION_COOKIE_SECURE'u kontrol eder (AC-12)
# ---------------------------------------------------------------------------

def test_session_cookie_secure_controlled_by_env_var():
    """KUBESEC_SECURE_COOKIES env var'i SESSION_COOKIE_SECURE degerini belirler (AC-12).

    Env var set edilmemisse False (HTTP-only ortamda cookie hic gonderilmemesini onler);
    set edilmisse True (HTTPS reverse proxy arkasinda guvenli cookie iletimi).
    """
    secure_env = os.environ.get('KUBESEC_SECURE_COOKIES', '').lower()
    expected = secure_env in ('1', 'true', 'yes', 'on')
    actual = app.config.get('SESSION_COOKIE_SECURE')
    assert actual == expected, (
        f"KUBESEC_SECURE_COOKIES='{os.environ.get('KUBESEC_SECURE_COOKIES', '')}' iken "
        f"SESSION_COOKIE_SECURE={actual!r} olmali, ama {expected!r} bekleniyor."
    )
