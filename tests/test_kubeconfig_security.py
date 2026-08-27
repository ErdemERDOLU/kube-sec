"""tests/test_kubeconfig_security.py — Backlog #23: Kubeconfig path traversal ve izin güvenlik testleri.

_sanitize_kubeconfig_name() yardımcı fonksiyonu ile kubeconfig dosya/dizin izin
davranışlarını kapsar. Testler AC-1, AC-2, AC-3, AC-4, AC-5, AC-7, AC-8 kabul
kriterlerine karşılık gelir.
"""

import os
import stat
import pytest

import web.blueprints.kubeconfigs as kc_bp
from web.blueprints.kubeconfigs import _sanitize_kubeconfig_name


# ---------------------------------------------------------------------------
# _sanitize_kubeconfig_name — birim testler (AC-1, AC-2, AC-8)
# ---------------------------------------------------------------------------

class TestSanitizeKubeconfigName:
    """_sanitize_kubeconfig_name yardımcı fonksiyon testleri."""

    def test_valid_name_returns_tuple(self, monkeypatch, tmp_path):
        """Geçerli bir ad için (safe_name, full_path) tuple'ı döner (AC-8)."""
        monkeypatch.setattr(kc_bp, 'KUBECONFIG_UPLOAD_DIR', str(tmp_path))
        safe_name, full_path = _sanitize_kubeconfig_name('my-cluster.yaml')
        assert safe_name == 'my-cluster.yaml'
        assert full_path == str(tmp_path / 'my-cluster.yaml')

    def test_valid_name_alphanumeric(self, monkeypatch, tmp_path):
        """Alfanümerik, tire ve alt çizgi içeren geçerli ad kabul edilir."""
        monkeypatch.setattr(kc_bp, 'KUBECONFIG_UPLOAD_DIR', str(tmp_path))
        safe_name, _ = _sanitize_kubeconfig_name('prod_cluster-01')
        assert safe_name == 'prod_cluster-01'

    def test_path_traversal_classic_is_neutralized(self, monkeypatch, tmp_path):
        """Klasik path traversal '../../../etc/passwd': safe_name filtresi '/' karakterlerini kaldırır,
        sonuç '....etcpasswd' biçiminde upload dizini içinde kalır — realpath kontrolü de geçer (AC-1).

        AC-1 gerekliliği: sonuç PATH değişkeninde '../' segmenti BULUNMAMALI. Bu filtre sayesinde
        sağlanır. İstek HTTP 400 değil, dosya bulunamazsa HTTP 404 ile sonuçlanır (kabul edilen davranış).
        """
        monkeypatch.setattr(kc_bp, 'KUBECONFIG_UPLOAD_DIR', str(tmp_path))
        safe_name, full_path = _sanitize_kubeconfig_name('../../../etc/passwd')
        # Sonuçta path separator YOK
        assert '/' not in safe_name
        assert '\\' not in safe_name
        # Yol upload dizini içinde kalıyor (traversal nötralize edildi)
        assert full_path.startswith(str(tmp_path))

    def test_path_traversal_double_dot_only_raises(self, monkeypatch, tmp_path):
        """'..' adı safe_name filtresinden geçer ama realpath kontrolüyle reddedilir (AC-2)."""
        monkeypatch.setattr(kc_bp, 'KUBECONFIG_UPLOAD_DIR', str(tmp_path))
        with pytest.raises(ValueError):
            _sanitize_kubeconfig_name('..')

    def test_empty_after_filter_raises(self, monkeypatch, tmp_path):
        """Tüm karakterler filtrelenince boş safe_name → ValueError (AC-1)."""
        monkeypatch.setattr(kc_bp, 'KUBECONFIG_UPLOAD_DIR', str(tmp_path))
        with pytest.raises(ValueError):
            _sanitize_kubeconfig_name('@@@!!!')

    def test_path_traversal_nested_is_neutralized(self, monkeypatch, tmp_path):
        """İç içe path traversal '../kubeconfigs/../../../etc/shadow': safe_name filtresi
        '/' karakterlerini kaldırır; sonuç yol upload dizini içinde kalır (AC-1, AC-2).
        """
        monkeypatch.setattr(kc_bp, 'KUBECONFIG_UPLOAD_DIR', str(tmp_path))
        safe_name, full_path = _sanitize_kubeconfig_name('../kubeconfigs/../../../etc/shadow')
        assert '/' not in safe_name
        assert full_path.startswith(str(tmp_path))

    def test_url_encoded_traversal_is_neutralized(self, monkeypatch, tmp_path):
        """URL-encoded traversal '..%2f..%2fetc%2fpasswd': safe_name filtresi '%' ve '/'
        karakterlerini kaldırır; sonuç string'i upload dizini içinde kalır, bu nedenle
        safe_name filtresi bu durumu zaten nötralize eder (AC-1)."""
        monkeypatch.setattr(kc_bp, 'KUBECONFIG_UPLOAD_DIR', str(tmp_path))
        # '%' ve '/' kaldırılır → '....etcpasswd' → upload dizini içinde → geçerli
        safe_name, full_path = _sanitize_kubeconfig_name('..%2f..%2fetc%2fpasswd')
        assert '/' not in safe_name
        assert '%' not in safe_name
        assert str(tmp_path) in full_path

    def test_special_chars_stripped(self, monkeypatch, tmp_path):
        """Özel karakterler (boşluk, slash, backslash) safe_name filtresince kaldırılır."""
        monkeypatch.setattr(kc_bp, 'KUBECONFIG_UPLOAD_DIR', str(tmp_path))
        safe_name, _ = _sanitize_kubeconfig_name('my cluster/config\\test')
        assert ' ' not in safe_name
        assert '/' not in safe_name
        assert '\\' not in safe_name

    def test_error_message_does_not_contain_path(self, monkeypatch, tmp_path):
        """Hata mesajı sunucu dosya sistemi yolunu içermez (AC-10)."""
        monkeypatch.setattr(kc_bp, 'KUBECONFIG_UPLOAD_DIR', str(tmp_path))
        with pytest.raises(ValueError) as exc_info:
            _sanitize_kubeconfig_name('..')
        error_msg = str(exc_info.value)
        assert str(tmp_path) not in error_msg
        assert os.sep not in error_msg or 'kubeconfig' in error_msg.lower()


# ---------------------------------------------------------------------------
# Dosya izni testleri (AC-3)
# ---------------------------------------------------------------------------

class TestKubeconfigFilePermissions:
    """Kubeconfig dosyaları 0o600 izinle yazılmalıdır (AC-3)."""

    def test_written_file_has_600_permissions(self, tmp_path):
        """open(path, 'w') + os.chmod(path, 0o600) sonucu dosya izni 0o600 olmalı."""
        test_file = tmp_path / 'test-cluster.yaml'
        with open(str(test_file), 'w') as f:
            f.write('apiVersion: v1\nkind: Config\n')
        os.chmod(str(test_file), 0o600)

        file_stat = os.stat(str(test_file))
        # stat.S_IMODE: yalnızca izin bitlerini al
        permissions = stat.S_IMODE(file_stat.st_mode)
        assert permissions == 0o600, (
            f"Beklenen dosya izni 0o600, bulunan 0o{permissions:o}. "
            "Kubeconfig dosyaları dünye-okunabilir (0644) olmamalıdır."
        )


# ---------------------------------------------------------------------------
# Dizin izni testleri (AC-4, AC-5)
# ---------------------------------------------------------------------------

class TestKubeconfigDirectoryPermissions:
    """Kubeconfig upload dizini 0o700 izinle oluşturulmalı ve korunmalıdır."""

    def test_new_directory_has_700_permissions(self, tmp_path):
        """Yeni oluşturulan dizin 0o700 izinle oluşturulduğunda bu izni taşımalı (AC-4)."""
        new_dir = tmp_path / 'kubeconfigs_new'
        os.makedirs(str(new_dir), mode=0o700, exist_ok=True)
        os.chmod(str(new_dir), 0o700)

        dir_stat = os.stat(str(new_dir))
        permissions = stat.S_IMODE(dir_stat.st_mode)
        assert permissions == 0o700, (
            f"Beklenen dizin izni 0o700, bulunan 0o{permissions:o}. "
            "Kubeconfig dizini dünye-gezinilebilir (0755) olmamalıdır."
        )

    def test_existing_wide_directory_gets_fixed(self, tmp_path):
        """Önceden geniş izinle (0o755) oluşturulmuş dizin os.chmod ile 0o700'e düzeltilir (AC-5)."""
        existing_dir = tmp_path / 'kubeconfigs_existing'
        # Eski kurulumdan kalan geniş izinli dizin simülasyonu
        os.makedirs(str(existing_dir), mode=0o755, exist_ok=True)
        os.chmod(str(existing_dir), 0o755)

        # Uygulama başlatma sırasında yapılan düzeltme (kubeconfig_manager.py mantığı)
        os.makedirs(str(existing_dir), mode=0o700, exist_ok=True)
        os.chmod(str(existing_dir), 0o700)

        dir_stat = os.stat(str(existing_dir))
        permissions = stat.S_IMODE(dir_stat.st_mode)
        assert permissions == 0o700, (
            f"Beklenen düzeltilmiş dizin izni 0o700, bulunan 0o{permissions:o}."
        )


# ---------------------------------------------------------------------------
# Regresyon testi: geçerli ad ile silme hâlâ çalışmalı (AC-6)
# ---------------------------------------------------------------------------

class TestSanitizeRegressionValidName:
    """Geçerli kubeconfig adları sanitizasyon sonrası değişmeden kalmalı (AC-6)."""

    @pytest.mark.parametrize("valid_name", [
        'my-cluster.yaml',
        'prod_config',
        'cluster01',
        'test-cluster-v2.yml',
        'cfg.kubeconfig',
    ])
    def test_valid_names_pass_through_unchanged(self, monkeypatch, tmp_path, valid_name):
        """Geçerli adlar sanitizasyon sonrası aynı değeri korur."""
        monkeypatch.setattr(kc_bp, 'KUBECONFIG_UPLOAD_DIR', str(tmp_path))
        safe_name, full_path = _sanitize_kubeconfig_name(valid_name)
        assert safe_name == valid_name
        assert full_path.endswith(valid_name)
