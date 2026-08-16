from pathlib import Path

from handoff_tickets import HandoffTicketStore


def test_handoff_ticket_is_one_time_and_expires(tmp_path: Path):
    store = HandoffTicketStore(tmp_path / "handoff.sqlite3", ttl_seconds=60)
    ticket = store.issue(package_id="paid-ai", payment_ref="pi_123", now=1000)
    assert ticket.startswith("handoff_")
    assert store.consume(package_id="paid-ai", ticket=ticket, now=1010) == "pi_123"
    assert store.consume(package_id="paid-ai", ticket=ticket, now=1011) is None

    expired = store.issue(package_id="paid-ai", payment_ref="pi_456", now=2000)
    assert store.consume(package_id="paid-ai", ticket=expired, now=2060) is None


def test_handoff_ticket_is_package_bound_and_plaintext_not_stored(tmp_path: Path):
    path = tmp_path / "handoff.sqlite3"
    store = HandoffTicketStore(path, ttl_seconds=60)
    ticket = store.issue(package_id="paid-ai", payment_ref="pi_123", now=1000)
    assert store.consume(package_id="other-ai", ticket=ticket, now=1010) is None
    assert ticket.encode("utf-8") not in path.read_bytes()
