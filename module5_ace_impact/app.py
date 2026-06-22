"""Module 5 - ACE Impact Certification

Automates the before/after impact analysis MTA currently appears to produce
by hand for each ACE route rollout (the "+5% speed, -20% collisions" style
stats seen across individual press releases). Pulls real public data via
01_extract_ace_data.py, certifies the statistical significance of the
speed change per route, and can draft a press-release-style summary.
"""

import os, sys
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv
load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from config import (
    ACE_ROUTES_CSV, ACE_VIOLATIONS_CSV, BUS_SPEEDS_CSV,
    BRAND_NAME as APP_NAME, IMPACT_WINDOW_DAYS,
)
from module1_voice_of_customer.voc_analyzer import get_groq_client
from module5_ace_impact.impact_engine import (
    load_data, get_eligible_routes, compute_route_impact,
    write_impact_summary, estimate_emissions_impact,
)

# These must match whatever 01_extract_ace_data.py actually detected at
# extraction time. If you changed COLUMN_OVERRIDES there, mirror it here too.
# Left as None = best-effort guess at load time from the saved CSV headers.
GUESS_KEYWORDS = {
    "route_col":        ["route_id", "bus_route", "route"],
    "route_date_col":   ["activation", "implementation", "effective_date", "start_date", "ace_date", "date"],
    "viol_route_col":   ["bus_route_id", "route_id", "route"],
    "viol_date_col":    ["first_occurrence", "violation_date", "issue_date", "date"],
    "speed_route_col":  ["route_id", "bus_route", "route"],
    "speed_period_col": ["month", "period", "date"],
    "speed_col":        ["average_speed", "speed_mph", "speed"],
}


def guess_column(df, keywords):
    if df is None or df.empty:
        return None
    lower_to_real = {c.lower(): c for c in df.columns}
    for kw in keywords:
        for col_lower, col_real in lower_to_real.items():
            if kw in col_lower:
                return col_real
    return None


@st.cache_data(show_spinner=False)
def load_all():
    # Peek at headers first so guess_column has something to work with even
    # before full load_data() parsing.
    routes_df  = pd.read_csv(ACE_ROUTES_CSV) if os.path.exists(ACE_ROUTES_CSV) else pd.DataFrame()
    viol_df    = pd.read_csv(ACE_VIOLATIONS_CSV) if os.path.exists(ACE_VIOLATIONS_CSV) else pd.DataFrame()
    speed_df   = pd.read_csv(BUS_SPEEDS_CSV) if os.path.exists(BUS_SPEEDS_CSV) else pd.DataFrame()

    cols = {
        "route_col":        guess_column(routes_df, GUESS_KEYWORDS["route_col"]),
        "route_date_col":   guess_column(routes_df, GUESS_KEYWORDS["route_date_col"]),
        "viol_route_col":   guess_column(viol_df, GUESS_KEYWORDS["viol_route_col"]),
        "viol_date_col":    guess_column(viol_df, GUESS_KEYWORDS["viol_date_col"]),
        "viol_status_col":  None,
        "speed_route_col":  guess_column(speed_df, GUESS_KEYWORDS["speed_route_col"]),
        "speed_period_col": guess_column(speed_df, GUESS_KEYWORDS["speed_period_col"]),
        "speed_col":        guess_column(speed_df, GUESS_KEYWORDS["speed_col"]),
    }

    routes_df, viol_df, speed_df = load_data(
        ACE_ROUTES_CSV, ACE_VIOLATIONS_CSV, BUS_SPEEDS_CSV,
        cols["route_col"], cols["route_date_col"],
        cols["viol_route_col"], cols["viol_date_col"], cols["viol_status_col"],
        cols["speed_route_col"], cols["speed_period_col"], cols["speed_col"],
    )
    return routes_df, viol_df, speed_df, cols


def show():
    st.markdown("## 📋 ACE Impact Certification")
    st.markdown(
        f"Automated before/after impact analysis for **{APP_NAME}**'s Automated Camera Enforcement (ACE) "
        "program - the speed/violation stats MTA currently appears to compute by hand per route, "
        "certified statistically and ready in seconds instead of a manual analyst pull."
    )

    if not (os.path.exists(ACE_ROUTES_CSV) and os.path.exists(BUS_SPEEDS_CSV)):
        st.error(
            "No ACE data yet. Run:\n\n"
            "```\npython module5_ace_impact/01_extract_ace_data.py\n```\n\n"
            "This pulls live data from data.ny.gov (MTA Bus Automated Camera Enforced Routes, "
            "ACE Violations, and MTA Bus Speeds datasets)."
        )
        return

    routes_df, viol_df, speed_df, cols = load_all()

    missing = [k for k, v in cols.items() if v is None and k != "viol_status_col"]
    if missing:
        st.warning(
            f"Couldn't confidently detect these columns from the saved CSVs: {missing}. "
            "Check the printed column list from 01_extract_ace_data.py and hardcode the "
            "real names in module5_ace_impact/app.py's GUESS_KEYWORDS or the extractor's "
            "COLUMN_OVERRIDES."
        )
        return

    eligible = get_eligible_routes(
        routes_df, speed_df,
        cols["route_col"], cols["route_date_col"],
        cols["speed_route_col"], cols["speed_period_col"],
    )

    if not eligible:
        st.warning(
            "No routes currently have both an activation date and speed data on both sides of it. "
            "This can happen if ACE was activated very recently for every route in the dataset, "
            "or if column detection picked the wrong fields - check the values above."
        )
        return

    st.markdown("---")
    st.sidebar.markdown("### 📋 ACE Impact Filters")
    selected_route = st.sidebar.selectbox("Route", eligible)

    result = compute_route_impact(
        selected_route, routes_df, viol_df, speed_df,
        cols["route_col"], cols["route_date_col"],
        cols["viol_route_col"], cols["viol_date_col"],
        cols["speed_route_col"], cols["speed_period_col"], cols["speed_col"],
        window_days=IMPACT_WINDOW_DAYS,
    )

    color = result["color"]
    st.markdown(
        f"""<div style="background:{color}15;border:2px solid {color};border-radius:12px;padding:20px 24px;margin-bottom:20px;">
            <div style="font-size:24px;font-weight:700;color:{color};margin-bottom:8px;">{result['verdict']}</div>
            <div style="font-size:14px;color:#444;line-height:1.6;">{result.get('detail','')}</div>
        </div>""",
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Speed Before", f"{result.get('speed_before','-')} mph")
    c2.metric("Speed After", f"{result.get('speed_after','-')} mph",
              f"{result.get('pct_change','-')}%" if result.get('pct_change') is not None else None)
    c3.metric("p-value", result.get("p_value", "-"))
    c4.metric("Effect Size", result.get("effect_size", "-"))

    if "speed_before" in result and "speed_after" in result:
        st.markdown("---")
        st.markdown("### 📈 Speed: Before vs After Activation")
        fig = go.Figure(go.Bar(
            x=["Before ACE", "After ACE"],
            y=[result["speed_before"], result["speed_after"]],
            marker_color=["#94a3b8", color],
            text=[f"{result['speed_before']} mph", f"{result['speed_after']} mph"],
            textposition="outside",
        ))
        fig.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0),
                          plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                          yaxis_title="Avg Speed (mph)")
        st.plotly_chart(fig, use_container_width=True)

    if result.get("violations_first_window") is not None:
        st.markdown("---")
        st.markdown("### 🚨 Violation Trend (recidivism signal)")
        vc1, vc2, vc3 = st.columns(3)
        vc1.metric(f"Violations, first {IMPACT_WINDOW_DAYS}d", result["violations_first_window"])
        vc2.metric(f"Violations, most recent {IMPACT_WINDOW_DAYS}d", result["violations_recent_window"])
        trend = result.get("violation_trend_pct")
        if trend is not None:
            vc3.metric("Change", f"{trend:+.1f}%", delta=f"{trend:+.1f}%", delta_color="inverse")

    # ── Emissions estimate ──────────────────────────────────────────────────
    emissions = estimate_emissions_impact(result)
    if emissions:
        st.markdown("---")
        st.markdown("### 🌎 Estimated Emissions Impact")
        st.caption(
            "⚠️ Order-of-magnitude **estimate**, not a precision vehicle emissions model. "
            "See methodology below."
        )
        ec1, ec2, ec3 = st.columns(3)
        ec1.metric("Time saved", f"{emissions['time_saved_min_per_mile']} min/mile")
        ec2.metric("Fuel saved (est.)", f"{emissions['fuel_saved_gal_per_mile']} gal/mile")
        ec3.metric("CO2 avoided (est.)", f"{emissions['co2_avoided_kg_per_mile']} kg/mile")

        with st.expander("Optional: scale to a daily/annual estimate"):
            st.caption(
                "These two numbers are NOT pulled from any dataset - enter real figures "
                "for this route if you have them (e.g. from the route's published schedule) "
                "to scale the per-mile rate up. Leave blank to skip scaling."
            )
            sc1, sc2 = st.columns(2)
            daily_trips = sc1.number_input("Daily bus trips on this route", min_value=0, value=0, step=1)
            route_miles_input = sc2.number_input("Route length (miles, one-way)", min_value=0.0, value=0.0, step=0.1)
            if daily_trips and route_miles_input:
                scaled = estimate_emissions_impact(result, daily_bus_trips=daily_trips, route_miles=route_miles_input)
                st.metric("Estimated CO2 avoided / day", f"{scaled['co2_avoided_kg_per_day']:,} kg")
                st.metric("Estimated CO2 avoided / year", f"{scaled['co2_avoided_kg_per_year']:,.0f} kg")
                st.caption(f"Assumption used: {scaled['scale_assumption']}")

        with st.expander("Methodology & sources"):
            st.markdown(f"""
{emissions['methodology']}

**Sources:**
- Transit bus idling fuel rate (~1.0 gal/hr): U.S. Dept. of Energy, *Fact #861: Idle Fuel
  Consumption for Selected Gasoline and Diesel Vehicles* (Feb 2015), based on Argonne National
  Laboratory data. [energy.gov/cmei/vehicles/fact-861](https://www.energy.gov/cmei/vehicles/fact-861-february-23-2015-idle-fuel-consumption-selected-gasoline-and-diesel-vehicles)
- Diesel CO2 factor (10.18 kg/gal): EPA Greenhouse Gas Equivalencies Calculator, citing the
  joint EPA/DOT Federal Register rulemaking (May 2010).
  [epa.gov/energy/greenhouse-gas-equivalencies-calculator](https://www.epa.gov/energy/greenhouse-gas-equivalencies-calculator-calculations-and-references)
""")

    st.markdown("---")
    st.markdown("### 📄 Draft Impact Statement")
    if st.button("Generate Press-Release-Style Summary", type="primary"):
        try:
            client = get_groq_client()
        except ValueError as e:
            st.error(str(e))
        else:
            with st.spinner("Writing summary..."):
                summary = write_impact_summary(result, client, brand_name=APP_NAME, emissions=emissions)
            st.markdown(
                f"""<div style="background:#F1EFE8;border-radius:12px;padding:20px 24px;border:1px solid #D3D1C7;">
                    <div style="font-size:11px;font-weight:600;letter-spacing:0.08em;color:#888;text-transform:uppercase;margin-bottom:12px;">
                        Impact Statement · AI Generated · Speeds and counts are real data; any emissions figure is a labeled estimate
                    </div>
                    <div style="font-size:15px;line-height:1.8;color:#2C2C2A;">{summary}</div>
                </div>""",
                unsafe_allow_html=True,
            )
            st.code(summary, language=None)

    st.markdown("---")
    st.markdown("## 🏆 Systemwide Ranking — All ACE Routes")
    st.markdown(
        "Computed for every route in the ACE Enforced Routes dataset that has speed data "
        "on both sides of its activation date — not just the one selected above."
    )

    # ── Coverage accounting: which routes have ACE but couldn't be analyzed ──
    all_ace_routes = sorted(routes_df.dropna(subset=[cols["route_date_col"]])[cols["route_col"]].unique().tolist())
    excluded = [r for r in all_ace_routes if r not in eligible]

    cov1, cov2, cov3 = st.columns(3)
    cov1.metric("Total ACE routes", len(all_ace_routes))
    cov2.metric("Analyzable (have before+after speed data)", len(eligible))
    cov3.metric("Excluded (missing speed data)", len(excluded))

    if excluded:
        with st.expander(f"View {len(excluded)} routes excluded from ranking"):
            st.caption(
                "These routes have ACE cameras but don't yet have speed data on both sides "
                "of their activation date in the Bus Speeds dataset(s) - usually because "
                "activation was too recent, or the route isn't covered by the speed dataset."
            )
            st.write(", ".join(str(r) for r in excluded))

    # ── Compute speed + emissions impact for every analyzable route ─────────
    all_results = []
    for r in eligible:
        res = compute_route_impact(
            r, routes_df, viol_df, speed_df,
            cols["route_col"], cols["route_date_col"],
            cols["viol_route_col"], cols["viol_date_col"],
            cols["speed_route_col"], cols["speed_period_col"], cols["speed_col"],
            window_days=IMPACT_WINDOW_DAYS,
        )
        if "pct_change" not in res:
            continue
        em = estimate_emissions_impact(res)
        all_results.append({
            "Route": r,
            "Verdict": res["verdict"],
            "Speed Before": res["speed_before"],
            "Speed After": res["speed_after"],
            "% Speed Change": res["pct_change"],
            "p-value": res.get("p_value"),
            "CO2 Avoided (kg/mile, est.)": em["co2_avoided_kg_per_mile"] if em else None,
            "Time Saved (min/mile)": em["time_saved_min_per_mile"] if em else None,
        })

    if not all_results:
        st.info("No routes with enough data to rank yet.")
    else:
        full_table = pd.DataFrame(all_results)

        by_speed = full_table.sort_values("% Speed Change", ascending=False)
        by_emissions = full_table.sort_values("CO2 Avoided (kg/mile, est.)", ascending=False)

        top5_speed_routes = set(by_speed.head(5)["Route"])
        top5_emissions_routes = set(by_emissions.head(5)["Route"])
        overlap = top5_speed_routes & top5_emissions_routes

        st.markdown("---")
        st.markdown(
            f"**Top 5 by speed and top 5 by emissions overlap on {len(overlap)}/5 routes.** "
            + (
                "Same routes lead on both metrics - speed gains and emissions gains are tracking together here."
                if len(overlap) >= 4 else
                "The rankings diverge more than you might expect: emissions impact depends on the absolute "
                "minutes saved per mile, not the percentage - so a slower, more congested route can rank higher "
                "on emissions even with a smaller percentage speed gain, because the same % improvement recovers "
                "more real idling time at low speeds than at high speeds."
            )
        )

        rc1, rc2 = st.columns(2)
        with rc1:
            st.markdown("#### 🚀 Top 5 — Speed Improvement")
            st.dataframe(
                by_speed.head(5)[["Route", "% Speed Change", "Speed Before", "Speed After", "Verdict"]],
                use_container_width=True, hide_index=True,
            )
            st.markdown("#### 🐌 Bottom 5 — Speed Improvement")
            st.dataframe(
                by_speed.tail(5)[["Route", "% Speed Change", "Speed Before", "Speed After", "Verdict"]].iloc[::-1],
                use_container_width=True, hide_index=True,
            )
        with rc2:
            st.markdown("#### 🌎 Top 5 — Emissions Reduction (est.)")
            st.dataframe(
                by_emissions.head(5)[["Route", "CO2 Avoided (kg/mile, est.)", "Time Saved (min/mile)", "% Speed Change"]],
                use_container_width=True, hide_index=True,
            )
            st.markdown("#### 🏭 Bottom 5 — Emissions Reduction (est.)")
            st.dataframe(
                by_emissions.tail(5)[["Route", "CO2 Avoided (kg/mile, est.)", "Time Saved (min/mile)", "% Speed Change"]].iloc[::-1],
                use_container_width=True, hide_index=True,
            )

        st.markdown("---")
        st.markdown("#### Full ranking — all analyzable routes")
        sort_choice = st.radio("Sort by", ["% Speed Change", "CO2 Avoided (kg/mile, est.)"], horizontal=True)
        st.dataframe(
            full_table.sort_values(sort_choice, ascending=False),
            use_container_width=True, hide_index=True,
        )
        st.caption(
            "CO2 figures are order-of-magnitude estimates (see Methodology & sources above), "
            "not certified measurements."
        )
