"""tests/test_validators.py — validate_k8s_name, validate_k8s_namespace, validate_helm_version testleri.

Projenin girdi dogrulama modulu (src/web/validators.py) icin unit testler.
Her fonksiyon icin gecerli ve gecersiz ornekler; spec AC-6 ve AC-8 kabul kriterlerini kapsar.
Calistirmak icin:
    cd /Users/erdemerdolu/Desktop/kube-sec
    .venv/bin/python -m pytest tests/test_validators.py -v
"""

import sys
import os

# src/ dizinini Python yoluna ekle: test'leri proje kokunden calistirabilmek icin
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from web.validators import validate_k8s_name, validate_k8s_namespace, validate_helm_version


# =============================================================================
# validate_k8s_name — Gecerli ornekler (AC-6)
# =============================================================================

def test_k8s_name_valid_simple():
    """Kucuk harfli basit isim gecmeli."""
    assert validate_k8s_name('nginx') is True


def test_k8s_name_valid_with_hyphen():
    """Tire iceren isim gecmeli (AC-6)."""
    assert validate_k8s_name('nginx-deployment') is True


def test_k8s_name_valid_with_dot():
    """Nokta iceren isim gecmeli (AC-6)."""
    assert validate_k8s_name('my-app.v2') is True


def test_k8s_name_valid_single_char():
    """Tek alfanumerik karakter gecmeli (AC-6)."""
    assert validate_k8s_name('a') is True


def test_k8s_name_valid_alphanumeric():
    """Yalnizca rakam ve harf iceren isim gecmeli."""
    assert validate_k8s_name('myapp123') is True


def test_k8s_name_valid_starts_with_digit():
    """Rakamla baslayan isim gecmeli (RFC 1123 DNS subdomain izin verir)."""
    assert validate_k8s_name('1stpod') is True


# =============================================================================
# validate_k8s_name — Gecersiz ornekler (AC-8)
# =============================================================================

def test_k8s_name_invalid_empty():
    """Bos string reddedilmeli (AC-8)."""
    assert validate_k8s_name('') is False


def test_k8s_name_invalid_none():
    """None degeri reddedilmeli."""
    assert validate_k8s_name(None) is False


def test_k8s_name_invalid_uppercase():
    """Buyuk harf iceren isim reddedilmeli (AC-8: 'MyPod')."""
    assert validate_k8s_name('MyPod') is False


def test_k8s_name_invalid_starts_with_hyphen():
    """Tire ile baslayan isim reddedilmeli (AC-8: '-nginx')."""
    assert validate_k8s_name('-nginx') is False


def test_k8s_name_invalid_ends_with_hyphen():
    """Tire ile biten isim reddedilmeli (AC-8: 'nginx-')."""
    assert validate_k8s_name('nginx-') is False


def test_k8s_name_invalid_special_char():
    """Ozel karakter iceren isim reddedilmeli (AC-8: 'nginx;ls')."""
    assert validate_k8s_name('nginx;ls') is False


def test_k8s_name_invalid_space():
    """Bosluk iceren isim reddedilmeli (AC-8: 'my pod')."""
    assert validate_k8s_name('my pod') is False


def test_k8s_name_invalid_too_long():
    """254 karakter isim reddedilmeli — max 253 (AC-8)."""
    long_name = 'a' * 254
    assert validate_k8s_name(long_name) is False


def test_k8s_name_valid_exactly_253_chars():
    """Tam 253 karakter isim gecmeli (sinir deger testi)."""
    name = 'a' + 'b' * 251 + 'c'  # 253 karakter
    assert validate_k8s_name(name) is True


def test_k8s_name_invalid_only_hyphens():
    """Sadece tireden olusan isim reddedilmeli (AC-8: '---')."""
    assert validate_k8s_name('---') is False


def test_k8s_name_invalid_flag_injection():
    """Flag injection denemesi reddedilmeli ('--kubeconfig')."""
    assert validate_k8s_name('--kubeconfig') is False


def test_k8s_name_invalid_path_traversal():
    """Path traversal denemesi reddedilmeli ('../etc/shadow')."""
    assert validate_k8s_name('../etc/shadow') is False


# =============================================================================
# validate_k8s_namespace — Gecerli ornekler (AC-6)
# =============================================================================

def test_k8s_namespace_valid_default():
    """'default' namespace gecmeli (AC-6)."""
    assert validate_k8s_namespace('default') is True


def test_k8s_namespace_valid_kube_system():
    """'kube-system' namespace gecmeli (AC-6)."""
    assert validate_k8s_namespace('kube-system') is True


def test_k8s_namespace_valid_simple():
    """Kucuk harfli basit namespace gecmeli."""
    assert validate_k8s_namespace('production') is True


# =============================================================================
# validate_k8s_namespace — Gecersiz ornekler (AC-8)
# =============================================================================

def test_k8s_namespace_invalid_with_dot():
    """Nokta iceren namespace reddedilmeli (AC-8: 'my.namespace')."""
    assert validate_k8s_namespace('my.namespace') is False


def test_k8s_namespace_invalid_too_long():
    """64 karakter namespace reddedilmeli — max 63 (AC-8)."""
    long_ns = 'a' * 64
    assert validate_k8s_namespace(long_ns) is False


def test_k8s_namespace_valid_exactly_63_chars():
    """Tam 63 karakter namespace gecmeli (sinir deger testi)."""
    ns = 'a' + 'b' * 61 + 'c'  # 63 karakter
    assert validate_k8s_namespace(ns) is True


def test_k8s_namespace_invalid_path_traversal():
    """Path traversal denemesi reddedilmeli ('../../etc/shadow')."""
    assert validate_k8s_namespace('../../etc/shadow') is False


def test_k8s_namespace_invalid_empty():
    """Bos string reddedilmeli."""
    assert validate_k8s_namespace('') is False


def test_k8s_namespace_invalid_uppercase():
    """Buyuk harf iceren namespace reddedilmeli."""
    assert validate_k8s_namespace('MyNamespace') is False


def test_k8s_namespace_invalid_starts_with_hyphen():
    """Tire ile baslayan namespace reddedilmeli."""
    assert validate_k8s_namespace('-myns') is False


def test_k8s_namespace_invalid_ends_with_hyphen():
    """Tire ile biten namespace reddedilmeli (RFC 1123: 'ns-')."""
    assert validate_k8s_namespace('ns-') is False


# =============================================================================
# validate_helm_version — Gecerli ornekler (AC-6)
# =============================================================================

def test_helm_version_valid_semver():
    """Standart semver gecmeli (AC-6: '0.31.0')."""
    assert validate_helm_version('0.31.0') is True


def test_helm_version_valid_with_prerelease():
    """Pre-release tag iceren semver gecmeli (AC-6: '1.0.0-rc1')."""
    assert validate_helm_version('1.0.0-rc1') is True


def test_helm_version_valid_with_build_meta():
    """Build metadata iceren versiyon gecmeli ('1.0.0+build.1')."""
    assert validate_helm_version('1.0.0+build.1') is True


def test_helm_version_valid_simple():
    """Basit rakamla baslayan versiyon gecmeli."""
    assert validate_helm_version('2') is True


# =============================================================================
# validate_helm_version — Gecersiz ornekler
# =============================================================================

def test_helm_version_invalid_flag_injection():
    """Flag injection denemesi reddedilmeli ('--set image.tag=evil')."""
    assert validate_helm_version('--set image.tag=evil') is False


def test_helm_version_invalid_starts_with_letter():
    """Harfle baslayan versiyon reddedilmeli ('v1.0.0' bile gecersiz)."""
    assert validate_helm_version('v1.0.0') is False


def test_helm_version_invalid_empty():
    """Bos string reddedilmeli."""
    assert validate_helm_version('') is False


def test_helm_version_invalid_none():
    """None degeri reddedilmeli."""
    assert validate_helm_version(None) is False


def test_helm_version_invalid_with_space():
    """Bosluk iceren versiyon reddedilmeli."""
    assert validate_helm_version('1.0.0 evil') is False


def test_helm_version_invalid_too_long():
    """129 karakter versiyon reddedilmeli — max 128."""
    long_ver = '1' + '.' * 128  # 129 karakter
    assert validate_helm_version(long_ver) is False


# =============================================================================
# Trailing-newline guvenligi — $ vs \Z regression testleri (code-reviewer #7)
# Python re.match() ile $ anchor'i, string sonundaki \n'i "gorunmez" sayar.
# \Z anchor'i kullanilarak bu acik kapatildi; asagidaki testler bunu dogrular.
# =============================================================================

def test_k8s_name_invalid_trailing_newline():
    r"""Sonda newline (\n) olan isim reddedilmeli — \\Z anchor dogrulamasi."""
    assert validate_k8s_name('nginx\n') is False


def test_k8s_namespace_invalid_trailing_newline():
    r"""Sonda newline (\n) olan namespace reddedilmeli — \\Z anchor dogrulamasi."""
    assert validate_k8s_namespace('default\n') is False


def test_helm_version_invalid_trailing_newline():
    r"""Sonda newline (\n) olan versiyon reddedilmeli — \\Z anchor dogrulamasi."""
    assert validate_helm_version('0.31.0\n') is False
