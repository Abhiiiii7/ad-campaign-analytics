"""
Builds dashboard/index.html - an interactive version of the analysis,
with the results embedded. Run after analysis.py:

    python src/build_dashboard.py
"""
from pathlib import Path
import json
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
T = ROOT / "output" / "tableau"
pk = pd.read_csv(T / "placement_kpis.csv")
shift = pd.read_csv(T / "budget_shift.csv")
pace = pd.read_csv(T / "line_daily_pacing.csv")
alerts = pd.read_csv(T / "alert_backtest.csv")

under = alerts[alerts.under_delivered == 1].copy()
under["days_earlier"] = under.old_flag_day.fillna(30) - under.new_flag_day.fillna(30)

lines = {}
for lid, g in pace.groupby("line_id"):
    g = g.sort_values("flight_day")
    a = alerts.set_index("line_id").loc[lid]
    lines[lid] = {
        "pub": g.publisher_name.iloc[0], "plc": g.placement_name.iloc[0],
        "goal": int(g.impression_goal.iloc[0]), "under": int(g.under_delivered.iloc[0]),
        "cum": g.cum_delivered.astype(int).tolist(),
        "proj": g.projected_pct_of_goal.round(3).fillna(0).tolist(),
        "pace": g.pace_index.round(3).tolist(),
        "newFlag": None if pd.isna(a.new_flag_day) else int(a.new_flag_day),
        "oldFlag": None if pd.isna(a.old_flag_day) else int(a.old_flag_day),
    }

view_now, view_after = shift.viewable_now.sum(), shift.viewable_after.sum()
data = {
    "placements": pk[["placement_name", "format", "impressions", "cpm", "ctr_pct",
                      "viewability_pct", "vcpm"]].values.tolist(),
    "scatter": shift[["publisher_name", "placement_name", "cpm", "viewability_pct", "vcpm",
                      "spend", "group"]].round(2).values.tolist(),
    "lead": under.days_earlier.astype(int).tolist(),
    "lines": lines,
    "kpi": {
        "impressions": int(pk.impressions.sum()),
        "spend": float(pk.spend.sum()),
        "under": int(alerts.under_delivered.sum()),
        "nLines": int(len(alerts)),
        "medianEarlier": float(under.days_earlier.median()),
        "viewLift": float(view_after / view_now - 1),
        "imprLift": float(shift.impr_after.sum() / shift.impressions.sum() - 1),
        "moved": float((shift.spend - shift.new_spend).clip(lower=0).sum()),
    },
}
html = (ROOT / "src" / "dashboard_template.html").read_text().replace(
    "__DATA__", json.dumps(data, separators=(",", ":")))
out = ROOT / "dashboard"
out.mkdir(exist_ok=True)
(out / "index.html").write_text(html)
print(f"wrote {out / 'index.html'} ({len(html)/1024:.0f} KB)")
