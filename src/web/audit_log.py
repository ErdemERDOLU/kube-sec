"""audit_log.py — Audit Trail persistence modülü.

Flask/blueprint'e HİÇBİR bağımlılık yoktur. Saf Python:
collections, threading, json, pathlib, datetime, logging, hashlib.

Public API:
    record_audit_event(action, resource_type, resource_name, namespace,
                       session_id, details=None) -> None
    get_recent_events(limit=100) -> list[dict]
    _short_session_id(raw_cookie) -> str   (her blueprint tarafından kullanılabilir)

Persistence stratejisi (Spec Bölüm 3.3):
    - Birincil: collections.deque(maxlen=500) — süreç içi hızlı okuma.
    - İkincil: ~/.kube-sec/audit.jsonl — append-only JSON Lines dosyası.
    - Modül import edildiğinde disk dosyasından son 500 satır yüklenir (_load_from_disk).
    - Dosya boyutu 5 MB'yi aştığında rotation yapılır (audit.jsonl.1).
    - Disk yazma işlemi daemon Thread ile asenkrondur (Spec R-1).
"""

import collections
import hashlib
import json
import logging
import os
import pathlib
import threading
from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Tip takma adı (Spec 3.1)
# ---------------------------------------------------------------------------
AuditEvent = dict  # {timestamp, action, resource_type, resource_name, namespace, session_id, details}

# ---------------------------------------------------------------------------
# Logger — AC-7 kriteri
# ---------------------------------------------------------------------------
_logger = logging.getLogger('audit')

# ---------------------------------------------------------------------------
# Disk konumu (Spec 3.5)
# ---------------------------------------------------------------------------


def _get_audit_log_dir() -> pathlib.Path:
    """Kullanıcı home dizini altında .kube-sec/ klasörünü döndürür, yoksa oluşturur."""
    base = pathlib.Path.home() / '.kube-sec'
    base.mkdir(parents=True, exist_ok=True)
    return base


AUDIT_LOG_FILE: str = str(_get_audit_log_dir() / 'audit.jsonl')

# ---------------------------------------------------------------------------
# Bellek tamponu ve kilit (Spec 3.1)
# ---------------------------------------------------------------------------
_audit_deque: collections.deque = collections.deque(maxlen=500)
_audit_lock: threading.Lock = threading.Lock()
_disk_lock: threading.Lock = threading.Lock()

# ---------------------------------------------------------------------------
# Yardımcı: kısa oturum kimliği (Spec Bölüm 4.4)
# ---------------------------------------------------------------------------


def _short_session_id(raw_cookie: Optional[str]) -> str:
    """Flask session cookie'sinin ham değerinden 8 karakterlik kısa bir kimlik üretir.

    Args:
        raw_cookie: Her blueprint'te ``request.cookies.get('session')`` ile elde edilen
                    ham cookie değeri. None veya boş string ise ``'local'`` döner.

    Returns:
        str: SHA-256 hash'inin ilk 8 karakteri veya ``'local'``.

    Note:
        Bu fonksiyon ``flask.request``'e erişmez; parametre olarak ham cookie değerini
        alır. Böylece modül Flask-bağımsız kalır ve arka plan thread'lerinden de
        güvenle çağrılabilir.
    """
    if not raw_cookie:
        return 'local'
    return hashlib.sha256(raw_cookie.encode()).hexdigest()[:8]

# ---------------------------------------------------------------------------
# Disk I/O yardımcıları
# ---------------------------------------------------------------------------


def _rotate_if_needed() -> None:
    """audit.jsonl 5 MB'yi aştığında audit.jsonl.1 olarak yeniden adlandırır (Spec 3.4, AC-15).

    Maksimum 2 dosya (toplamda ~10 MB) tutulur.
    Eski .1 dosyası varsa önce silinir.
    I/O hatası sessizce loglanır; olaylar bellek tamponunda korunur.
    """
    try:
        if os.path.exists(AUDIT_LOG_FILE) and os.path.getsize(AUDIT_LOG_FILE) >= 5 * 1024 * 1024:
            rotated = AUDIT_LOG_FILE + '.1'
            if os.path.exists(rotated):
                os.remove(rotated)
            os.rename(AUDIT_LOG_FILE, rotated)
            _logger.info('[AUDIT] rotation: audit.jsonl -> audit.jsonl.1')
    except OSError as exc:
        _logger.warning('[AUDIT] rotation hatasi: %s', exc)


def _flush_to_disk(event: AuditEvent) -> None:
    """Tek bir olayı AUDIT_LOG_FILE'a append-only JSON Lines olarak yazar (Spec 3.2).

    Args:
        event: Diske yazılacak AuditEvent dict nesnesi.

    Note:
        I/O hatası durumunda sessizce loglanır; olay deque'de mevcuttur (bellek kaybı olmaz).
        Rotasyon kontrolü ve yazma işlemi, eşzamanlı daemon thread'lerin (örn. toplu silme
        sırasında) birbirinin rotasyonunu bozmaması için _disk_lock ile korunur.
    """
    try:
        with _disk_lock:
            _rotate_if_needed()
            with open(AUDIT_LOG_FILE, 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + '\n')
    except OSError as exc:
        _logger.warning('[AUDIT] diske yazma hatasi: %s', exc)

# ---------------------------------------------------------------------------
# Başlangıçta diskten yükle (Spec 3.3, AC-11)
# ---------------------------------------------------------------------------


def _load_from_disk() -> None:
    """Modül import edildiğinde audit.jsonl'den son 500 satırı okuyup deque'yi doldurur.

    Dosya mevcut değilse boş başlar. Bozuk JSON satırları sessizce atlanır.
    """
    if not os.path.exists(AUDIT_LOG_FILE):
        return
    try:
        with open(AUDIT_LOG_FILE, 'r', encoding='utf-8') as fh:
            lines = fh.readlines()
        # Son 500 satırı al (deque maxlen ile tutarlı)
        for line in lines[-500:]:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                _audit_deque.append(event)
            except json.JSONDecodeError:
                pass  # Bozuk satırları sessizce atla
        _logger.debug('[AUDIT] diskten %d kayit yuklendi.', len(_audit_deque))
    except OSError as exc:
        _logger.warning('[AUDIT] diskten yukleme hatasi: %s', exc)

# ---------------------------------------------------------------------------
# Public API (Spec 3.2)
# ---------------------------------------------------------------------------


def record_audit_event(
    action: str,
    resource_type: str,
    resource_name: str,
    namespace: Optional[str],
    session_id: Optional[str],
    details: Optional[str] = None,
) -> None:
    """Bir audit olayını bellek tamponuna ve diske kaydeder.

    Args:
        action: Yapılan işlem türü.
                Geçerli değerler: 'update', 'delete', 'scale', 'restart', 'cordon',
                'uncordon', 'drain', 'yaml_update', 'install', 'scan_trigger',
                'add', 'activate'.
        resource_type: Etkilenen Kubernetes kaynak türü
                       (örn. 'Deployment', 'ConfigMap', 'Secret', 'Node', 'Kubeconfig').
        resource_name: Kaynağın adı.
        namespace: Kaynağın namespace'i. Cluster-scoped kaynaklar için None geçilebilir.
        session_id: Kısa oturum kimliği (8 karakter hash veya 'local' veya 'system').
                    Dışarıdan verilir; bu fonksiyon flask.request'e erişmez.
        details: Opsiyonel ek bilgi (örn. 'replicas: 3 -> 5', 'min_available=1').
                 Hassas veri (secret değerleri, token'lar) ASLA eklenmemelidir.

    Note:
        - Flask/blueprint'e bağımlılık yoktur (Spec Bölüm 11.4).
        - Thread-safe: _audit_lock ile korunur (Spec Bölüm 11.2).
        - Disk yazma daemon Thread ile asenkrondur (Spec R-1).
        - Sunucu logu [AUDIT] ön ekiyle yazılır (Spec Bölüm 11.3, AC-7).
    """
    event: AuditEvent = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'action': action,
        'resource_type': resource_type,
        'resource_name': resource_name,
        'namespace': namespace,
        'session_id': session_id,
        'details': details,
    }

    # Thread-safe bellek tamponu güncellemesi (Spec Bölüm 11.2)
    with _audit_lock:
        _audit_deque.append(event)

    # AC-7: Sunucu logu — hassas veri içermez
    _logger.info(
        '[AUDIT] action=%s resource_type=%s resource_name=%s namespace=%s session=%s',
        action,
        resource_type,
        resource_name,
        namespace,
        session_id,
    )

    # Asenkron disk yazımı (Spec R-1) — yanıt süresini etkilemez
    t = threading.Thread(target=_flush_to_disk, args=(event,), daemon=True)
    t.start()


def get_recent_events(limit: int = 100) -> list:
    """Bellek tamponundaki son N kaydı ters kronolojik sırada (en yeni önce) döndürür.

    Args:
        limit: Döndürülecek maksimum kayıt sayısı. Varsayılan 100 (UI gösterimi için).
               Bellek tamponu 500 kayıt saklar; bu parametre yalnızca döndürülen
               listeyi kırpar.

    Returns:
        list[AuditEvent]: En yeni kayıt başta olmak üzere sıralanmış AuditEvent listesi.
    """
    if limit <= 0:
        return []

    with _audit_lock:
        # Deque anlık kopyasını al (kilidi uzun tutmamak için)
        all_events = list(_audit_deque)

    # Son limit kadar al ve ters sıraya çevir (en yeni önce)
    recent = all_events[-limit:] if len(all_events) > limit else all_events
    return list(reversed(recent))


# ---------------------------------------------------------------------------
# Modül yüklenirken diskten başlat (Spec 3.3, AC-11)
# ---------------------------------------------------------------------------
_load_from_disk()
