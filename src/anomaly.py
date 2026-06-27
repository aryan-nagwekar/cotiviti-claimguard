"""Statistical peer-outlier detection (pattern recognition, no ML training).

For each CPT code, compare every provider's billing volume against its peers
(other providers billing the same code). A provider whose volume exceeds the
peer upper fence (median + 1.5 * IQR) AND whose z-score is high is flagged.

Simple, explainable stats only — this is the "anomaly detection" requirement.

Run standalone:
    python src/anomaly.py
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, asdict
from statistics import median, pstdev

from rules_engine import load_claims

IQR_K = 1.5        # Tukey fence multiplier
Z_THRESHOLD = 2.0  # standard deviations above peer mean
MIN_PEERS = 3      # need at least this many providers billing a code to compare


@dataclass
class ProviderAnomaly:
    provider_id: str
    cpt: str
    provider_count: int
    peer_median: float
    upper_fence: float
    z_score: float
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


def detect_anomalies(claims: list[dict]) -> list[ProviderAnomaly]:
    # counts[cpt][provider] = number of claims by that provider with that CPT
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for c in claims:
        for cpt in set(c["cpt_codes"]):
            counts[cpt][c["provider_id"]] += 1

    anomalies: list[ProviderAnomaly] = []
    for cpt, by_provider in counts.items():
        vals = list(by_provider.values())
        if len(vals) < MIN_PEERS:
            continue
        vals_sorted = sorted(vals)
        med = median(vals_sorted)
        q1 = median(vals_sorted[: len(vals_sorted) // 2] or vals_sorted)
        q3 = median(vals_sorted[(len(vals_sorted) + 1) // 2:] or vals_sorted)
        iqr = q3 - q1
        upper = med + IQR_K * iqr
        mean = sum(vals) / len(vals)
        sd = pstdev(vals) or 1e-9

        for provider, n in by_provider.items():
            z = (n - mean) / sd
            if n > upper and z >= Z_THRESHOLD:
                anomalies.append(ProviderAnomaly(
                    provider_id=provider, cpt=cpt, provider_count=n,
                    peer_median=med, upper_fence=round(upper, 2),
                    z_score=round(z, 2),
                    detail=(f"Provider {provider} billed CPT {cpt} {n}x vs peer "
                            f"median {med:g} (z={z:.1f}); exceeds upper fence "
                            f"{upper:g}."),
                ))
    return anomalies


def anomalies_by_provider(claims: list[dict]) -> dict[str, list[ProviderAnomaly]]:
    out: dict[str, list[ProviderAnomaly]] = defaultdict(list)
    for a in detect_anomalies(claims):
        out[a.provider_id].append(a)
    return out


def main() -> None:
    claims = load_claims()
    anomalies = detect_anomalies(claims)
    if not anomalies:
        print("No provider anomalies detected.")
        return
    print(f"Detected {len(anomalies)} provider/CPT anomalies:\n")
    for a in sorted(anomalies, key=lambda x: -x.z_score):
        print(f"  [{a.provider_id} / CPT {a.cpt}] {a.detail}")


if __name__ == "__main__":
    main()
