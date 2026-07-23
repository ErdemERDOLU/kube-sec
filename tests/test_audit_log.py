"""tests/test_audit_log.py — record_audit_event() ve get_recent_events() birim testleri (AC-3).

src/web/audit_log.py fonksiyonlarını test eder. Flask bağımlılığı yoktur.
Disk yazma işlemi _flush_to_disk mock'u ile engellenir; gerçek
~/.kube-sec/audit.jsonl dosyasına YAZILMAZ.
"""

import pytest
from unittest.mock import patch

import web.audit_log as _audit_mod
from web.audit_log import record_audit_event, get_recent_events, _audit_deque


@pytest.fixture(autouse=True)
def isolate_deque():
    """Her testten önce ve sonra bellek tamponunu sıfırlar."""
    _audit_deque.clear()
    yield
    _audit_deque.clear()


def test_record_audit_event_adds_entry():
    """record_audit_event() çağrıldıktan sonra get_recent_events() en az 1 kayıt döner
    ve kayıt, girilen alanları doğru şekilde içerir.
    """
    with patch.object(_audit_mod, '_flush_to_disk'):
        record_audit_event(
            action='update',
            resource_type='Deployment',
            resource_name='nginx',
            namespace='default',
            session_id='test-session',
        )

    events = get_recent_events()
    assert len(events) >= 1

    event = events[0]
    assert event['action'] == 'update'
    assert event['resource_type'] == 'Deployment'
    assert event['resource_name'] == 'nginx'
    assert event['namespace'] == 'default'
    assert event['session_id'] == 'test-session'


def test_get_recent_events_limit():
    """5'ten fazla kayıt eklendiğinde get_recent_events(limit=2) tam olarak 2 kayıt döner."""
    with patch.object(_audit_mod, '_flush_to_disk'):
        for i in range(7):
            record_audit_event('delete', 'Pod', f'pod-{i}', 'default', 'session')

    events = get_recent_events(limit=2)
    assert len(events) == 2


def test_get_recent_events_reverse_chronological_order():
    """get_recent_events() dönüş listesinin ilk elemanı en son eklenen kayıt olmalı
    (ters kronolojik sıra).
    """
    with patch.object(_audit_mod, '_flush_to_disk'):
        record_audit_event('update', 'ConfigMap', 'first-resource', 'default', 'session')
        record_audit_event('delete', 'Secret', 'last-resource', 'kube-system', 'session')

    events = get_recent_events()
    assert events[0]['resource_name'] == 'last-resource'
    assert events[-1]['resource_name'] == 'first-resource'
