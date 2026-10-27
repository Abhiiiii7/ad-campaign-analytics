"""
Runs every query in sql/analysis.sql against data/ad_campaigns.db, then:

  1. Placement comparison - CPM, CTR, viewability, vCPM
  2. Budget-shift test    - what happens to viewable impressions if display
                            spend moves from the worst-vCPM publisher x placement
                            combos to the best ones (inventory-capped)
  3. Early-warning test   - backtests a daily run-rate pacing alert against
                            the old weekly pacing check: how many days earlier
                            are under-delivering line items caught?

Writes charts to output/charts, Tableau-ready CSVs to output/tableau,
and the numbers to output/findings.md.

Run:  python src/analysis.py
"""
from pathlib import Path
import re
import sqlite3
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
CH, TB = OUT / "charts", OUT / "tableau"
for p in (CH, TB):
    p.mkdir(parents=True, exist_ok=True)

con = sqlite3.connect(ROOT / "data" / "ad_campaigns.db")
sql = (ROOT / "sql" / "analysis.sql").read_text()
queries = dict(re.findall(r"-- name: (\w+)\n(.*?;)", sql, flags=re.S))
Q = {name: pd.read_sql_query(q, con) for name, q in queries.items()}

FLIGHT_DAYS = 30
UNDER = 0.90          # finished below 90% of goal = under-delivered
SHIFT = 0.50          # donors give up half their spend
CAP = 0.50            # receivers can grow at most 50% (inventory limit)

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                     "axes.spines.top": False, "axes.spines.right": False})
INK, MUTED, ACCENT, ALERT = "#1f2937", "#9ca3af", "#2563eb", "#dc2626"

# ------------------------------------------------------------ 1. placements
pk = Q["placement_kpis"]
total_impr = int(pk.impressions.sum())

fig, ax = plt.subplots(figsize=(9.5, 4))
order = pk.sort_values("vcpm")
bars = ax.barh(order.placement_name, order.vcpm,
               color=[ACCENT if f == "Display" else MUTED for f in order.format])
for b, cpm, v in zip(bars, order.cpm, order.viewability_pct):
    ax.text(b.get_width() + 0.2, b.get_y() + b.get_height() / 2,
            f"\\${b.get_width():.2f} vCPM   (CPM \\${cpm:.2f}, {v:.0f}% viewable)", va="center", fontsize=9)
ax.set_xlabel("Cost per 1,000 viewable impressions ($)")
ax.set_title("Cheap banners cost half as much per impression, but only ~12% less per viewable one",
             loc="left", color=INK, fontsize=10)
ax.set_xlim(0, order.vcpm.max() * 1.9)
fig.tight_layout()
fig.savefig(CH / "01_vcpm_by_placement.png", dpi=160)
plt.close(fig)

# --------------------------------------------------------- 2. budget shift
pp = Q["publisher_placement_kpis"]
disp = pp[pp.format == "Display"].copy().sort_values("vcpm").reset_index(drop=True)
disp["cum_share"] = disp.spend.cumsum() / disp.spend.sum()
disp["group"] = np.where(disp.cum_share <= 1 / 3, "Best third",
                         np.where(disp.cum_share > 2 / 3, "Worst third", "Middle"))
# the combo that straddles a boundary goes with the group its midpoint falls in
mid = (disp.cum_share - disp.spend / disp.spend.sum() / 2)
disp["group"] = np.where(mid <= 1 / 3, "Best third", np.where(mid > 2 / 3, "Worst third", "Middle"))

donors = disp.group == "Worst third"
receivers = disp.group == "Best third"
pool = (disp.loc[donors, "spend"] * SHIFT).sum()
room = disp.loc[receivers, "spend"] * CAP
moved = min(pool, room.sum())

disp["new_spend"] = disp.spend
disp.loc[donors, "new_spend"] = disp.loc[donors, "spend"] - disp.loc[donors, "spend"] * SHIFT * (moved / pool)
disp.loc[receivers, "new_spend"] = disp.loc[receivers, "spend"] + room * (moved / room.sum())
disp["viewable_now"] = disp.viewable_impressions
disp["viewable_after"] = disp.new_spend / disp.vcpm * 1000
disp["impr_after"] = disp.new_spend / disp.cpm * 1000

view_now, view_after = disp.viewable_now.sum(), disp.viewable_after.sum()
view_lift = view_after / view_now - 1
impr_lift = disp.impr_after.sum() / disp.impressions.sum() - 1
spend_check = disp.new_spend.sum() - disp.spend.sum()
worst_vcpm = (disp.loc[donors, "spend"].sum() * 1000 / disp.loc[donors, "viewable_impressions"].sum())
best_vcpm = (disp.loc[receivers, "spend"].sum() * 1000 / disp.loc[receivers, "viewable_impressions"].sum())

fig, ax = plt.subplots(figsize=(8, 4.5))
colors = {"Best third": ACCENT, "Middle": MUTED, "Worst third": ALERT}
for g, sub in disp.groupby("group"):
    ax.scatter(sub.cpm, sub.viewability_pct, s=sub.spend / 60, color=colors[g], alpha=0.75,
               label=f"{g} by vCPM", edgecolor="white")
ax.set_xlabel("CPM ($)")
ax.set_ylabel("Viewability (%)")
ax.set_title("Display buys by publisher x placement (bubble = spend)", loc="left", color=INK)
ax.legend(frameon=False, loc="lower right")
fig.tight_layout()
fig.savefig(CH / "02_cpm_vs_viewability.png", dpi=160)
plt.close(fig)

# --------------------------------------------------------- 3. early warning
pace = Q["line_daily_pacing"]
outc = Q["line_outcomes"].set_index("line_id")
truth = outc.under_delivered

# Old process: weekly pacing review (days 7, 14, 21, 28). Flag if pace < 0.90.
CHECKPOINTS = [7, 14, 21, 28]
weekly = pace[pace.flight_day.isin(CHECKPOINTS) & (pace.pace_index < UNDER)]
old_day = weekly.groupby("line_id").flight_day.min()

# New process: daily check from day 3. Flag when the 3-day run-rate projection
# lands below 90% of goal two days in a row.
p = pace[pace.flight_day >= 3].copy()
p["below"] = p.projected_pct_of_goal < UNDER
p["prev_below"] = p.groupby("line_id").below.shift(1, fill_value=False)
new_day = p[p.below & p.prev_below].groupby("line_id").flight_day.min()

lines = pd.DataFrame({"under_delivered": truth})
lines["old_flag_day"] = old_day
lines["new_flag_day"] = new_day
# a problem the weekly check never caught is only seen in the end-of-flight recap (day 30)
under = lines[lines.under_delivered == 1].copy()
under["old_detect"] = under.old_flag_day.fillna(FLIGHT_DAYS)
under["new_detect"] = under.new_flag_day.fillna(FLIGHT_DAYS)
under["days_earlier"] = under.old_detect - under.new_detect

n_lines, n_under = len(lines), int(truth.sum())
caught_new_before_end = int((under.new_flag_day < FLIGHT_DAYS).sum())
caught_old_before_end = int((under.old_flag_day < FLIGHT_DAYS).sum())
median_earlier = float(under.days_earlier.median())
mean_earlier = float(under.days_earlier.mean())
new_flags = lines.new_flag_day.notna()
old_flags = lines.old_flag_day.notna()
new_precision = lines.loc[new_flags, "under_delivered"].mean()
old_precision = lines.loc[old_flags, "under_delivered"].mean()
new_false = int((new_flags & (lines.under_delivered == 0)).sum())
old_false = int((old_flags & (lines.under_delivered == 0)).sum())

fig, ax = plt.subplots(figsize=(7, 3.8))
vals = under.days_earlier.astype(int)
ax.hist(vals, bins=range(vals.min(), vals.max() + 2), color=ACCENT, edgecolor="white", align="left")
ax.axvline(median_earlier, color=INK, ls="--", lw=1)
ax.text(median_earlier + 0.3, ax.get_ylim()[1] * 0.9, f"median {median_earlier:.0f} days", color=INK)
ax.set_xlabel("Days earlier the daily alert caught it vs the weekly check")
ax.set_ylabel("Under-delivering line items")
ax.set_title("Daily run-rate alert vs weekly pacing review", loc="left", color=INK)
fig.tight_layout()
fig.savefig(CH / "03_early_warning_lead_time.png", dpi=160)
plt.close(fig)

# example line: biggest lead time
ex = under.sort_values("days_earlier", ascending=False).index[0]
e = pace[pace.line_id == ex]
fig, ax = plt.subplots(figsize=(8, 4))
ax.plot(e.flight_day, e.cum_delivered, color=ACCENT, lw=2, label="Delivered (cumulative)")
ax.plot(e.flight_day, e.expected_to_date, color=MUTED, lw=1.5, ls="--", label="Plan")
ax.axvline(under.loc[ex, "new_detect"], color=ACCENT, lw=1, ls=":")
ax.text(under.loc[ex, "new_detect"] + 0.3, e.expected_to_date.max() * 0.95, "daily alert", color=ACCENT)
ax.axvline(under.loc[ex, "old_detect"], color=ALERT, lw=1, ls=":")
ax.text(under.loc[ex, "old_detect"] + 0.3, e.expected_to_date.max() * 0.85, "weekly check", color=ALERT)
ax.set_xlabel("Flight day")
ax.set_ylabel("Impressions")
ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
ax.set_title(f"Line {ex}: {outc.loc[ex, 'publisher_name']} / {outc.loc[ex, 'placement_name']} "
             f"(finished at {outc.loc[ex, 'pct_of_goal']:.0%} of goal)", loc="left", color=INK, fontsize=10)
ax.legend(frameon=False)
fig.tight_layout()
fig.savefig(CH / "04_example_line_pacing.png", dpi=160)
plt.close(fig)

# ---------------------------------------------------------- tableau exports
fact = pd.read_sql_query("""
    SELECT d.date, d.flight_day, d.line_id, l.campaign_id, c.advertiser, c.campaign_name,
           pb.publisher_name, p.placement_name, p.format,
           d.impressions, d.viewable_impressions, d.clicks, d.spend,
           l.impression_goal, l.booked_cpm
    FROM daily_delivery d
    JOIN line_items l  ON l.line_id = d.line_id
    JOIN campaigns c   ON c.campaign_id = l.campaign_id
    JOIN publishers pb ON pb.publisher_id = l.publisher_id
    JOIN placements p  ON p.placement_id = l.placement_id
""", con)
fact.to_csv(TB / "delivery_fact.csv", index=False)
pace.merge(outc[["publisher_name", "placement_name", "under_delivered"]], left_on="line_id",
           right_index=True).to_csv(TB / "line_daily_pacing.csv", index=False)
lines.reset_index().rename(columns={"index": "line_id"}).to_csv(TB / "alert_backtest.csv", index=False)
disp.to_csv(TB / "budget_shift.csv", index=False)
for name in ("placement_kpis", "publisher_delivery"):
    Q[name].to_csv(TB / f"{name}.csv", index=False)

# --------------------------------------------------------------- findings
pdv = Q["publisher_delivery"]
md = f"""# Findings

*Simulated data: 12 campaigns, 128 line items, 5 publishers, 6 placements, 30-day flights,
{total_impr:,} impressions. Generated by `src/generate_data.py` (seed 7).*

## 1. Placement comparison

{pk[['placement_name','impressions','cpm','ctr_pct','viewability_pct','vcpm']].to_markdown(index=False)}

Below-the-fold and sidebar banners cost about half as much per impression as above-the-fold
(${pk.set_index('placement_name').loc['Below-the-fold 300x250','cpm']:.2f} vs ${pk.set_index('placement_name').loc['Above-the-fold 300x250','cpm']:.2f}),
but only about 40% of their impressions are seen. Per *viewable* impression the gap shrinks to roughly 12%.
CPM alone overstates how much cheaper they are.

## 2. Shifting display budget toward better-value inventory

Display buys were split into thirds by vCPM (spend-weighted). Half of the spend in the worst third
(avg vCPM ${worst_vcpm:.2f}) was moved to the best third (avg vCPM ${best_vcpm:.2f}), and each receiving buy
could grow by at most 50% to reflect real inventory limits.

| | Now | After shift | Change |
|---|---|---|---|
| Display spend | ${disp.spend.sum():,.0f} | ${disp.new_spend.sum():,.0f} | {spend_check:+.0f} |
| Viewable impressions | {view_now:,.0f} | {view_after:,.0f} | **{view_lift:+.1%}** |
| Total impressions | {disp.impressions.sum():,.0f} | {disp.impr_after.sum():,.0f} | {impr_lift:+.1%} |

**Same budget, {view_lift:.1%} more viewable impressions.** Moved: ${moved:,.0f}.
Raw impressions jump {impr_lift:.1%}, but most of that is cheap inventory people don't see.
Judged on CPM alone, this shift looks four times better than it really is.
This is a what-if on historical rates, not a tested result. It assumes rates hold at higher spend.

## 3. Catching under-delivery earlier

{n_under} of {n_lines} line items finished below 90% of their impression goal.

| | Weekly pacing review (days 7/14/21/28, pace < 0.90) | Daily run-rate alert (3-day projection < 90% of goal, 2 days running) |
|---|---|---|
| Under-deliverers caught before flight end | {caught_old_before_end} of {n_under} | {caught_new_before_end} of {n_under} |
| Median detection day | {under.old_detect.median():.0f} | {under.new_detect.median():.0f} |
| False alarms (flagged but finished fine) | {old_false} | {new_false} |
| Share of flags that were real problems | {old_precision:.0%} | {new_precision:.0%} |

**The daily alert caught under-delivering line items a median of {median_earlier:.0f} days earlier
(mean {mean_earlier:.1f}).** That's time to ask a publisher for make-goods or move budget while the
flight is still running.

## Publisher delivery

{pdv.to_markdown(index=False)}
"""
(OUT / "findings.md").write_text(md)

print(f"impressions={total_impr:,}")
print(pk[["placement_name", "cpm", "ctr_pct", "viewability_pct", "vcpm"]].to_string(index=False))
print(f"shift: moved=${moved:,.0f} view_lift={view_lift:.1%} impr_lift={impr_lift:.1%} spend_check={spend_check:.2f}")
print(f"under={n_under}/{n_lines} median_earlier={median_earlier} mean={mean_earlier:.1f} "
      f"caught old={caught_old_before_end} new={caught_new_before_end} "
      f"false old={old_false} new={new_false} precision old={old_precision:.2f} new={new_precision:.2f}")
print(pdv.to_string(index=False))
