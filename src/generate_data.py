"""
Simulates programmatic display + video delivery for 12 campaigns across
5 fictional publishers and 6 placements, March 2026 (30-day flights).

Writes data/raw/*.csv and builds data/ad_campaigns.db (SQLite).
All names and numbers are simulated for practice.

Run:  python src/generate_data.py
"""
from pathlib import Path
import sqlite3
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)
rng = np.random.default_rng(7)

FLIGHT_DAYS = 30
START = pd.Timestamp("2026-03-01")

placements = pd.DataFrame([
    # id, name, format, base CPM, base CTR, base viewability
    ("P1", "Above-the-fold 300x250", "Display", 6.50, 0.0012, 0.68),
    ("P2", "Below-the-fold 300x250", "Display", 3.20, 0.0006, 0.38),
    ("P3", "In-article native",      "Display", 7.50, 0.0020, 0.74),
    ("P4", "Sidebar 160x600",        "Display", 3.80, 0.0005, 0.45),
    ("P5", "Interstitial",           "Display", 9.00, 0.0045, 0.85),
    ("P6", "Pre-roll video :15",     "Video",  14.00, 0.0030, 0.80),
], columns=["placement_id", "placement_name", "format", "base_cpm", "base_ctr", "base_viewability"])

publishers = pd.DataFrame([
    # id, name, category, CPM factor, viewability factor
    ("PB1", "Northline News",     "News",      1.10, 1.08),
    ("PB2", "Kitchen & Co",       "Lifestyle", 0.95, 1.02),
    ("PB3", "StreamHub",          "Video/Ent", 1.05, 1.00),
    ("PB4", "DealFinder Network", "Shopping",  0.80, 0.82),
    ("PB5", "Weekend Wire",       "Sports",    1.00, 0.95),
], columns=["publisher_id", "publisher_name", "category", "cpm_factor", "view_factor"])

advertisers = ["Brightside Grocers", "Peakline Outdoor", "Lumen Skincare", "Harbor Bank",
               "Volt Mobility", "Tidewater Travel"]
campaigns = []
for i in range(12):
    campaigns.append({
        "campaign_id": f"C{i+1:02d}",
        "advertiser": advertisers[i % len(advertisers)],
        "campaign_name": f"{advertisers[i % len(advertisers)]} - Spring {'Awareness' if i % 2 == 0 else 'Consideration'}",
        "objective": "Awareness" if i % 2 == 0 else "Consideration",
        "budget": float(rng.choice([8000, 10000, 12000, 15000, 18000])),
        "start_date": START.date().isoformat(),
        "end_date": (START + pd.Timedelta(days=FLIGHT_DAYS - 1)).date().isoformat(),
    })
campaigns = pd.DataFrame(campaigns)

# Line items: each campaign runs on 3 publishers x 3-4 placements
lines, deliv = [], []
lid = 0
for c in campaigns.itertuples():
    pubs = rng.choice(publishers.publisher_id, 3, replace=False)
    combos = []
    for pb in pubs:
        pl_pool = placements.placement_id.tolist()
        if pb != "PB3":                      # only StreamHub sells video in this sim
            pl_pool = [p for p in pl_pool if p != "P6"]
        for pl in rng.choice(pl_pool, rng.integers(3, 5), replace=False):
            combos.append((pb, pl))
    weights = rng.dirichlet(np.ones(len(combos)) * 2)
    for (pb, pl), wgt in zip(combos, weights):
        lid += 1
        P = placements.set_index("placement_id").loc[pl]
        B = publishers.set_index("publisher_id").loc[pb]
        cpm = round(P.base_cpm * B.cpm_factor * rng.uniform(0.92, 1.08), 2)
        budget = round(c.budget * wgt, 2)
        goal = int(budget / cpm * 1000)
        line_id = f"L{lid:03d}"
        lines.append({"line_id": line_id, "campaign_id": c.campaign_id, "publisher_id": pb,
                      "placement_id": pl, "booked_cpm": cpm, "line_budget": budget,
                      "impression_goal": goal})

        # ~25% of lines hit a delivery problem partway through the flight
        problem = rng.random() < 0.25
        break_day = int(rng.integers(6, 18)) if problem else None
        drop_to = rng.uniform(0.45, 0.80) if problem else 1.0
        base_rate = rng.uniform(0.97, 1.05)
        view = np.clip(P.base_viewability * B.view_factor * rng.uniform(0.95, 1.05), 0.2, 0.95)
        ctr = P.base_ctr * rng.uniform(0.85, 1.15)
        daily_goal = goal / FLIGHT_DAYS
        for d in range(FLIGHT_DAYS):
            date = START + pd.Timedelta(days=d)
            rate = base_rate
            if problem and d + 1 >= break_day:
                # problem ramps in over 3 days
                ramp = min(1.0, (d + 2 - break_day) / 3)
                rate = base_rate * (1 - ramp * (1 - drop_to))
            wk = 1.08 if date.dayofweek >= 5 and B.category in ("Sports", "Video/Ent") else 1.0
            impr = max(0, int(rng.normal(daily_goal * rate * wk, daily_goal * 0.07)))
            viewable = int(rng.binomial(impr, view))
            clicks = int(rng.binomial(impr, ctr))
            deliv.append({"date": date.date().isoformat(), "flight_day": d + 1, "line_id": line_id,
                          "impressions": impr, "viewable_impressions": viewable, "clicks": clicks,
                          "spend": round(impr * cpm / 1000, 2)})

lines = pd.DataFrame(lines)
deliv = pd.DataFrame(deliv)

for name, df in [("placements", placements), ("publishers", publishers), ("campaigns", campaigns),
                 ("line_items", lines), ("daily_delivery", deliv)]:
    df.to_csv(RAW / f"{name}.csv", index=False)

db = ROOT / "data" / "ad_campaigns.db"
db.unlink(missing_ok=True)
con = sqlite3.connect(db)
con.executescript((ROOT / "sql" / "schema.sql").read_text())
for name, df in [("placements", placements[["placement_id", "placement_name", "format"]]),
                 ("publishers", publishers[["publisher_id", "publisher_name", "category"]]),
                 ("campaigns", campaigns), ("line_items", lines), ("daily_delivery", deliv)]:
    df.to_sql(name, con, if_exists="append", index=False)
con.commit()
con.close()
print(f"campaigns={len(campaigns)} line_items={len(lines)} rows={len(deliv)} "
      f"impressions={deliv.impressions.sum():,}")
