from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


def install_paid_page_guard(base) -> None:
    """Revalidate paid browser authority against the current entitlement state.

    A signed entitlement cookie is only a durable reference to WebAI's payment
    authority. It must never outlive a revoke/expire transition in the
    EntitlementStore. The guard is installed on every canonical commercial
    surface so `/a/{slug}` cannot serve paid UI from stale browser state.
    """

    @base.app.middleware("http")
    async def paid_page_guard(request: Request, call_next):
        if request.method != "GET" or not request.url.path.startswith("/a/"):
            return await call_next(request)

        slug = request.url.path[len("/a/") :].strip("/")
        if not slug or "/" in slug:
            return await call_next(request)

        try:
            app_config = base.core.registry.get(slug)
        except KeyError:
            return await call_next(request)

        if (app_config.get("access") or {}).get("mode") == "FREE":
            return await call_next(request)

        try:
            base.require_secure_transport(request)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

        legacy_token = request.headers.get("X-WebAI-Entitlement", "").strip()
        if base.entitlements.authorize(package_id=slug, token=legacy_token):
            return await call_next(request)

        payment_ref = base.entitlement_payment_ref(request, slug=slug)
        if payment_ref is None:
            return JSONResponse(status_code=401, content={"detail": "Valid buyer access is required"})
        if not base.entitlements.authorize_payment(package_id=slug, payment_ref=payment_ref):
            return JSONResponse(status_code=403, content={"detail": "Buyer access is no longer active"})

        return await call_next(request)
