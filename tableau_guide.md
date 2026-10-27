# Tableau Build Guide — Pacing & Under-Delivery Dashboard

Build time is about 60–90 minutes in Tableau Public (free). Use the files in `output/tableau/`. When you're done, your numbers should match `output/findings.md`.

## 1. Connect

Connect → Text file, then add these as **separate data sources** (no joins needed):

| File | Use for |
|---|---|
| `delivery_fact.csv` | Placement and publisher KPIs, trends |
| `line_daily_pacing.csv` | Pacing curves, at-risk list |
| `alert_backtest.csv` | Weekly vs daily alert comparison |
| `publisher_delivery.csv` | Delivery vs goal by publisher |

Set `date` to Date and `flight_day` to a dimension (discrete for tables, continuous for lines).

## 2. Calculated fields

On **delivery_fact**:
```
CPM            = SUM([Spend]) / SUM([Impressions]) * 1000
CTR            = SUM([Clicks]) / SUM([Impressions])
Viewability    = SUM([Viewable Impressions]) / SUM([Impressions])
vCPM           = SUM([Spend]) / SUM([Viewable Impressions]) * 1000
```

On **line_daily_pacing**:
```
At Risk        = [Projected Pct Of Goal] < 0.9
Pace Status    = IF [Pace Index] < 0.9 THEN "Behind"
                 ELSEIF [Pace Index] > 1.1 THEN "Ahead"
                 ELSE "On track" END
```

**Parameter:** `As Of Day` (integer, 1–30, default 14). Add it to a filter on `line_daily_pacing` with `[Flight Day] = [As Of Day]`.

## 3. Sheets

1. **Placement Value.** Bar chart: Placement on rows, vCPM on columns, sorted ascending. Put CPM and Viewability in the tooltip. Color by Format.
2. **CPM vs Viewability.** Scatter: CPM on X, Viewability on Y, Publisher × Placement on detail, size = SUM(Spend).
3. **Pacing by Publisher.** Using the `As Of Day` filter: Publisher on rows, AVG(Pace Index) as a bar. Add a reference line at 0.9 labeled "Behind". Color by Pace Status.
4. **At-Risk Line Items.** Table filtered to `At Risk = True` at the As Of Day: Line, Publisher, Placement, Pace Index, Projected Pct Of Goal. Sort by Projected Pct Of Goal ascending. This is the list you'd send to the publisher.
5. **Pacing Curve.** Line: Flight Day (continuous) vs SUM(Cum Delivered) and SUM(Expected To Date), dual axis synchronized. Add a filter on Line Id so you can pick one line.
6. **Alert Lead Time.** From `alert_backtest.csv`, filtered to `Under Delivered = 1`. Calculated field `Days Earlier = IFNULL([Old Flag Day],30) - IFNULL([New Flag Day],30)`. Show it as a histogram.

## 4. Dashboard

**Page "Pacing Monitor":** the As Of Day slider at the top, then sheets 3 and 4 side by side, then sheet 5. Set sheet 4 to act as a filter on sheet 5, so clicking an at-risk line shows its curve.

**Page "Placement Value":** sheets 1 and 2, plus a text box with the finding: cheap banners are about 12% cheaper per viewable impression, not 50%.

## 5. Check against findings.md

| Check | Should read |
|---|---|
| Total impressions | 30,149,491 |
| Below-the-fold vCPM | $8.54 |
| Interstitial viewability | 82.4% |
| Under-delivered lines (`under_delivered = 1`) | 35 |
| Median Days Earlier | 6 |

Publish to Tableau Public and put the link and 2 screenshots in the README.
