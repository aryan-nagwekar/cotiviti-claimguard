"""ClaimGuard demo dashboard (Streamlit).

A sortable, risk-ranked table of claims. Select a claim to see the agent's
reasoning, the rules it tripped (with citations), the anomaly signal, and the raw
audit event. Includes a human-in-the-loop Approve/Override control (in-memory).

Run:
    streamlit run app/dashboard.py

NOTE: For a fast, bulletproof demo the table is built from the DETERMINISTIC
agent path (no API calls on load). Use "Re-run via live agent" on a selected
claim to exercise the Anthropic API when ANTHROPIC_API_KEY is set.
"""
from __future__ import annotations

import html
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from rules_engine import load_policies, load_claims, evaluate_claim   # noqa: E402
from anomaly import anomalies_by_provider                            # noqa: E402
from agent import decide, fallback_decision                         # noqa: E402
from audit import emit, events_for_claim                            # noqa: E402

# action -> (text color, soft background)
ACTION_STYLE = {
    "PAY":    ("#1F8A55", "#E6F5EC"),
    "PEND":   ("#B9740A", "#FBF1DF"),
    "REVIEW": ("#1F6FE0", "#E7F0FD"),
    "DENY":   ("#C0392B", "#FBE9E7"),
}


def badge(action: str) -> str:
    fg, bg = ACTION_STYLE.get(action, ("#444", "#eee"))
    return (f"<span style='background:{bg};color:{fg};padding:3px 12px;"
            f"border-radius:999px;font-weight:700;font-size:12px;"
            f"letter-spacing:.03em'>{action}</span>")


def chip(label: str, value: str) -> str:
    return (f"<span style='display:inline-block;background:#EEF2F5;"
            f"border:1px solid #E0E7EC;border-radius:8px;padding:4px 10px;"
            f"margin:0 6px 6px 0;font-size:13px;color:#3A4A56'>"
            f"<b style='color:#11808D'>{html.escape(label)}</b> "
            f"{html.escape(value)}</span>")


@st.cache_data
def build_table():
    """Deterministic per-claim decisions for the whole dataset (fast, no API)."""
    policies = load_policies()
    claims = load_claims()
    anomap = anomalies_by_provider(claims)
    rows, ctx = [], {}
    for c in claims:
        v = evaluate_claim(c, policies)
        anom = (anomap.get(c["provider_id"]) or [None])[0]
        d = fallback_decision(c, v, anom, "dashboard deterministic view")
        ctx[c["claim_id"]] = (c, v, anom)
        rows.append({
            "claim_id": c["claim_id"],
            "provider": c["provider_id"],
            "risk": d.risk_score,
            "action": d.recommended_action,
            "rules": ", ".join(sorted({rv.rule_id for rv in v})) or "—",
            "anomaly": "⚠" if anom else "",
            "cpt_codes": ", ".join(c["cpt_codes"]),
        })
    df = pd.DataFrame(rows).sort_values("risk", ascending=False).reset_index(drop=True)
    return df, ctx


# --------------------------------------------------------------------------- #
# Page chrome
# --------------------------------------------------------------------------- #
st.set_page_config(page_title="ClaimGuard", layout="wide", page_icon="🛡️")

st.markdown("""
<style>
  .block-container { padding-top: 2rem; max-width: 1320px; }
  #MainMenu, footer, header { visibility: hidden; }
  .cg-header {
    background: linear-gradient(120deg, #0C5C68 0%, #11808D 55%, #169AA1 100%);
    color: #fff; border-radius: 16px; padding: 24px 28px; margin-bottom: 18px;
    box-shadow: 0 6px 20px rgba(12,92,104,.18);
  }
  .cg-header h1 { font-size: 26px; margin: 0; font-weight: 800; letter-spacing:-.01em;}
  .cg-header p  { margin: 6px 0 0; opacity: .92; font-size: 14px; max-width: 760px;}
  .cg-pill {
    display:inline-block; margin-top:12px; background: rgba(255,255,255,.16);
    border:1px solid rgba(255,255,255,.35); border-radius:999px;
    padding:4px 14px; font-size:12.5px; font-weight:600;
  }
  .kpi-wrap { display:flex; gap:14px; margin-bottom:8px; flex-wrap:wrap; }
  .kpi {
    flex:1; min-width:150px; background:#fff; border:1px solid #E3E9ED;
    border-top:4px solid var(--c); border-radius:12px; padding:14px 18px;
    box-shadow:0 1px 2px rgba(16,40,60,.04);
  }
  .kpi .l { font-size:11.5px; text-transform:uppercase; letter-spacing:.07em;
            color:#6B7B88; font-weight:700; }
  .kpi .v { font-size:30px; font-weight:800; line-height:1; margin-top:6px; color:#16242E;}
  .panel { background:#fff; border:1px solid #E3E9ED; border-radius:14px;
           padding:18px 20px; box-shadow:0 1px 2px rgba(16,40,60,.04);}
  .reason-box { background:#F7FAFB; border-left:4px solid #11808D; border-radius:8px;
                padding:12px 14px; font-size:13.5px; color:#2A3A46; white-space:pre-wrap;
                font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  .rule-card { background:#FCFDFD; border:1px solid #E6ECF0; border-radius:10px;
               padding:10px 13px; margin-bottom:9px; }
  .rule-card .rid { display:inline-block; background:#11808D; color:#fff;
                    border-radius:6px; padding:1px 8px; font-size:11px; font-weight:700;
                    letter-spacing:.03em; margin-right:8px;}
  .rule-card .nm { font-weight:600; color:#16242E; font-size:13.5px;}
  .rule-card .dt { font-size:13px; color:#34454F; margin-top:5px;}
  .rule-card .ct { font-size:11.5px; color:#7A8A95; font-style:italic; margin-top:5px;}
  .anom-box { background:#FBF4E6; border:1px solid #F0DFB8; border-radius:10px;
              padding:11px 14px; font-size:13px; color:#8A5B12;}
  .sec { font-size:12px; text-transform:uppercase; letter-spacing:.07em;
         color:#6B7B88; font-weight:700; margin:14px 0 7px;}
</style>
""", unsafe_allow_html=True)

key_set = bool(os.environ.get("ANTHROPIC_API_KEY"))
mode_label = ("● LIVE — Anthropic API available" if key_set
              else "● FALLBACK — deterministic (no API key set)")
st.markdown(f"""
<div class="cg-header">
  <h1>🛡️ ClaimGuard — Agentic Claims Review</h1>
  <p>Deterministic rules + statistical anomaly detection + an LLM agent that
     explains, scores, and recommends — and <b>every decision is audited</b>.</p>
  <span class="cg-pill">{mode_label} · table uses the deterministic path for speed</span>
</div>
""", unsafe_allow_html=True)

st.caption("⚠️ Demo uses synthetic claims and illustrative policy edits only. "
           "Not for real claims adjudication.")

df, ctx = build_table()

# --- KPI cards ---
counts = df["action"].value_counts()
kpis = [
    ("Claims", len(df), "#11808D"),
    ("PAY", int(counts.get("PAY", 0)), ACTION_STYLE["PAY"][0]),
    ("PEND", int(counts.get("PEND", 0)), ACTION_STYLE["PEND"][0]),
    ("REVIEW", int(counts.get("REVIEW", 0)), ACTION_STYLE["REVIEW"][0]),
    ("DENY", int(counts.get("DENY", 0)), ACTION_STYLE["DENY"][0]),
]
cards = "".join(
    f"<div class='kpi' style='--c:{c}'><div class='l'>{l}</div>"
    f"<div class='v'>{v}</div></div>" for l, v, c in kpis
)
st.markdown(f"<div class='kpi-wrap'>{cards}</div>", unsafe_allow_html=True)

left, right = st.columns([3, 2], gap="large")

# --------------------------------------------------------------------------- #
# Left: risk-ranked table
# --------------------------------------------------------------------------- #
with left:
    st.markdown("<div class='sec'>Claims · ranked by risk</div>",
                unsafe_allow_html=True)
    only_flagged = st.checkbox("Show only flagged claims (risk ≥ 35)", value=True)
    view = df[df["risk"] >= 35] if only_flagged else df

    def _action_css(v):
        fg, bg = ACTION_STYLE.get(v, ("#333", "#eee"))
        return f"background-color:{bg};color:{fg};font-weight:700;"

    def _risk_css(v):
        c = ("#C0392B" if v >= 70 else "#B9740A" if v >= 40
             else "#1F6FE0" if v >= 35 else "#1F8A55")
        return f"color:{c};font-weight:800;"

    styler = (view.style
              .map(_action_css, subset=["action"])
              .map(_risk_css, subset=["risk"]))
    st.dataframe(
        styler, use_container_width=True, height=520, hide_index=True,
        column_config={
            "claim_id": "Claim",
            "provider": "Provider",
            "risk": st.column_config.NumberColumn("Risk", width="small"),
            "action": "Action",
            "rules": "Rules fired",
            "anomaly": st.column_config.TextColumn("Anom.", width="small"),
            "cpt_codes": "CPT",
        },
    )

# --------------------------------------------------------------------------- #
# Right: claim detail
# --------------------------------------------------------------------------- #
with right:
    st.markdown("<div class='sec'>Claim detail</div>", unsafe_allow_html=True)
    claim_id = st.selectbox("Select a claim", df["claim_id"].tolist(), index=0)
    claim, violations, anomaly = ctx[claim_id]
    decision = fallback_decision(claim, violations, anomaly, "dashboard view")

    if st.button("🤖 Re-run via live agent", use_container_width=True):
        with st.spinner("Calling agent…"):
            decision = decide(claim, violations, anomaly)
            emit(claim, violations, anomaly, decision)
        st.success(f"Agent returned (mode={decision.mode}).")
        if decision.fallback_reason:
            st.warning(f"Fell back: {decision.fallback_reason}")

    fg, bg = ACTION_STYLE.get(decision.recommended_action, ("#444", "#eee"))
    st.markdown(f"""
    <div style="background:{bg};border-left:6px solid {fg};border-radius:12px;
                padding:14px 18px;margin:4px 0 12px;">
      <div style="font-size:12px;color:#6B7B88;font-weight:700;
                  text-transform:uppercase;letter-spacing:.06em">
        {html.escape(claim_id)} · agent recommendation</div>
      <div style="display:flex;align-items:baseline;gap:14px;margin-top:4px">
        <span style="font-size:26px;font-weight:800;color:{fg}">
          {decision.recommended_action}</span>
        <span style="font-size:15px;color:#46545E">risk
          <b style="color:{fg}">{decision.risk_score}</b>/100 ·
          mode {decision.mode}</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    chips = (chip("Provider", claim["provider_id"])
             + chip("Member", f"{claim['member_age']}/{claim['member_sex']}")
             + chip("POS", claim["place_of_service"])
             + chip("Units", str(claim["units"]))
             + chip("CPT", ", ".join(claim["cpt_codes"])))
    st.markdown(f"<div>{chips}</div>", unsafe_allow_html=True)

    st.markdown("<div class='sec'>Agent reasoning</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='reason-box'>{html.escape(decision.reasoning)}</div>",
                unsafe_allow_html=True)

    if violations:
        st.markdown("<div class='sec'>Rules tripped · with citations</div>",
                    unsafe_allow_html=True)
        for v in violations:
            st.markdown(f"""
            <div class="rule-card">
              <span class="rid">{html.escape(v.rule_id)}</span>
              <span class="nm">{html.escape(v.name)}</span>
              <div class="dt">{html.escape(v.detail)}</div>
              <div class="ct">{html.escape(v.citation)}</div>
            </div>""", unsafe_allow_html=True)

    if anomaly:
        st.markdown("<div class='sec'>Anomaly signal</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='anom-box'>⚠ {html.escape(anomaly.detail)}</div>",
                    unsafe_allow_html=True)

    # --- Human-in-the-loop ---
    st.markdown("<div class='sec'>🧑‍⚖️ Human-in-the-loop</div>",
                unsafe_allow_html=True)
    if "dispositions" not in st.session_state:
        st.session_state.dispositions = {}
    choice = st.radio("Reviewer action",
                      ["Approve agent recommendation", "Override"],
                      key=f"hil_{claim_id}", horizontal=True)
    if choice == "Override":
        final = st.selectbox("Override action", list(ACTION_STYLE),
                             key=f"ovr_{claim_id}")
    else:
        final = decision.recommended_action
    if st.button("Record disposition", key=f"rec_{claim_id}",
                 use_container_width=True):
        st.session_state.dispositions[claim_id] = final
        st.success(f"Recorded: {claim_id} → {final} (in-memory only)")
    if st.session_state.dispositions:
        st.caption("Session dispositions: "
                   + " · ".join(f"{k}={v}" for k, v in
                                st.session_state.dispositions.items()))

    with st.expander("🧾 Raw audit event(s) for this claim"):
        evs = events_for_claim(claim_id)
        if evs:
            st.json(evs[-1])
        else:
            st.caption("No audit event yet. Run `python src/pipeline.py "
                       "--run-all` or click 'Re-run via live agent' above.")

st.divider()
st.caption("ClaimGuard · synthetic claims and illustrative policy edits only — "
           "not for real claims adjudication. Cotiviti intern take-home · Aryan Nagwekar.")
