from package_knowledge import retrieve_chunks


def test_retrieve_chunks_matches_component_inside_underscore_compound() -> None:
    text = "ACCEPTANCE_SECRET_PHRASE = ORACLE_FIXED_DOMAIN_SECOND_PRODUCT_20260818"

    chunks = retrieve_chunks(text, "The environment is ORACLE, AWS, or AZURE. Which one?")

    assert chunks == [text]


def test_retrieve_chunks_matches_component_inside_hyphen_compound() -> None:
    text = "Deployment marker: TOKYO-EDGE-CANARY-20260818"

    chunks = retrieve_chunks(text, "Is this the TOKYO deployment?")

    assert chunks == [text]


def test_compound_exact_match_still_works() -> None:
    text = "Deployment marker: ORACLE_FIXED_DOMAIN_SECOND_PRODUCT_20260818"

    chunks = retrieve_chunks(text, "ORACLE_FIXED_DOMAIN_SECOND_PRODUCT_20260818")

    assert chunks == [text]
