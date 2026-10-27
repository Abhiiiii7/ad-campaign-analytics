-- ============================================================
-- Ad Campaign Performance Analytics - analysis queries (SQLite)
-- Each query is named with "-- name: <query_name>" so the Python
-- runner can execute them one by one.
-- ============================================================

-- name: placement_kpis
-- CPM, CTR, viewability and viewable CPM by placement.
-- vCPM (cost per 1,000 viewable impressions) is the fair way to compare
-- placements: a cheap banner nobody sees isn't cheap.
SELECT
    p.placement_name,
    p.format,
    SUM(d.impressions)                                           AS impressions,
    SUM(d.viewable_impressions)                                  AS viewable_impressions,
    SUM(d.clicks)                                                AS clicks,
    ROUND(SUM(d.spend), 2)                                       AS spend,
    ROUND(SUM(d.spend) * 1000.0 / SUM(d.impressions), 2)         AS cpm,
    ROUND(100.0 * SUM(d.clicks) / SUM(d.impressions), 3)         AS ctr_pct,
    ROUND(100.0 * SUM(d.viewable_impressions) / SUM(d.impressions), 1) AS viewability_pct,
    ROUND(SUM(d.spend) * 1000.0 / SUM(d.viewable_impressions), 2) AS vcpm
FROM daily_delivery d
JOIN line_items l  ON l.line_id = d.line_id
JOIN placements p  ON p.placement_id = l.placement_id
GROUP BY p.placement_name, p.format
ORDER BY vcpm;

-- name: publisher_placement_kpis
-- Same KPIs at publisher x placement level - where the reallocation
-- opportunity actually lives.
SELECT
    pb.publisher_name,
    p.placement_name,
    p.format,
    SUM(d.impressions)                                            AS impressions,
    SUM(d.viewable_impressions)                                   AS viewable_impressions,
    ROUND(SUM(d.spend), 2)                                        AS spend,
    ROUND(SUM(d.spend) * 1000.0 / SUM(d.impressions), 2)          AS cpm,
    ROUND(100.0 * SUM(d.viewable_impressions) / SUM(d.impressions), 1) AS viewability_pct,
    ROUND(SUM(d.spend) * 1000.0 / SUM(d.viewable_impressions), 2) AS vcpm
FROM daily_delivery d
JOIN line_items l  ON l.line_id = d.line_id
JOIN placements p  ON p.placement_id = l.placement_id
JOIN publishers pb ON pb.publisher_id = l.publisher_id
GROUP BY pb.publisher_name, p.placement_name, p.format
ORDER BY vcpm;

-- name: line_daily_pacing
-- Daily pacing per line item using window functions:
--   cumulative delivered, expected-to-date, pace index,
--   3-day run rate and a projected final.
WITH daily AS (
    SELECT
        d.line_id,
        d.flight_day,
        d.impressions,
        l.impression_goal,
        l.campaign_id,
        l.publisher_id,
        SUM(d.impressions) OVER (PARTITION BY d.line_id ORDER BY d.flight_day)          AS cum_delivered,
        AVG(d.impressions) OVER (PARTITION BY d.line_id ORDER BY d.flight_day
                                 ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)            AS run_rate_3d
    FROM daily_delivery d
    JOIN line_items l ON l.line_id = d.line_id
)
SELECT
    line_id,
    campaign_id,
    publisher_id,
    flight_day,
    impressions,
    impression_goal,
    cum_delivered,
    impression_goal * flight_day / 30.0                                      AS expected_to_date,
    ROUND(cum_delivered / (impression_goal * flight_day / 30.0), 3)          AS pace_index,
    ROUND(run_rate_3d, 0)                                                    AS run_rate_3d,
    ROUND(cum_delivered + run_rate_3d * (30 - flight_day), 0)                AS projected_final,
    ROUND((cum_delivered + run_rate_3d * (30 - flight_day)) * 1.0 / impression_goal, 3) AS projected_pct_of_goal
FROM daily
ORDER BY line_id, flight_day;

-- name: line_outcomes
-- Final outcome per line item. Under-delivered = finished below 90% of goal.
SELECT
    l.line_id,
    l.campaign_id,
    pb.publisher_name,
    p.placement_name,
    l.impression_goal,
    SUM(d.impressions)                                       AS delivered,
    ROUND(1.0 * SUM(d.impressions) / l.impression_goal, 3)   AS pct_of_goal,
    CASE WHEN 1.0 * SUM(d.impressions) / l.impression_goal < 0.90
         THEN 1 ELSE 0 END                                   AS under_delivered
FROM line_items l
JOIN daily_delivery d ON d.line_id = l.line_id
JOIN publishers pb    ON pb.publisher_id = l.publisher_id
JOIN placements p     ON p.placement_id = l.placement_id
GROUP BY l.line_id, l.campaign_id, pb.publisher_name, p.placement_name, l.impression_goal;

-- name: publisher_delivery
-- Delivery vs goal by publisher - who under-delivers most.
SELECT
    pb.publisher_name,
    COUNT(DISTINCT l.line_id)                                         AS line_items,
    SUM(l.impression_goal)                                            AS goal,
    SUM(x.delivered)                                                  AS delivered,
    ROUND(100.0 * SUM(x.delivered) / SUM(l.impression_goal), 1)       AS pct_of_goal,
    SUM(CASE WHEN 1.0 * x.delivered / l.impression_goal < 0.90 THEN 1 ELSE 0 END) AS lines_under_90pct
FROM line_items l
JOIN (SELECT line_id, SUM(impressions) AS delivered
      FROM daily_delivery GROUP BY line_id) x ON x.line_id = l.line_id
JOIN publishers pb ON pb.publisher_id = l.publisher_id
GROUP BY pb.publisher_name
ORDER BY pct_of_goal;
