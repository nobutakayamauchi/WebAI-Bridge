from __future__ import annotations

"""Buyer-only commercial surface with browser-bound payment completion.

This keeps the legacy commercial core as the single paid runtime authority while
installing initiating-browser proof for Stripe and a separate secret browser
claim for bank-transfer checkout. No Studio or PACKAGE_TEXT-specific routes are
added here.
"""

import commercial as base
from bank_checkout_binding import install_bank_checkout_binding
from checkout_browser_binding import install_checkout_browser_binding

install_checkout_browser_binding(base)
install_bank_checkout_binding(base)
app = base.app
