from pathlib import Path
from types import SimpleNamespace

from commercial_studio import MANUAL_WARNING
from cost_router import PricingRegistry
from knowledge_studio import KNOWLEDGE_SALE_WARNING, KnowledgeStudioDraft, build_knowledge_studio_result
from studio import build_package, validate_package_document

BASE_DIR = Path(__file__).resolve().parents[1]
SCHEMA = BASE_DIR.parent / "package-schema" / "package.schema.json"
PRICING = BASE_DIR / "pricing.json"


def test_paid_knowledge_studio_does_not_claim_manual_bearer_fulfillment() -> None:
    pricing = PricingRegistry(PRICING)
    model = next(iter(pricing.models))
    core = SimpleNamespace(
        pricing=pricing,
        PACKAGE_SCHEMA_FILE=SCHEMA,
        build_package=build_package,
        validate_package_document=validate_package_document,
    )
    draft = KnowledgeStudioDraft(
        display_name="Knowledge Sale",
        slug="knowledge-sale-warning",
        instructions="Answer with package Knowledge.",
        knowledge_enabled=True,
        knowledge_text="author-owned reference data",
        access_mode="BUY_ONCE",
        access_price_jpy=500,
        checkout_setup_mode="SELF_SETUP",
        stripe_payment_link_url="https://buy.stripe.com/test_warning",
        stripe_link_matches_configuration=True,
        allowed_payer_modes=["BYOK"],
        default_payer_mode="BYOK",
        default_model=model,
        allowed_models=[model],
        protection_level="LEVEL_4_HOSTED_ONLY",
    )
    result = build_knowledge_studio_result(core=core, payload=draft)
    assert MANUAL_WARNING not in result["warnings"]
    assert KNOWLEDGE_SALE_WARNING in result["warnings"]
