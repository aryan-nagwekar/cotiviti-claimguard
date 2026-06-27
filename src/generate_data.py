"""Seeded synthetic claims generator for ClaimGuard.

Produces ~200 reproducible synthetic medical claims to data/synthetic_claims.csv,
deliberately injecting rule violations (~17%) and one statistical-outlier provider
so the downstream demo has clear, explainable hits.

ASSUMPTION: This is entirely synthetic data. CPT/ICD codes, charges, and member
demographics are illustrative and bear no relation to real patients or providers.

Run standalone:
    python -m src.generate_data --seed 42
    python src/generate_data.py --seed 42
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUT_CSV = DATA_DIR / "synthetic_claims.csv"

# CPT codes that appear in NO rule -> always clean. Used to pad benign claims.
SAFE_CPTS = ["99212", "85025", "81002", "90658", "99396"]
SAFE_ICDS = ["Z00.00", "E11.9", "I10", "J06.9", "M54.5"]

# Rough per-CPT base charges (illustrative dollars).
BASE_CHARGE = {
    "99212": 75, "99213": 110, "99214": 165, "85025": 35, "81002": 20,
    "90658": 40, "99396": 220, "80048": 45, "80053": 60, "93000": 55,
    "93005": 30, "71046": 90, "36415": 18, "45378": 950, "76801": 280,
    "55700": 700, "99391": 180,
}

PROVIDERS = [f"PRV{n:03d}" for n in range(1, 16)]   # 15 providers
OUTLIER_PROVIDER = "PRV013"                          # bills 36415 far above peers
DATES = [f"2025-0{m}-{d:02d}" for m in (1, 2, 3) for d in range(1, 28)]


def _charge(cpt: str, rng: random.Random) -> float:
    base = BASE_CHARGE.get(cpt, 100)
    return round(base * rng.uniform(0.9, 1.3), 2)


def _row(cid, prov, cpts, icds, units, pos, age, sex, rng):
    """Assemble one claim row. charge scales with the priciest code on the claim."""
    top = max(cpts, key=lambda c: BASE_CHARGE.get(c, 100))
    return {
        "claim_id": cid,
        "provider_id": prov,
        "member_id": f"MBR{rng.randint(1, 200):04d}",
        "dos": rng.choice(DATES),
        "cpt_codes": json.dumps(cpts),
        "icd_codes": json.dumps(icds),
        "units": units,
        "charge_amount": _charge(top, rng) * units,
        "place_of_service": pos,
        "member_age": age,
        "member_sex": sex,
    }


def generate(seed: int = 42) -> pd.DataFrame:
    rng = random.Random(seed)
    rows = []
    n = 0

    def cid() -> str:
        nonlocal n
        n += 1
        return f"CLM{n:05d}"

    # --- 140 benign claims (guaranteed clean) ---
    for _ in range(140):
        cpt = rng.choice(SAFE_CPTS)
        rows.append(_row(
            cid(), rng.choice(PROVIDERS), [cpt], [rng.choice(SAFE_ICDS)],
            1, "11", rng.randint(2, 90), rng.choice(["M", "F"]), rng,
        ))

    # --- 25 outlier claims: PRV013 hammers 36415 (clean per-rule, anomalous stat) ---
    for _ in range(25):
        rows.append(_row(
            cid(), OUTLIER_PROVIDER, ["36415"], ["Z00.00"],
            1, "11", rng.randint(20, 80), rng.choice(["M", "F"]), rng,
        ))
    # A few peer claims with 36415 so the anomaly layer has a real baseline.
    for _ in range(8):
        rows.append(_row(
            cid(), rng.choice([p for p in PROVIDERS if p != OUTLIER_PROVIDER]),
            ["36415"], ["Z00.00"], 1, "11", rng.randint(20, 80),
            rng.choice(["M", "F"]), rng,
        ))

    # --- ~35 injected rule violations ---
    # NCCI-PTP-001: mutually exclusive pairs (8)
    for _ in range(4):
        rows.append(_row(cid(), rng.choice(PROVIDERS), ["80053", "80048"],
                         ["E11.9"], 1, "11", rng.randint(30, 80),
                         rng.choice(["M", "F"]), rng))
    for _ in range(4):
        rows.append(_row(cid(), rng.choice(PROVIDERS), ["93000", "93005"],
                         ["I10"], 1, "11", rng.randint(30, 80),
                         rng.choice(["M", "F"]), rng))

    # FREQ-LIMIT-001: same E/M code billed twice on one claim (7)
    for _ in range(7):
        code = rng.choice(["99213", "99214"])
        rows.append(_row(cid(), rng.choice(PROVIDERS), [code, code],
                         ["M54.5"], 1, "11", rng.randint(30, 80),
                         rng.choice(["M", "F"]), rng))

    # MUE-001: units over cap (7)
    for _ in range(7):
        cpt = rng.choice(["36415", "71046"])
        cap = 1 if cpt == "36415" else 2
        rows.append(_row(cid(), rng.choice(PROVIDERS), [cpt], ["J06.9"],
                         cap + rng.randint(2, 6), "11", rng.randint(30, 80),
                         rng.choice(["M", "F"]), rng))

    # POS-001: colonoscopy billed in office (7)
    for _ in range(7):
        rows.append(_row(cid(), rng.choice(PROVIDERS), ["45378"], ["Z00.00"],
                         1, "11", rng.randint(45, 75),
                         rng.choice(["M", "F"]), rng))

    # AGESEX-001: sex/age inappropriate (6)
    for _ in range(2):  # OB ultrasound billed for a male
        rows.append(_row(cid(), rng.choice(PROVIDERS), ["76801"], ["Z00.00"],
                         1, "22", rng.randint(20, 45), "M", rng))
    for _ in range(2):  # prostate biopsy billed for a female
        rows.append(_row(cid(), rng.choice(PROVIDERS), ["55700"], ["Z00.00"],
                         1, "22", rng.randint(40, 70), "F", rng))
    for _ in range(2):  # infant preventive visit billed for an adult
        rows.append(_row(cid(), rng.choice(PROVIDERS), ["99391"], ["Z00.00"],
                         1, "11", rng.randint(25, 60),
                         rng.choice(["M", "F"]), rng))

    # --- 4 egregious claims that trip MULTIPLE rules -> high risk / DENY (4) ---
    # Unbundled pair + duplicate E/M + colonoscopy in office = 3 violations.
    for _ in range(2):
        rows.append(_row(cid(), rng.choice(PROVIDERS),
                         ["80053", "80048", "99213", "99213", "45378"],
                         ["E11.9"], 1, "11", rng.randint(45, 70),
                         rng.choice(["M", "F"]), rng))
    # Outlier provider PRV013: unbundled pair + MUE over-units (+ anomaly signal).
    for _ in range(2):
        rows.append(_row(cid(), OUTLIER_PROVIDER, ["93000", "93005", "36415"],
                         ["I10"], 6, "11", rng.randint(45, 70),
                         rng.choice(["M", "F"]), rng))

    rng.shuffle(rows)
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate synthetic claims.")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=str, default=str(OUT_CSV))
    args = ap.parse_args()

    df = generate(args.seed)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    print(f"Wrote {len(df)} claims -> {args.out} (seed={args.seed})")
    print(f"Providers: {df['provider_id'].nunique()} | "
          f"Outlier provider (36415): {OUTLIER_PROVIDER}")


if __name__ == "__main__":
    main()
