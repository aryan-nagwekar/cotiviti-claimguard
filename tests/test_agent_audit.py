"""Tests for the deterministic fallback agent scoring and audit emission."""
from agent import fallback_decision
from anomaly import ProviderAnomaly
from audit import emit, events_for_claim
from rules_engine import RuleViolation, normalize_claim


def _claim(**overrides):
    base = {
        "claim_id": "TST0001", "provider_id": "PRV001", "member_id": "MBR0001",
        "dos": "2025-01-15", "cpt_codes": ["99212"], "icd_codes": ["Z00.00"],
        "units": 1, "charge_amount": 100.0, "place_of_service": "11",
        "member_age": 40, "member_sex": "F",
    }
    base.update(overrides)
    return normalize_claim(base)


def _violation(rule_id="MUE-001"):
    return RuleViolation(rule_id, "name", "citation", "detail")


def test_fallback_clean_claim_pays():
    d = fallback_decision(_claim(), [], None, "test")
    assert d.recommended_action == "PAY"
    assert d.mode == "fallback"
    assert d.risk_score < 35


def test_fallback_multiple_violations_denies():
    violations = [_violation("A"), _violation("B"), _violation("C")]
    d = fallback_decision(_claim(), violations, None, "test")
    assert d.recommended_action == "DENY"
    assert d.risk_score >= 70


def test_fallback_anomaly_only_reviews():
    anom = ProviderAnomaly("PRV001", "36415", 20, 2, 6.5, 2.4, "outlier")
    d = fallback_decision(_claim(), [], anom, "test")
    assert d.recommended_action == "REVIEW"


def test_audit_event_is_replayable(tmp_path):
    path = tmp_path / "events.jsonl"
    claim, violations = _claim(), [_violation()]
    decision = fallback_decision(claim, violations, None, "test")

    event = emit(claim, violations, None, decision, path=path)
    required = ("timestamp", "decision_id", "claim_id", "inputs_summary",
                "rules_fired", "anomaly_flag", "model", "mode", "risk_score",
                "recommended_action", "reasoning", "citations")
    for key in required:
        assert key in event, f"missing audit field: {key}"

    # round-trips from disk and is filterable by claim_id
    replayed = events_for_claim(claim["claim_id"], path=path)
    assert len(replayed) == 1
    assert replayed[0]["recommended_action"] == decision.recommended_action
    assert replayed[0]["rules_fired"][0]["rule_id"] == "MUE-001"
