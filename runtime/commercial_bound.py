from __future__ import annotations

"""Buyer-only commercial surface with browser-bound Stripe completion.

This keeps the legacy commercial core as the single paid runtime authority while
installing the same initiating-browser proof used by the Creator Studio surface.
No Studio or PACKAGE_TEXT-specific routes are added here.
"""

import commercial as base
from checkout_browser_binding import install_checkout_browser_binding
from external_entitlement_authority import install_external_entitlement_routes

install_checkout_browser_binding(base)
EXTERNAL_ENTITLEMENT_AUTHORITY = install_external_entitlement_routes(base)
app = base.app
