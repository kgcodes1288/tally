#!/usr/bin/env python3
"""Federal Spending workspace: USAspending.gov account data (DATA Act Files A, B and C), FY2025, six agencies.

Tables (schema ws_federal), every row scoped by agency_code:
  account_balances   File A: budgetary resources and status per Treasury account
  program_activity   File B: obligations and outlays by program activity and object class
  award_financial    File C: account-level spending tied to individual awards; award_category marks
                     assistance, contract, or unlinked (a File C row USAspending could not link to an award)
"""
import duckdb
from common import RAW, connect, load_table, money_cols, persona, secure

WS = "ws_federal"
AGENCIES = {  # folder slug -> (toptier code, name, persona role, persona title)
    "nasa": ("080", "National Aeronautics and Space Administration", "p_fed_nasa", "NASA budget analyst"),
    "education": ("091", "Department of Education", "p_fed_education", "Education budget analyst"),
    "energy": ("089", "Department of Energy", "p_fed_energy", "Energy budget analyst"),
    "epa": ("068", "Environmental Protection Agency", "p_fed_epa", "EPA budget analyst"),
    "nsf": ("049", "National Science Foundation", "p_fed_nsf", "NSF budget analyst"),
    "sba": ("073", "Small Business Administration", "p_fed_sba", "SBA budget analyst"),
}
ACCOUNT_KEYS = ["submission_period", "owning_agency_name", "reporting_agency_name", "treasury_account_symbol", "treasury_account_name",
                "federal_account_symbol", "federal_account_name", "budget_function", "budget_subfunction", "availability_type_code",
                "beginning_period_of_availability", "ending_period_of_availability"]
B_EXTRA = ["program_activity_reporting_key", "program_activity_code", "program_activity_name", "object_class_code", "object_class_name",
           "direct_or_reimbursable_funding_source", "disaster_emergency_fund_code", "disaster_emergency_fund_name"]
C_KEEP = ["program_activity_code", "program_activity_name", "object_class_code", "object_class_name", "disaster_emergency_fund_code",
          "transaction_obligated_amount", "gross_outlay_amount_FYB_to_period_end", "award_unique_key", "award_id_piid", "parent_award_id_piid",
          "award_id_fain", "award_id_uri", "award_base_action_date", "award_latest_action_date", "period_of_performance_start_date",
          "period_of_performance_current_end_date", "award_type_code", "award_type", "prime_award_base_transaction_description",
          "awarding_subagency_name", "awarding_office_name", "funding_subagency_name", "recipient_uei", "recipient_name",
          "recipient_parent_name", "recipient_country", "recipient_state", "recipient_city", "primary_place_of_performance_state",
          "cfda_number", "cfda_title", "product_or_service_code_description", "naics_code", "naics_description", "usaspending_permalink"]


def select(files_glob, keep, slug, extra=""):
    code = AGENCIES[slug][0]
    src = f"read_csv('{files_glob}', all_varchar=true, header=true, union_by_name=true)"
    cols = duckdb.sql(f"SELECT * FROM {src} LIMIT 0").columns
    keep = [c for c in keep if c in cols]
    money = set(money_cols(keep))
    exprs = [f"'{code}' AS agency_code"] + [
        f'TRY_CAST("{c}" AS DECIMAL(20,2)) AS "{c.lower()}"' if c in money
        else f'TRY_CAST("{c}" AS DATE) AS "{c.lower()}"' if c.endswith("_date")
        else f'"{c}" AS "{c.lower()}"' for c in keep]
    return f"SELECT {', '.join(exprs)}{extra} FROM {src}"


def main():
    pg = connect(); con = duckdb.connect()
    pg.execute(f"CREATE SCHEMA IF NOT EXISTS {WS}")
    pg.execute("""INSERT INTO tally.workspaces (id, name, description, scope_label) VALUES (%s,%s,%s,%s)
                  ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, description=EXCLUDED.description, scope_label=EXCLUDED.scope_label""",
               (WS, "Federal Spending", "USAspending.gov account and award data (DATA Act Files A, B, C) for six federal agencies, fiscal year 2025.", "agency"))
    roles = []
    for slug, (code, name, role, title) in AGENCIES.items():
        persona(pg, WS, role, title, f"Sees only {name} ({code}) data.", [code]); roles.append(role)
    persona(pg, WS, "p_fed_oversight", "Spending oversight lead", "Sees all six agencies, for cross-agency comparisons.", None)
    roles.append("p_fed_oversight")

    d = RAW / "usaspending"
    first_a = next((d / "nasa_fy2025").glob("*AccountBalances*.csv"))
    a_cols = duckdb.sql(f"SELECT * FROM read_csv('{first_a}', all_varchar=true) LIMIT 0").columns
    a_keep = ACCOUNT_KEYS + [c for c in a_cols if c in money_cols(a_cols)]
    first_b = next((d / "nasa_fy2025").glob("*ByPA-OC*.csv"))
    b_cols = duckdb.sql(f"SELECT * FROM read_csv('{first_b}', all_varchar=true) LIMIT 0").columns
    b_keep = ACCOUNT_KEYS + B_EXTRA + [c for c in b_cols if c in money_cols(b_cols)]

    A = " UNION ALL BY NAME ".join(select(str(d / f"{s}_fy2025" / "*AccountBalances*.csv"), a_keep, s) for s in AGENCIES)
    B = " UNION ALL BY NAME ".join(select(str(d / f"{s}_fy2025" / "*ByPA-OC*.csv"), b_keep, s) for s in AGENCIES)
    C = " UNION ALL BY NAME ".join(
        select(str(d / f"{s}_fy2025" / f"*_{kind}_AccountBreakdownByAward*.csv"), ACCOUNT_KEYS + C_KEEP, s, f", '{cat}' AS award_category")
        for s in AGENCIES for kind, cat in [("Assistance", "assistance"), ("Contracts", "contract"), ("Unlinked", "unlinked")])

    load_table(pg, con, A, WS, "account_balances", "File A: budgetary resources and status of each Treasury account (FY2025, period 12).")
    load_table(pg, con, B, WS, "program_activity", "File B: obligations and outlays by program activity and object class.")
    load_table(pg, con, C, WS, "award_financial", "File C: account-level spending linked to awards. award_category = assistance, contract, or unlinked.")
    pg.execute("""DROP TABLE IF EXISTS ws_federal.agencies; CREATE TABLE ws_federal.agencies (agency_code text PRIMARY KEY, agency_name text)""")
    for s, (code, name, *_) in AGENCIES.items(): pg.execute("INSERT INTO ws_federal.agencies VALUES (%s,%s)", (code, name))
    for t in ["account_balances", "program_activity", "award_financial", "agencies"]:
        secure(pg, WS, t, "agency_code", roles)
    pg.execute("CREATE INDEX ON ws_federal.award_financial (agency_code, award_category)")
    pg.execute("CREATE INDEX ON ws_federal.award_financial (award_unique_key)")
    pg.execute("CREATE INDEX ON ws_federal.program_activity (agency_code, treasury_account_symbol)")
    pg.execute("ANALYZE")
    print("federal workspace ready")


if __name__ == "__main__":
    main()
