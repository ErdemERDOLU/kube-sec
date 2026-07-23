"""tests/conftest.py — Merkezi pytest fixture'ları ve sys.path ayarı.

Tüm test dosyaları bu conftest.py sayesinde ortak Flask test client'ını
ve sys.path konfigürasyonunu paylaşır.
"""

import os
import sys

# src/ dizinini Python yoluna merkezi olarak ekle; her test dosyasının
# bunu tekrar yapmasına gerek kalmaz.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from web.app import app as _flask_app


@pytest.fixture
def app_instance():
    """Test edilebilir Flask app nesnesini döner.

    TESTING=True ve WTF_CSRF_ENABLED=False ayarlanır; test sonrasında
    orijinal değerlere geri yüklenir.
    """
    _was_testing = _flask_app.config.get('TESTING', False)
    _was_csrf = _flask_app.config.get('WTF_CSRF_ENABLED', True)

    _flask_app.config['TESTING'] = True
    _flask_app.config['WTF_CSRF_ENABLED'] = False

    yield _flask_app

    _flask_app.config['TESTING'] = _was_testing
    _flask_app.config['WTF_CSRF_ENABLED'] = _was_csrf


@pytest.fixture
def client(app_instance):
    """Flask test client döner.

    TESTING=True ve WTF_CSRF_ENABLED=False olarak konfigüre edilmiş
    app üzerinden bir test client sağlar. test_csrf.py kendi yerel
    'client' fixture'ını tanımladığı için bu fixture orada kullanılmaz
    (pytest dosya-seviyesi fixture'a öncelik tanır).
    """
    with app_instance.test_client() as c:
        yield c
