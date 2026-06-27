"""Rules-engine tests: each rule fires on a violating claim; clean claims pass."""
from rules_engine import evaluate_claim, load_policies, normalize_claim

POLICIES = load_policies()


def _claim(**overrides):
    """A clean baseline claim; override fields to construct violations."""
    base = {
        "claim_id": "TST0001", "provider_id": "PRV001", "member_id": "MBR0001",
        "dos": "2025-01-15", "cpt_codes": ["99212"], "icd_codes": ["Z00.00"],
        "units": 1, "charge_amount": 100.0, "place_of_service": "11",
        "member_age": 40, "member_sex": "F",
    }
    base.update(overrides)
    return normalize_claim(base)


def _ids(violations):
    return {v.rule_id for v in violations}


def test_clean_claim_has_no_violations():
    assert evaluate_claim(_claim(), POLICIES) == []


def test_mutually_exclusive_pair_fires():
    v = evaluate_claim(_claim(cpt_codes=["80053", "80048"]), POLICIES)
    assert "NCCI-PTP-001" in _ids(v)


def test_unbundle_single_code_of_pair_is_clean():
    # Only one half of the pair -> no unbundling violation.
    assert "NCCI-PTP-001" not in _ids(evaluate_claim(_claim(cpt_codes=["80053"]), POLICIES))


def test_frequency_limit_fires_on_duplicate():
    v = evaluate_claim(_claim(cpt_codes=["99213", "99213"]), POLICIES)
    assert "FREQ-LIMIT-001" in _ids(v)


def test_mue_unit_cap_fires():
    v = evaluate_claim(_claim(cpt_codes=["36415"], units=5), POLICIES)
    assert "MUE-001" in _ids(v)


def test_mue_within_cap_is_clean():
    assert "MUE-001" not in _ids(evaluate_claim(_claim(cpt_codes=["36415"], units=1), POLICIES))


def test_pos_mismatch_fires():
    v = evaluate_claim(_claim(cpt_codes=["45378"], place_of_service="11"), POLICIES)
    assert "POS-001" in _ids(v)


def test_pos_allowed_setting_is_clean():
    v = evaluate_claim(_claim(cpt_codes=["45378"], place_of_service="22"), POLICIES)
    assert "POS-001" not in _ids(v)


def test_age_sex_fires_on_wrong_sex():
    v = evaluate_claim(_claim(cpt_codes=["76801"], member_sex="M"), POLICIES)
    assert "AGESEX-001" in _ids(v)


def test_age_sex_fires_on_wrong_age():
    v = evaluate_claim(_claim(cpt_codes=["99391"], member_age=40), POLICIES)
    assert "AGESEX-001" in _ids(v)
