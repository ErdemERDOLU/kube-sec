"""tests/test_i18n.py — translate() fonksiyonu birim testleri (AC-4).

src/web/i18n.py içindeki translate(key, lang) fonksiyonunu test eder.
Flask bağımlılığı yoktur; saf Python fonksiyon çağrısıdır.
"""

from web.i18n import translate


def test_translate_valid_key_turkish():
    """Geçerli anahtar + 'tr' dili -> Türkçe çeviriyi döner."""
    result = translate('nav.home', 'tr')
    assert result == 'Ana Sayfa'


def test_translate_valid_key_english():
    """Geçerli anahtar + 'en' dili -> İngilizce çeviriyi döner."""
    result = translate('nav.home', 'en')
    assert result == 'Home'


def test_translate_invalid_key_returns_key_itself():
    """Geçersiz/bilinmeyen anahtar -> anahtarın kendisini döner (fallback)."""
    key = 'non.existent.key.xyz'
    result = translate(key, 'tr')
    assert result == key


def test_translate_unknown_language_falls_back_to_turkish():
    """Bilinmeyen dil kodu verildiğinde Türkçe fallback döner."""
    result = translate('nav.home', 'fr')
    assert result == 'Ana Sayfa'
