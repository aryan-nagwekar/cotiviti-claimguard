"""Governance layer: structured, replayable audit events for every decision.

This is the strategic centerpiece. For every AgentDecision we append one JSON
line to audit_log/events.jsonl containing enough context to reconstruct WHY a
decision was made: the claim summary, rules fired (with citations), anomaly flag,
model + mode, risk score, action, reasoning, and citations.

Run standalone to pretty-print the trail for a claim:
    python src/audit.py CLM00177
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agent import AgentDecision
from rules_engine import RuleViolation
from anomaly import ProviderAnomaly

ROOT = Path(__file__).resolve().parent.parent
AUDIT_LOG = ROOT / "audit_log" / "events.jsonl"


def _claim_summary(claim: dict) -> dict:
    return {
        "claim_id": claim["claim_id"],
        "provider_id": claim["provider_id"],
        "member_id": claim["member_id"],
        "dos": claim["dos"],
        "cpt_codes": claim["cpt_codes"],
        "icd_codes": claim["icd_codes"],
        "units": claim["units"],
        "charge_amount": claim["charge_amount"],
        "place_of_service": claim["place_of_service"],
        "member_age": claim["member_age"],
        "member_sex": claim["member_sex"],
    }


def emit(claim: dict, violations: list[RuleViolation],
         anomaly: ProviderAnomaly | None, decision: AgentDecision,
         path: Path | str = AUDIT_LOG) -> dict:
    """Append one replayable audit event and return it."""
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "decision_id": str(uuid.uuid4()),
        "claim_id": claim["claim_id"],
        "inputs_summary": _claim_summary(claim),
        "rules_fired": [v.to_dict() for v in violations],
        "anomaly_flag": anomaly.to_dict() if anomaly else None,
        "model": decision.model,
        "mode": decision.mode,
        "risk_score": decision.risk_score,
        "recommended_action": decision.recommended_action,
        "reasoning": decision.reasoning,
        "citations": decision.citations,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(event) + "\n")
    return event


def read_events(path: Path | str = AUDIT_LOG) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def events_for_claim(claim_id: str, path: Path | str = AUDIT_LOG) -> list[dict]:
    return [e for e in read_events(path) if e["claim_id"] == claim_id]


def pretty_print_trail(claim_id: str, path: Path | str = AUDIT_LOG) -> None:
    events = events_for_claim(claim_id, path)
    if not events:
        print(f"No audit events for {claim_id}.")
        return
    for e in events:
        print("=" * 70)
        print(f"decision_id : {e['decision_id']}")
        print(f"timestamp   : {e['timestamp']}")
        print(f"claim_id    : {e['claim_id']}")
        print(f"mode/model  : {e['mode']} / {e['model']}")
        print(f"risk/action : {e['risk_score']} -> {e['recommended_action']}")
        s = e["inputs_summary"]
        print(f"claim       : {s['provider_id']} CPT={s['cpt_codes']} "
              f"units={s['units']} POS={s['place_of_service']} "
              f"age/sex={s['member_age']}/{s['member_sex']}")
        print(f"rules_fired : {[r['rule_id'] for r in e['rules_fired']]}")
        print(f"anomaly     : {bool(e['anomaly_flag'])}")
        print("reasoning   :")
        for line in e["reasoning"].splitlines():
            print(f"    {line}")
        if e["citations"]:
            print("citations   :")
            for c in e["citations"]:
                print(f"    - {c}")
    print("=" * 70)


def main() -> None:
    if len(sys.argv) < 2:
        events = read_events()
        print(f"{len(events)} audit events in {AUDIT_LOG}.")
        print("Usage: python src/audit.py <CLAIM_ID>   (pretty-print a trail)")
        return
    pretty_print_trail(sys.argv[1])


if __name__ == "__main__":
    main()
