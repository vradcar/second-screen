# Fabric notebook: load the Second Screen synthetic season into Delta tables.
#
# 1. Upload the Parquet files:  python -m secondscreen.dataset --onelake "<workspace>/<lakehouse>"
#    (or drag data/season/*.parquet into the lakehouse: Files > second-screen > season_2026)
# 2. In the lakehouse, New notebook, attach this lakehouse, paste this cell, Run all.
# 3. Query with the SQL analytics endpoint, or build a Power BI report on the tables (Direct Lake).

BASE = "Files/second-screen/season_2026"
TABLES = ["clubs", "players", "matches", "standings", "events", "signals", "arcs", "player_match"]

for t in TABLES:
    df = spark.read.parquet(f"{BASE}/{t}.parquet")  # noqa: F821 - `spark` is provided by the notebook
    df.write.mode("overwrite").option("overwriteSchema", "true").format("delta").saveAsTable(f"ss_{t}")
    print(f"ss_{t}: {df.count():,} rows")

# --- How well does the engine find the hidden story arcs? (ground truth vs detection)
display(spark.sql("""
    SELECT kind,
           COUNT(*)                                    AS arcs,
           ROUND(AVG(CAST(detected AS INT)), 2)        AS recall,
           ROUND(AVG(detection_lag_min), 1)            AS avg_lag_min
    FROM ss_arcs GROUP BY kind ORDER BY recall DESC
"""))

# --- League table with expected goals: who is over- or under-performing?
display(spark.sql("""
    SELECT position, name, played, won, drawn, lost, gf, ga, points,
           ROUND(xg_for, 1) AS xg_for, ROUND(xg_against, 1) AS xg_against,
           ROUND(gf - xg_for, 1) AS finishing_vs_xg
    FROM ss_standings ORDER BY position
"""))

# --- Season leaders from the event feed
display(spark.sql("""
    SELECT player_name, team_id, COUNT(*) AS apps, SUM(goals) AS goals, ROUND(SUM(xg), 2) AS xg,
           ROUND(SUM(distance_m) / 1000 / COUNT(*), 1) AS km_per_match, MAX(top_speed_kmh) AS top_speed
    FROM ss_player_match GROUP BY player_name, team_id
    ORDER BY goals DESC, xg DESC LIMIT 15
"""))
