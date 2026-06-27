"""Orchestrates one claim end-to-end: rules -> anomaly -> agent -> audit.

This is the CLI spine of the demo.

    python src/pipeline.py --claim CLM00177     # one claim, verbose
    python src/pipeline.py --run-all            # whole CSV + summary table
"""
from __future__ import annotations

import argparse
from collections import Counter

from rules_engine import load_policies, load_claims, evaluate_claim
from anomaly import anomalies_by_provider
from agent import decide, AgentDecision
from audit import emit


def process_claim(claim, policies, anomap) -> tuple[AgentDecision, list, object]:
    """Run the full chain for a single claim and emit its audit event."""
    violations = evaluate_claim(claim, policies)
    anomaly = (anomap.get(claim["provider_id"]) or [None])[0]
    decision = decide(claim, violations, anomaly)
    emit(claim, violations, anomaly, decision)
    return decision, violations, anomaly


def run_all() -> None:
    policies = load_policies()
    claims = load_claims()
    anomap = anomalies_by_provider(claims)

    decisions = []
    mode_seen = set()
    for claim in claims:
        d, _, _ = process_claim(claim, policies, anomap)
        decisions.append((claim, d))
        mode_seen.add(d.mode)

    if "live" not in mode_seen:
        print("** Running in FALLBACK mode (no ANTHROPIC_API_KEY or live call "
              "failed). Decisions are deterministic templates. **\n")

    by_action = Counter(d.recommended_action for _, d in decisions)
    print(f"Processed {len(decisions)} claims.")
    print("\nAction counts:")
    for action in ("PAY", "PEND", "DENY", "REVIEW"):
        print(f"  {action:<7}: {by_action.get(action, 0)}")

    print("\nTop 10 highest-risk claims:")
    print(f"  {'claim_id':<10} {'risk':>4}  {'action':<7} {'provider':<8} rules")
    top = sorted(decisions, key=lambda kv: -kv[1].risk_score)[:10]
    for claim, d in top:
        v = evaluate_claim(claim, policies)
        rules = ",".join(sorted({rv.rule_id for rv in v})) or "-"
        print(f"  {d.claim_id:<10} {d.risk_score:>4}  "
              f"{d.recommended_action:<7} {claim['provider_id']:<8} {rules}")

    print("\nAudit events appended to audit_log/events.jsonl "
          "(replay with: python src/audit.py <CLAIM_ID>).")


def run_one(claim_id: str) -> None:
    policies = load_policies()
    claims = load_claims()
    anomap = anomalies_by_provider(claims)
    match = next((c for c in claims if c["claim_id"] == claim_id), None)
    if match is None:
        print(f"Claim {claim_id} not found.")
        return
    d, violations, anomaly = process_claim(match, policies, anomap)
    if d.mode == "fallback":
        print("** FALLBACK mode (deterministic). **\n")
    print(f"Claim {claim_id} | provider {match['provider_id']} | "
          f"CPT {match['cpt_codes']}")
    print(f"Rules fired : {[v.rule_id for v in violations] or 'none'}")
    print(f"Anomaly     : {anomaly.detail if anomaly else 'none'}")
    print(f"Risk score  : {d.risk_score}/100")
    print(f"Action      : {d.recommended_action}  (mode={d.mode})")
    print("\nReasoning:")
    print(d.reasoning)


def main() -> None:
    ap = argparse.ArgumentParser(description="ClaimGuard pipeline.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--run-all", action="store_true", help="process whole CSV")
    g.add_argument("--claim", type=str, help="process a single claim_id")
    args = ap.parse_args()
    if args.run_all:
        run_all()
    else:
        run_one(args.claim)


if __name__ == "__main__":
    main()
