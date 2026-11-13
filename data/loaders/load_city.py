#!/usr/bin/env python3
"""City Operations workspace: NYC 311 service requests, January to March 2025 (NYC Open Data, dataset erm2-nwe9).

Scoped by borough. Requests with no borough ('Unspecified') are visible only to the citywide persona, which is
itself a realistic data-quality story. response_hours is derived from created and closed timestamps.
"""
import duckdb
from common import RAW, connect, load_table, persona, secure

WS = "ws_city"
SRC = RAW / "nyc311" / "nyc311_2025q1.csv"


def main():
    pg = connect(); con = duckdb.connect()
    pg.execute(f"CREATE SCHEMA IF NOT EXISTS {WS}")
    pg.execute("""INSERT INTO tally.workspaces (id, name, description, scope_label) VALUES (%s,%s,%s,%s)
                  ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, description=EXCLUDED.description, scope_label=EXCLUDED.scope_label""",
               (WS, "City Operations", "NYC 311 service requests from January to March 2025: complaint types, agencies, locations and resolution times.", "borough"))
    personas = [("p_city_brooklyn", "Brooklyn borough operations manager", "Service requests in Brooklyn.", ["BROOKLYN"]),
                ("p_city_bronx", "Bronx borough operations manager", "Service requests in the Bronx.", ["BRONX"]),
                ("p_city_manhattan", "Manhattan borough operations manager", "Service requests in Manhattan.", ["MANHATTAN"]),
                ("p_city_citywide", "Citywide operations director", "All boroughs, including requests with no borough recorded.", None)]
    for role, title, desc, scopes in personas:
        persona(pg, WS, role, title, desc, scopes)
    q = f"""SELECT unique_key, created_date, closed_date,
              round(date_diff('second', created_date, closed_date) / 3600.0, 2)::DOUBLE AS response_hours,
              agency, agency_name, complaint_type, descriptor, location_type, incident_zip,
              upper(coalesce(nullif(borough, ''), 'UNSPECIFIED')) AS borough, city, status, resolution_description,
              resolution_action_updated_date, community_board, open_data_channel_type, latitude, longitude
            FROM read_csv('{SRC}', header=true, sample_size=-1)"""
    load_table(pg, con, q, WS, "service_requests",
               "NYC 311 service requests, Q1 2025. response_hours = closed_date minus created_date (null while open). Negative values are data errors.")
    secure(pg, WS, "service_requests", "borough", [p[0] for p in personas])
    for c in ["borough, created_date", "complaint_type", "agency"]:
        pg.execute(f"CREATE INDEX ON {WS}.service_requests ({c})")
    pg.execute("ANALYZE")
    print("city workspace ready")


if __name__ == "__main__":
    main()
