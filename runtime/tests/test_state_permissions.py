import stat
import sys
from pathlib import Path

RUNTIME_DIR = Path(__file__).resolve().parents[1]
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from cost_router import BudgetLedger
from entitlements import EntitlementStore


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_budget_ledger_is_owner_only(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    BudgetLedger(path)
    assert mode(path) & 0o077 == 0


def test_entitlement_store_is_owner_only(tmp_path):
    path = tmp_path / "entitlements.sqlite3"
    EntitlementStore(path)
    assert mode(path) & 0o077 == 0
