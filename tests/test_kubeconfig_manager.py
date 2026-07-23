"""tests/test_kubeconfig_manager.py — list_kubeconfigs() ve get_active_kubeconfig_path() testleri (AC-5).

src/web/kubeconfig_manager.py fonksiyonlarını test eder.
Global state (KUBECONFIG_STORE, KUBECONFIG_UPLOAD_DIR vb.) monkeypatch ile
geçici değerlere yönlendirilir; gerçek kubeconfigs/ dizinine ve global
state'e kalıcı değişiklik YAPILMAZ.
"""

import os
import pytest

import web.kubeconfig_manager as kcm
from web.kubeconfig_manager import list_kubeconfigs, get_active_kubeconfig_path


def test_list_kubeconfigs_empty(monkeypatch, tmp_path):
    """KUBECONFIG_STORE boş ve KUBECONFIG_UPLOAD_DIR boş geçici dizine yönlendirilince
    list_kubeconfigs() boş liste döner.
    """
    monkeypatch.setattr(kcm, 'KUBECONFIG_STORE', {})
    monkeypatch.setattr(kcm, 'KUBECONFIG_UPLOAD_DIR', str(tmp_path))

    result = list_kubeconfigs()
    assert result == []


def test_list_kubeconfigs_with_disk_file(monkeypatch, tmp_path):
    """KUBECONFIG_UPLOAD_DIR içinde dosya varsa list_kubeconfigs() bu dosyayı
    içeren bir liste döner. Dönüş öğesinde name, path ve source alanları olmalı.
    """
    monkeypatch.setattr(kcm, 'KUBECONFIG_STORE', {})
    monkeypatch.setattr(kcm, 'KUBECONFIG_UPLOAD_DIR', str(tmp_path))

    kubeconfig_file = tmp_path / 'test-cluster.yaml'
    kubeconfig_file.write_text('apiVersion: v1\nkind: Config\n')

    result = list_kubeconfigs()
    assert len(result) == 1

    item = result[0]
    assert item['name'] == 'test-cluster.yaml'
    assert item['source'] == 'disk'
    assert 'path' in item
    assert os.path.isfile(item['path'])


def test_get_active_kubeconfig_path_returns_none_when_nothing_configured(monkeypatch, tmp_path):
    """Aktif kubeconfig, global state ve KUBECONFIG env değişkeni yokken
    get_active_kubeconfig_path() None döner.
    """
    monkeypatch.setattr(kcm, 'KUBECONFIG_STORE', {})
    monkeypatch.setattr(kcm, 'KUBECONFIG_UPLOAD_DIR', str(tmp_path))
    monkeypatch.setattr(kcm, 'KUBECONFIG_ACTIVE_GLOBAL', None)
    monkeypatch.setattr(kcm, 'KUBECONFIG_LAST_PATH', None)
    monkeypatch.delenv('KUBECONFIG', raising=False)

    result = get_active_kubeconfig_path()
    assert result is None
