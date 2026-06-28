"""Agentic reasoning layer: explanation + risk score + recommended action.

The agent takes a claim, its deterministic rule violations, and any provider
anomaly, then produces a structured, evidence-grounded decision rationale, a
risk_score (0-100), a recommended_action (PAY / PEND / DENY / REVIEW), and the
citations it relied on.

It calls the Anthropic API (model claude-sonnet-4-6) when ANTHROPIC_API_KEY is
set. If the key is missing OR the call/parse fails, it deterministically composes
the SAME fields from the rule + anomaly data (mode="fallback") so the demo never
hard-fails on camera.

Run standalone (prints a few sample decisions; honors the key if present):
    python src/agent.py
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict, field

from rules_engine import RuleViolation
from anomaly import ProviderAnomaly

MODEL = "claude-sonnet-4-6"
ACTIONS = ("PAY", "PEND", "DENY", "REVIEW")


@dataclass
class AgentDecision:
    claim_id: str
    risk_score: int
    recommended_action: str
    reasoning: str
    citations: list[str]
    mode: str                       # "live" or "fallback"
    model: str | None = None
    fallback_reason: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Deterministic fallback (also the source of truth for scoring shape)
# --------------------------------------------------------------------------- #
def _score_and_action(violations, anomaly) -> tuple[int, str]:
    score = min(100, 25 * len(violations) + (20 if anomaly else 0))
    if not violations and not anomaly:
        return 5, "PAY"
    if not violations and anomaly:
        return max(score, 35), "REVIEW"
    if score >= 70:
        return score, "DENY"
    return score, "PEND"


def fallback_decision(claim, violations, anomaly, reason: str) -> AgentDecision:
    score, action = _score_and_action(violations, anomaly)
    citations = [v.citation for v in violations]

    parts = [f"Claim {claim['claim_id']} from provider {claim['provider_id']}."]
    if violations:
        parts.append(f"It tripped {len(violations)} policy rule(s):")
        for v in violations:
            parts.append(f"  - {v.name} [{v.rule_id}]: {v.detail}")
    else:
        parts.append("No deterministic policy rules were tripped.")
    if anomaly:
        parts.append(f"Provider anomaly: {anomaly.detail}")
    parts.append(f"=> risk {score}/100, recommend {action}.")

    return AgentDecision(
        claim_id=claim["claim_id"], risk_score=score, recommended_action=action,
        reasoning="\n".join(parts), citations=citations, mode="fallback",
        model=None, fallback_reason=reason,
    )


# --------------------------------------------------------------------------- #
# Live LLM path
# --------------------------------------------------------------------------- #
def _build_prompt(claim, violations, anomaly) -> str:
    v_lines = "\n".join(
        f"- {v.rule_id} ({v.name}): {v.detail} | citation: {v.citation}"
        for v in violations
    ) or "- none"
    a_line = anomaly.detail if anomaly else "none"
    return f"""You are a payment-integrity claims-review agent for a health plan.
Produce a structured decision rationale grounded in the evidence below (the rules
triggered, their citations, and the anomaly signal), then output a single decision.

CLAIM FACTS:
- claim_id: {claim['claim_id']}
- provider_id: {claim['provider_id']}
- member: age {claim['member_age']}, sex {claim['member_sex']}
- CPT codes: {claim['cpt_codes']}
- ICD codes: {claim['icd_codes']}
- units: {claim['units']}
- place_of_service: {claim['place_of_service']}
- charge_amount: {claim['charge_amount']}

DETERMINISTIC RULE VIOLATIONS (from the rules engine):
{v_lines}

PROVIDER ANOMALY SIGNAL (statistical):
{a_line}

Decide a recommended_action from exactly: PAY, PEND, DENY, REVIEW.
- PAY: no concerns. DENY: clear, multiple/serious violations.
- PEND: needs documentation before payment. REVIEW: anomaly without a hard rule hit.
Assign risk_score 0-100. Cite the policy citations you relied on (verbatim strings).

Respond with ONLY a JSON object, no prose, no markdown fences:
{{"reasoning": "<structured decision rationale grounded in the rules, citations, and anomaly>", "risk_score": <int 0-100>,
"recommended_action": "<PAY|PEND|DENY|REVIEW>", "citations": ["<citation>", ...]}}"""


def _parse_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in response")
    data = json.loads(text[start:end + 1])
    action = str(data["recommended_action"]).upper()
    if action not in ACTIONS:
        raise ValueError(f"invalid action: {action}")
    score = int(data["risk_score"])
    if not 0 <= score <= 100:
        raise ValueError(f"score out of range: {score}")
    return {
        "reasoning": str(data["reasoning"]),
        "risk_score": score,
        "recommended_action": action,
        "citations": [str(c) for c in data.get("citations", [])],
    }


def decide(claim, violations: list[RuleViolation],
           anomaly: ProviderAnomaly | None = None) -> AgentDecision:
    """Produce an AgentDecision, preferring the live LLM, falling back safely."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return fallback_decision(claim, violations, anomaly,
                                 "ANTHROPIC_API_KEY not set")
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(
            model=MODEL, max_tokens=1024,
            messages=[{"role": "user",
                       "content": _build_prompt(claim, violations, anomaly)}],
        )
        parsed = _parse_response(msg.content[0].text)
        return AgentDecision(
            claim_id=claim["claim_id"], mode="live", model=MODEL, **parsed,
        )
    except Exception as e:  # network, parse, auth, anything -> safe fallback
        return fallback_decision(claim, violations, anomaly,
                                 f"live call failed: {type(e).__name__}: {e}")


def main() -> None:
    from rules_engine import load_policies, load_claims, evaluate_claim
    from anomaly import anomalies_by_provider

    policies = load_policies()
    claims = load_claims()
    anomap = anomalies_by_provider(claims)

    # Show a couple of flagged claims so the output is interesting.
    shown = 0
    for claim in claims:
        v = evaluate_claim(claim, policies)
        anom = (anomap.get(claim["provider_id"]) or [None])[0]
        if not v and not anom:
            continue
        d = decide(claim, v, anom)
        print(f"\n=== {d.claim_id} [{d.mode}] risk={d.risk_score} "
              f"action={d.recommended_action} ===")
        print(d.reasoning)
        if d.fallback_reason:
            print(f"(fallback reason: {d.fallback_reason})")
        shown += 1
        if shown >= 3:
            break


if __name__ == "__main__":
    main()
