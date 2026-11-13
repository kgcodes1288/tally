"""Row-level security must hold even against a hostile query. Run: .venv/bin/python -m pytest tests/ -q"""
import secrets, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import psycopg, pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data" / "loaders"))
from common import connect, db_url

def temp_login(persona):
    """What the platform does per task: a LOGIN role that inherits one persona and expires in an hour."""
    admin = connect(); name = "t_" + secrets.token_hex(4); pw = secrets.token_hex(16)
    admin.execute(f"CREATE ROLE {name} LOGIN PASSWORD '{pw}' IN ROLE {persona} VALID UNTIL '{(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}'")
    info = psycopg.conninfo.conninfo_to_dict(db_url()); info.update(user=name, password=pw)
    return admin, name, psycopg.connect(**info, autocommit=True)

@pytest.fixture
def nasa():
    admin, name, c = temp_login("p_fed_nasa"); yield c; c.close(); admin.execute(f"DROP ROLE {name}")

@pytest.fixture
def oversight():
    admin, name, c = temp_login("p_fed_oversight"); yield c; c.close(); admin.execute(f"DROP ROLE {name}")

def test_analyst_sees_only_own_agency(nasa):
    rows = nasa.execute("SELECT DISTINCT agency_code FROM ws_federal.award_financial").fetchall()
    assert rows == [("080",)]

def test_filters_cannot_widen_scope(nasa):
    assert nasa.execute("SELECT count(*) FROM ws_federal.award_financial WHERE agency_code <> '080'").fetchone()[0] == 0
    assert nasa.execute("SELECT count(*) FROM ws_federal.account_balances WHERE agency_code = '091' OR true").fetchone()[0] == \
           nasa.execute("SELECT count(*) FROM ws_federal.account_balances").fetchone()[0]

def test_oversight_sees_all_six(oversight):
    assert oversight.execute("SELECT count(DISTINCT agency_code) FROM ws_federal.award_financial").fetchone()[0] == 6

@pytest.mark.parametrize("attack", [
    "SET ROLE p_fed_oversight",
    "SELECT * FROM tally.role_scopes",
    "INSERT INTO tally.role_scopes VALUES ('p_fed_nasa', '091')",
    "ALTER TABLE ws_federal.award_financial DISABLE ROW LEVEL SECURITY",
    "DELETE FROM ws_federal.award_financial",
    "CREATE TABLE ws_federal.x (a int)",
])
def test_privilege_escalation_is_refused(nasa, attack):
    with pytest.raises(psycopg.Error):
        nasa.execute(attack)


@pytest.mark.parametrize("persona_role, table, scope_col, expected", [
    ("p_ret_sp", "ws_retail.orders", "customer_state", {"SP"}),
    ("p_ret_south", "ws_retail.order_payments", "customer_state", {"PR", "SC", "RS"}),
    ("p_ret_rj", "ws_retail.sellers", "seller_state", {"RJ"}),
    ("p_city_bronx", "ws_city.service_requests", "borough", {"BRONX"}),
])
def test_each_workspace_scopes_rows(persona_role, table, scope_col, expected):
    admin, name, c = temp_login(persona_role)
    try:
        assert {v for (v,) in c.execute(f"SELECT DISTINCT {scope_col} FROM {table}")} == expected
    finally:
        c.close(); admin.execute(f"DROP ROLE {name}")


def test_personas_cannot_cross_workspaces():
    admin, name, c = temp_login("p_ret_sp")
    try:
        with pytest.raises(psycopg.Error):
            c.execute("SELECT count(*) FROM ws_city.service_requests")
    finally:
        c.close(); admin.execute(f"DROP ROLE {name}")


def test_unspecified_borough_only_citywide():
    for role, n_expected in [("p_city_manhattan", 0), ("p_city_citywide", 557)]:
        admin, name, c = temp_login(role)
        try:
            assert c.execute("SELECT count(*) FROM ws_city.service_requests WHERE borough='UNSPECIFIED'").fetchone()[0] == n_expected
        finally:
            c.close(); admin.execute(f"DROP ROLE {name}")


def test_reference_tables_respect_scope_or_are_shared():
    admin, name, c = temp_login("p_fed_epa")
    try:
        assert {v for (v,) in c.execute("SELECT DISTINCT agency_code FROM ws_federal.agency_budget_history")} == {"068"}
    finally:
        c.close(); admin.execute(f"DROP ROLE {name}")
    admin, name, c = temp_login("p_city_bronx")
    try:
        assert c.execute("SELECT count(*) FROM ws_city.weather_daily").fetchone()[0] == 90
    finally:
        c.close(); admin.execute(f"DROP ROLE {name}")
