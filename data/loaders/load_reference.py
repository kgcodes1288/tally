#!/usr/bin/env python3
"""Structured reference data that connects to each workspace's main tables, so the agent can answer
cross-source questions (trends, currency conversion, seasonality, weather, per-capita rates).

  ws_federal.agency_budget_history   USAspending agency API: budgetary resources, obligations, outlays by fiscal year
  ws_federal.agency_obligation_pace  same source: cumulative obligations by fiscal year and period (month)
  ws_retail.fx_brl_usd               Central Bank of Brazil (SGS series 1): BRL per USD, daily
  ws_retail.holidays                 BrasilAPI: Brazilian national holidays
  ws_retail.states                   Brazil's 27 federative units and their regions (static reference)
  ws_city.weather_daily              Open-Meteo historical weather for Central Park (CC BY 4.0)
  ws_city.community_districts        NYC Open Data: population by community district (latest census in source: 2010)
"""
import json, urllib.request
import duckdb
from common import connect, load_table, secure, WORK

UA = {"User-Agent": "Tally (personal open-source project)"}


def get(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120))


def stage(name, rows):
    """Write rows (list of dicts) to a JSON file DuckDB can read."""
    p = WORK / f"{name}.json"; p.write_text(json.dumps(rows)); return f"read_json_auto('{p}')"


def shared(pg, ws, table):
    for (r,) in pg.execute("SELECT pg_role FROM tally.personas WHERE workspace_id=%s", (ws,)):
        pg.execute(f"GRANT SELECT ON {ws}.{table} TO {r}")


def federal(pg, con):
    agencies = [c for (c,) in pg.execute("SELECT agency_code FROM ws_federal.agencies ORDER BY 1")]
    years, pace = [], []
    for code in agencies:
        for y in get(f"https://api.usaspending.gov/api/v2/agency/{code}/budgetary_resources/")["agency_data_by_year"]:
            if y["agency_budgetary_resources"] is None: continue
            years.append({"agency_code": code, "fiscal_year": y["fiscal_year"], "budgetary_resources": y["agency_budgetary_resources"],
                          "total_obligated": y["agency_total_obligated"], "total_outlayed": y["agency_total_outlayed"]})
            for p in y.get("agency_obligation_by_period") or []:
                pace.append({"agency_code": code, "fiscal_year": y["fiscal_year"], "period": p["period"], "cumulative_obligated": p["obligated"]})
    roles = [r for (r,) in pg.execute("SELECT pg_role FROM tally.personas WHERE workspace_id='ws_federal'")]
    load_table(pg, con, f"SELECT agency_code::VARCHAR AS agency_code, fiscal_year::INTEGER AS fiscal_year, "
                        f"budgetary_resources::DECIMAL(20,2) AS budgetary_resources, total_obligated::DECIMAL(20,2) AS total_obligated, "
                        f"total_outlayed::DECIMAL(20,2) AS total_outlayed FROM {stage('budget', years)}",
               "ws_federal", "agency_budget_history", "Agency-wide budgetary resources, obligations and outlays by fiscal year (USAspending agency API). Current year may be partial.")
    load_table(pg, con, f"SELECT agency_code::VARCHAR AS agency_code, fiscal_year::INTEGER AS fiscal_year, period::INTEGER AS period, "
                        f"cumulative_obligated::DECIMAL(20,2) AS cumulative_obligated FROM {stage('pace', pace)}",
               "ws_federal", "agency_obligation_pace", "Cumulative agency obligations by fiscal year and period (period 1 = October). Use for spending-pace questions.")
    for t in ["agency_budget_history", "agency_obligation_pace"]: secure(pg, "ws_federal", t, "agency_code", roles)


STATES = [("AC", "Acre", "North"), ("AL", "Alagoas", "Northeast"), ("AP", "Amapá", "North"), ("AM", "Amazonas", "North"), ("BA", "Bahia", "Northeast"),
          ("CE", "Ceará", "Northeast"), ("DF", "Distrito Federal", "Center-West"), ("ES", "Espírito Santo", "Southeast"), ("GO", "Goiás", "Center-West"),
          ("MA", "Maranhão", "Northeast"), ("MT", "Mato Grosso", "Center-West"), ("MS", "Mato Grosso do Sul", "Center-West"), ("MG", "Minas Gerais", "Southeast"),
          ("PA", "Pará", "North"), ("PB", "Paraíba", "Northeast"), ("PR", "Paraná", "South"), ("PE", "Pernambuco", "Northeast"), ("PI", "Piauí", "Northeast"),
          ("RJ", "Rio de Janeiro", "Southeast"), ("RN", "Rio Grande do Norte", "Northeast"), ("RS", "Rio Grande do Sul", "South"), ("RO", "Rondônia", "North"),
          ("RR", "Roraima", "North"), ("SC", "Santa Catarina", "South"), ("SP", "São Paulo", "Southeast"), ("SE", "Sergipe", "Northeast"), ("TO", "Tocantins", "North")]


def retail(pg, con):
    fx = get("https://api.bcb.gov.br/dados/serie/bcdata.sgs.1/dados?formato=json&dataInicial=01/01/2016&dataFinal=31/12/2018")
    load_table(pg, con, f"SELECT strptime(data, '%d/%m/%Y')::DATE AS rate_date, valor::DECIMAL(10,6) AS brl_per_usd FROM {stage('fx', fx)}",
               "ws_retail", "fx_brl_usd", "Central Bank of Brazil PTAX selling rate, BRL per 1 USD, business days only. For a weekend date use the latest prior rate.")
    hol = [h | {"year": y} for y in (2016, 2017, 2018) for h in get(f"https://brasilapi.com.br/api/feriados/v1/{y}")]
    load_table(pg, con, f"SELECT date::DATE AS holiday_date, name, type FROM {stage('hol', hol)}",
               "ws_retail", "holidays", "Brazilian national holidays 2016 to 2018 (names in Portuguese), from BrasilAPI.")
    st = [{"state": a, "state_name": n, "region": r} for a, n, r in STATES]
    load_table(pg, con, f"SELECT * FROM {stage('states', st)}", "ws_retail", "states", "Brazil's 27 federative units (two-letter code) and their official regions.")
    for t in ["fx_brl_usd", "holidays", "states"]: shared(pg, "ws_retail", t)


def city(pg, con):
    w = get("https://archive-api.open-meteo.com/v1/archive?latitude=40.7789&longitude=-73.9692&start_date=2025-01-01&end_date=2025-03-31"
            "&daily=temperature_2m_min,temperature_2m_max,temperature_2m_mean,precipitation_sum,snowfall_sum&temperature_unit=fahrenheit"
            "&precipitation_unit=inch&timezone=America/New_York")["daily"]
    rows = [dict(zip(w.keys(), vals)) for vals in zip(*w.values())]
    load_table(pg, con, f"SELECT time::DATE AS weather_date, temperature_2m_min::DOUBLE AS temp_min_f, temperature_2m_max::DOUBLE AS temp_max_f, "
                        f"temperature_2m_mean::DOUBLE AS temp_mean_f, precipitation_sum::DOUBLE AS precipitation_in, snowfall_sum::DOUBLE AS snowfall_in FROM {stage('wx', rows)}",
               "ws_city", "weather_daily", "Daily weather for Central Park, Q1 2025, from Open-Meteo historical reanalysis (CC BY 4.0). Fahrenheit and inches.")
    cd = get("https://data.cityofnewyork.us/resource/xi7c-iiu2.json?$limit=100")
    load_table(pg, con, f"SELECT upper(borough) AS borough, cd_number::INTEGER AS cd_number, cd_name, _2010_population::INTEGER AS population_2010, "
                        f"_2000_population::INTEGER AS population_2000 FROM {stage('cd', cd)}",
               "ws_city", "community_districts", "Population by NYC community district. Latest census in this source is 2010, so per-capita rates are approximate.")
    for t in ["weather_daily", "community_districts"]: shared(pg, "ws_city", t)


if __name__ == "__main__":
    pg, con = connect(), duckdb.connect()
    federal(pg, con); retail(pg, con); city(pg, con)
    pg.execute("ANALYZE"); print("reference data ready")
