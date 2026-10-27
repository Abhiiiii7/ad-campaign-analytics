-- Ad campaign delivery data model (SQLite)
-- One row per line item per day in daily_delivery.

CREATE TABLE placements (
    placement_id    TEXT PRIMARY KEY,
    placement_name  TEXT NOT NULL,
    format          TEXT NOT NULL            -- Display | Video
);

CREATE TABLE publishers (
    publisher_id    TEXT PRIMARY KEY,
    publisher_name  TEXT NOT NULL,
    category        TEXT
);

CREATE TABLE campaigns (
    campaign_id     TEXT PRIMARY KEY,
    advertiser      TEXT NOT NULL,
    campaign_name   TEXT NOT NULL,
    objective       TEXT,
    budget          REAL NOT NULL,
    start_date      TEXT NOT NULL,
    end_date        TEXT NOT NULL
);

-- A line item = one campaign on one publisher in one placement, with a booked goal
CREATE TABLE line_items (
    line_id          TEXT PRIMARY KEY,
    campaign_id      TEXT NOT NULL REFERENCES campaigns(campaign_id),
    publisher_id     TEXT NOT NULL REFERENCES publishers(publisher_id),
    placement_id     TEXT NOT NULL REFERENCES placements(placement_id),
    booked_cpm       REAL NOT NULL,
    line_budget      REAL NOT NULL,
    impression_goal  INTEGER NOT NULL
);

CREATE TABLE daily_delivery (
    date                  TEXT NOT NULL,
    flight_day            INTEGER NOT NULL,
    line_id               TEXT NOT NULL REFERENCES line_items(line_id),
    impressions           INTEGER NOT NULL,
    viewable_impressions  INTEGER NOT NULL,
    clicks                INTEGER NOT NULL,
    spend                 REAL NOT NULL,
    PRIMARY KEY (line_id, date)
);

CREATE INDEX ix_delivery_day ON daily_delivery(flight_day);
