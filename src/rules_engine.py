"""Deterministic payment-integrity rules engine.

Pure functions: given one normalized claim + loaded policies, return the list of
RuleViolations it trips. NO LLM, NO randomness, NO I/O in the check logic.

Run standalone to print violations across the dataset:
    python src/rules_engine.py
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
POLICIES_PATH = ROOT / "data" / "policies.yaml"
CLAIMS_PATH = ROOT / "data" / "synthetic_claims.csv"


@dataclass
class RuleViolation:
    rule_id: str
    name: str
    citation: str
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Loading / normalization
# --------------------------------------------------------------------------- #
def load_policies(path: Path | str = POLICIES_PATH) -> list[dict]:
    with open(path) as f:
        return yaml.safe_load(f)["rules"]


def normalize_claim(row: dict) -> dict:
    """Turn a raw CSV row into a typed claim dict the checks expect.

    cpt_codes / icd_codes -> list[str]; place_of_service -> str; ages -> int.
    """
    def as_list(v: Any) -> list[str]:
        if isinstance(v, list):
            return [str(x) for x in v]
        return [str(x) for x in json.loads(v)]

    return {
        "claim_id": str(row["claim_id"]),
        "provider_id": str(row["provider_id"]),
        "member_id": str(row["member_id"]),
        "dos": str(row["dos"]),
        "cpt_codes": as_list(row["cpt_codes"]),
        "icd_codes": as_list(row["icd_codes"]),
        "units": int(row["units"]),
        "charge_amount": float(row["charge_amount"]),
        "place_of_service": str(row["place_of_service"]),
        "member_age": int(row["member_age"]),
        "member_sex": str(row["member_sex"]),
    }


def load_claims(path: Path | str = CLAIMS_PATH) -> list[dict]:
    df = pd.read_csv(path, dtype={"place_of_service": str})
    return [normalize_claim(r) for r in df.to_dict(orient="records")]


# --------------------------------------------------------------------------- #
# Individual checks (one per rule type)
# --------------------------------------------------------------------------- #
def _check_mutually_exclusive(claim, rule) -> list[RuleViolation]:
    out, codes = [], set(claim["cpt_codes"])
    for a, b in rule["params"]["code_pairs"]:
        if a in codes and b in codes:
            out.append(RuleViolation(
                rule["id"], rule["name"], rule["citation"],
                f"Codes {a} and {b} billed together on claim {claim['claim_id']}.",
            ))
    return out


def _check_frequency_limit(claim, rule) -> list[RuleViolation]:
    out = []
    for code, limit in rule["params"]["per_claim_max"].items():
        count = claim["cpt_codes"].count(code)
        if count > limit:
            out.append(RuleViolation(
                rule["id"], rule["name"], rule["citation"],
                f"CPT {code} appears {count}x (limit {limit}) on this claim/day.",
            ))
    return out


def _check_mue_unit_cap(claim, rule) -> list[RuleViolation]:
    out = []
    for code, cap in rule["params"]["max_units"].items():
        if code in claim["cpt_codes"] and claim["units"] > cap:
            out.append(RuleViolation(
                rule["id"], rule["name"], rule["citation"],
                f"CPT {code} billed {claim['units']} units (MUE cap {cap}).",
            ))
    return out


def _check_pos_mismatch(claim, rule) -> list[RuleViolation]:
    out = []
    allowed_map = rule["params"]["allowed_pos"]
    labels = rule["params"].get("pos_labels", {})
    pos = claim["place_of_service"]
    for code, allowed in allowed_map.items():
        if code in claim["cpt_codes"] and pos not in allowed:
            label = labels.get(pos, pos)
            ok = ", ".join(labels.get(a, a) for a in allowed)
            out.append(RuleViolation(
                rule["id"], rule["name"], rule["citation"],
                f"CPT {code} billed in POS {pos} ({label}); allowed: {ok}.",
            ))
    return out


def _check_age_sex(claim, rule) -> list[RuleViolation]:
    out = []
    for code, c in rule["params"]["constraints"].items():
        if code not in claim["cpt_codes"]:
            continue
        if "sex" in c and claim["member_sex"] != c["sex"]:
            out.append(RuleViolation(
                rule["id"], rule["name"], rule["citation"],
                f"CPT {code} requires sex {c['sex']}; member is "
                f"{claim['member_sex']}.",
            ))
        if "min_age" in c and claim["member_age"] < c["min_age"]:
            out.append(RuleViolation(
                rule["id"], rule["name"], rule["citation"],
                f"CPT {code} requires age >= {c['min_age']}; member is "
                f"{claim['member_age']}.",
            ))
        if "max_age" in c and claim["member_age"] > c["max_age"]:
            out.append(RuleViolation(
                rule["id"], rule["name"], rule["citation"],
                f"CPT {code} requires age <= {c['max_age']}; member is "
                f"{claim['member_age']}.",
            ))
    return out


_DISPATCH = {
    "mutually_exclusive": _check_mutually_exclusive,
    "frequency_limit": _check_frequency_limit,
    "mue_unit_cap": _check_mue_unit_cap,
    "pos_mismatch": _check_pos_mismatch,
    "age_sex": _check_age_sex,
}


def evaluate_claim(claim: dict, policies: list[dict]) -> list[RuleViolation]:
    """Run every policy against one normalized claim."""
    violations: list[RuleViolation] = []
    for rule in policies:
        fn = _DISPATCH.get(rule["type"])
        if fn is None:
            raise ValueError(f"Unknown rule type: {rule['type']}")
        violations.extend(fn(claim, rule))
    return violations


def main() -> None:
    policies = load_policies()
    claims = load_claims()
    flagged = 0
    for claim in claims:
        v = evaluate_claim(claim, policies)
        if v:
            flagged += 1
            print(f"\n{claim['claim_id']} ({claim['provider_id']}) "
                  f"CPT={claim['cpt_codes']} units={claim['units']} "
                  f"POS={claim['place_of_service']} "
                  f"age/sex={claim['member_age']}/{claim['member_sex']}")
            for rv in v:
                print(f"   [{rv.rule_id}] {rv.detail}")
    print(f"\n{flagged}/{len(claims)} claims tripped >=1 rule.")


if __name__ == "__main__":
    main()
