"""
ACE Impact Engine
Computes statistically-grounded before/after impact for a single ACE route:
  - average bus speed before vs after activation (the outcome MTA itself reports)
  - a t-test + effect size on the available before/after monthly speed samples
  - violation trend (recent vs early period) as a secondary recidivism signal
  - a verdict label, mirroring the Test & Learn Autopilot module's approach

This is intentionally built on the same statistical pattern already used in
module3_test_and_learn/app.py (cohens_d + Welch's t-test), just pointed at
real route-level outcome data instead of uploaded CSVs.
"""

import numpy as np
import pandas as pd
from scipy import stats


def cohens_d(a, b):
    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2:
        return 0.0
    pooled = np.sqrt(((n1 - 1) * np.var(a, ddof=1) + (n2 - 1) * np.var(b, ddof=1)) / (n1 + n2 - 2))
    return (np.mean(a) - np.mean(b)) / pooled if pooled else 0.0


def load_data(routes_csv, violations_csv, speeds_csv, route_col, route_date_col,
              viol_route_col, viol_date_col, viol_status_col,
              speed_route_col, speed_period_col, speed_col):
    """Load and lightly normalize the three CSVs. Returns (routes_df, viol_df, speed_df)."""
    import os

    routes_df = pd.DataFrame()
    viol_df   = pd.DataFrame()
    speed_df  = pd.DataFrame()

    if os.path.exists(routes_csv):
        routes_df = pd.read_csv(routes_csv)
        if route_date_col and route_date_col in routes_df.columns:
            routes_df[route_date_col] = pd.to_datetime(routes_df[route_date_col], errors="coerce")

    if os.path.exists(violations_csv):
        viol_df = pd.read_csv(violations_csv)
        if viol_date_col and viol_date_col in viol_df.columns:
            viol_df[viol_date_col] = pd.to_datetime(viol_df[viol_date_col], errors="coerce")

    if os.path.exists(speeds_csv):
        speed_df = pd.read_csv(speeds_csv)
        if speed_period_col and speed_period_col in speed_df.columns:
            speed_df[speed_period_col] = pd.to_datetime(speed_df[speed_period_col], errors="coerce")
        if speed_col and speed_col in speed_df.columns:
            speed_df[speed_col] = pd.to_numeric(speed_df[speed_col], errors="coerce")

    return routes_df, viol_df, speed_df


def get_eligible_routes(routes_df, speed_df, route_col, route_date_col, speed_route_col, speed_period_col):
    """
    Routes that have a known activation date AND at least one speed sample
    both before and after that date - i.e. routes we can actually certify.
    """
    if routes_df.empty or speed_df.empty or not all([route_col, route_date_col, speed_route_col, speed_period_col]):
        return []

    eligible = []
    for _, row in routes_df.dropna(subset=[route_date_col]).iterrows():
        route = row[route_col]
        act_date = row[route_date_col]
        sub = speed_df[speed_df[speed_route_col] == route]
        if sub.empty:
            continue
        before = sub[sub[speed_period_col] < act_date]
        after  = sub[sub[speed_period_col] >= act_date]
        if len(before) >= 1 and len(after) >= 1:
            eligible.append(route)

    return sorted(set(eligible))


def compute_route_impact(route, routes_df, viol_df, speed_df,
                          route_col, route_date_col,
                          viol_route_col, viol_date_col,
                          speed_route_col, speed_period_col, speed_col,
                          window_days=90):
    """
    Returns a dict describing the before/after impact for one route.
    """
    result = {"route": route, "verdict": "INSUFFICIENT DATA", "color": "#5F5E5A"}

    route_row = routes_df[routes_df[route_col] == route]
    if route_row.empty:
        result["detail"] = "No activation date on record for this route."
        return result

    act_date = route_row.iloc[0][route_date_col]
    result["activation_date"] = act_date

    # ── Speed before/after ──────────────────────────────────────────────────
    sub = speed_df[speed_df[speed_route_col] == route].dropna(subset=[speed_col])
    before = sub[sub[speed_period_col] < act_date][speed_col].values
    after  = sub[sub[speed_period_col] >= act_date][speed_col].values

    result["n_before"] = len(before)
    result["n_after"]  = len(after)

    if len(before) == 0 or len(after) == 0:
        result["detail"] = "No speed data on one side of the activation date."
        return result

    speed_before = float(np.mean(before))
    speed_after  = float(np.mean(after))
    pct_change   = (speed_after - speed_before) / speed_before * 100 if speed_before else 0

    result["speed_before"] = round(speed_before, 2)
    result["speed_after"]  = round(speed_after, 2)
    result["pct_change"]   = round(pct_change, 1)

    if len(before) >= 2 and len(after) >= 2:
        _, p = stats.ttest_ind(after, before, equal_var=False)
        d = cohens_d(after, before)
        result["p_value"]    = round(float(p), 4)
        result["effect_size"] = round(float(d), 2)
    else:
        result["p_value"] = None
        result["effect_size"] = None
        result["note_small_sample"] = (
            f"Only {len(before)} sample(s) before and {len(after)} after - "
            "too few for a formal significance test. Treat the % change as directional, not certified."
        )

    # ── Violation trend (secondary signal) ──────────────────────────────────
    if not viol_df.empty and viol_route_col in viol_df.columns and viol_date_col in viol_df.columns:
        vsub = viol_df[viol_df[viol_route_col] == route].dropna(subset=[viol_date_col])
        if not vsub.empty:
            latest = vsub[viol_date_col].max()
            early_cut = act_date + pd.Timedelta(days=window_days)
            recent_cut = latest - pd.Timedelta(days=window_days)
            early_count  = vsub[(vsub[viol_date_col] >= act_date) & (vsub[viol_date_col] < early_cut)].shape[0]
            recent_count = vsub[vsub[viol_date_col] >= recent_cut].shape[0]
            result["violations_first_window"]  = early_count
            result["violations_recent_window"] = recent_count
            if early_count > 0:
                result["violation_trend_pct"] = round((recent_count - early_count) / early_count * 100, 1)

    # ── Verdict ──────────────────────────────────────────────────────────────
    p = result.get("p_value")
    d = result.get("effect_size")
    if p is not None and d is not None:
        sig = p < 0.05
        meaningful = abs(d) >= 0.2
        improved = pct_change > 0
        if sig and meaningful and improved:
            result["verdict"] = "CONFIRMED IMPROVEMENT"
            result["color"] = "#1D9E75"
            result["detail"] = (
                f"Statistically significant speed increase of {pct_change:+.1f}% "
                f"(p={p:.3f}, effect size={d:.2f}). This route's ACE impact can be reported with confidence."
            )
        elif sig and meaningful and not improved:
            result["verdict"] = "CONFIRMED DECLINE"
            result["color"] = "#E24B4A"
            result["detail"] = (
                f"Statistically significant speed decrease of {pct_change:+.1f}% "
                f"(p={p:.3f}, effect size={d:.2f}). Worth investigating before publicizing this route."
            )
        else:
            result["verdict"] = "NO SIGNIFICANT CHANGE"
            result["color"] = "#BA7517"
            result["detail"] = (
                f"Speed changed {pct_change:+.1f}% but isn't statistically distinguishable from noise "
                f"(p={p:.3f}). Needs more data before certifying an impact claim."
            )
    else:
        result["verdict"] = "DIRECTIONAL ONLY"
        result["color"] = "#5F5E5A"
        result["detail"] = result.get("note_small_sample", "Not enough data to test significance.")

    return result


# ══════════════════════════════════════════════════════════════════════════════
# Emissions estimate - REAL, SOURCED, LABELED AS AN ESTIMATE
#
# This is NOT a full vehicle emissions model (that would require EPA's MOVES
# tool with speed-specific emission rate curves for transit buses - out of
# scope here). It's a transparent, order-of-magnitude proxy: the time
# difference per mile between before/after average speed stands in for
# reduced idling/low-speed-creeping time, then two real cited figures are
# applied. Every number below traces to a real source - nothing is invented.
#
# SOURCES:
#   - Transit bus idling fuel consumption ≈ 1.0 gal/hr
#     U.S. Dept. of Energy, "Fact #861: Idle Fuel Consumption for Selected
#     Gasoline and Diesel Vehicles" (Feb 23, 2015), based on Argonne National
#     Laboratory data.
#     https://www.energy.gov/cmei/vehicles/fact-861-february-23-2015-idle-fuel-consumption-selected-gasoline-and-diesel-vehicles
#   - Diesel CO2 emission factor = 10.18 kg CO2/gallon (10,180 g/gal)
#     EPA Greenhouse Gas Equivalencies Calculator, citing the joint EPA/DOT
#     Federal Register rulemaking (May 7, 2010) on fuel economy standards.
#     https://www.epa.gov/energy/greenhouse-gas-equivalencies-calculator-calculations-and-references
# ══════════════════════════════════════════════════════════════════════════════

TRANSIT_BUS_IDLE_GAL_PER_HR = 1.0    # DOE Fact #861 / Argonne National Laboratory
DIESEL_CO2_KG_PER_GALLON    = 10.18  # EPA GHG Equivalencies Calculator (Federal Register 2010)

EMISSIONS_METHODOLOGY_NOTE = (
    "Estimate only, not a precision vehicle emissions model. Treats the time "
    "difference per mile between before/after average speed as a proxy for "
    "reduced idling/low-speed time, then applies DOE's transit bus idling fuel "
    "rate (~1.0 gal/hr, Fact #861, Argonne National Laboratory) and EPA's "
    "diesel CO2 factor (10.18 kg/gal, Federal Register 2010). Treat as "
    "directional, order-of-magnitude - not an exact figure."
)


def estimate_emissions_impact(result, daily_bus_trips=None, route_miles=None):
    """
    Estimate CO2 impact from a route's before/after speed change.
    Returns None if the result has no speed data to work with.

    daily_bus_trips & route_miles are OPTIONAL, user-supplied numbers for
    scaling the per-mile rate up to a daily/annual total. If either is left
    out, only the per-mile rate is returned - no trip volume is assumed or
    invented.
    """
    speed_before = result.get("speed_before")
    speed_after = result.get("speed_after")
    if not speed_before or not speed_after:
        return None

    min_per_mile_before = 60.0 / speed_before
    min_per_mile_after  = 60.0 / speed_after
    time_saved_min_per_mile = min_per_mile_before - min_per_mile_after
    time_saved_hr_per_mile  = time_saved_min_per_mile / 60.0

    fuel_saved_gal_per_mile = time_saved_hr_per_mile * TRANSIT_BUS_IDLE_GAL_PER_HR
    co2_avoided_kg_per_mile = fuel_saved_gal_per_mile * DIESEL_CO2_KG_PER_GALLON

    out = {
        "time_saved_min_per_mile": round(time_saved_min_per_mile, 2),
        "fuel_saved_gal_per_mile": round(fuel_saved_gal_per_mile, 4),
        "co2_avoided_kg_per_mile": round(co2_avoided_kg_per_mile, 3),
        "methodology": EMISSIONS_METHODOLOGY_NOTE,
    }

    if daily_bus_trips and route_miles:
        daily_miles = daily_bus_trips * route_miles
        out["co2_avoided_kg_per_day"]  = round(co2_avoided_kg_per_mile * daily_miles, 1)
        out["co2_avoided_kg_per_year"] = round(out["co2_avoided_kg_per_day"] * 365, 0)
        out["scale_assumption"] = f"{daily_bus_trips} daily trips x {route_miles} route miles (user-supplied, not pulled from data)"

    return out


def write_impact_summary(result, client, brand_name="MTA", emissions=None):
    """LLM-written before/after impact statement in the style of an MTA press release.
    emissions: optional dict from estimate_emissions_impact() - if provided, the
    summary may reference it, but is instructed to label it as an estimate."""
    emissions_block = ""
    if emissions:
        emissions_block = f"""
- Estimated CO2 avoided: {emissions['co2_avoided_kg_per_mile']} kg per bus-mile
  (THIS IS AN ESTIMATE based on EPA/DOE published rates, not a precise measurement -
  if you mention it, explicitly call it an estimate, never a precise/certified figure)
"""

    prompt = f"""Write a short before/after impact statement for {brand_name}'s Automated Camera
Enforcement (ACE) program on route {result['route']}, suitable for inclusion in a press release
or board report. Use ONLY the data below - do not invent numbers.

DATA:
- ACE activation date: {result.get('activation_date')}
- Average bus speed before: {result.get('speed_before')} mph
- Average bus speed after: {result.get('speed_after')} mph
- Change: {result.get('pct_change')}%
- Statistical verdict: {result['verdict']}
- p-value: {result.get('p_value')}
- Violations in first {90} days after activation: {result.get('violations_first_window')}
- Violations in most recent {90}-day window: {result.get('violations_recent_window')}
{emissions_block}
Write 2-3 short sentences, plain English, matching the tone of an MTA press release
(e.g. "Bus routes equipped with automated enforcement on average have increased speeds by 5%").
If the verdict is NO SIGNIFICANT CHANGE, DIRECTIONAL ONLY, or CONFIRMED DECLINE, do not overstate
the result - be honest that the data doesn't support a strong improvement claim yet.
"""
    r = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3, max_tokens=220,
    )
    return r.choices[0].message.content.strip()
