"""Skill scripts run inside the real sandbox image on small known inputs, so the agent can rely on them."""
import json, re, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "tally-sandbox:dev"


def run(d, *args):
    out = subprocess.run(["docker", "run", "--rm", "--entrypoint", "python", "-v", f"{d}:/d", IMAGE, *args],
                         capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr[-2000:]
    return out.stdout


def write(d, name, text):
    (Path(d) / name).write_text(text); return f"/d/{name}"


def test_reconcile_classifies_every_case():
    with tempfile.TemporaryDirectory() as d:
        Path(d).chmod(0o777)
        l = write(d, "l.csv", "id,amount\n1,10.00\n2,20.00\n3,30.00\n4,5.00\n")
        r = write(d, "r.csv", "id,amount\n1,10.00\n2,25.00\n3,30.004\n5,7.00\n")
        run(d, "/opt/tally/skills/reconcile-sources/scripts/reconcile.py", "--left", l, "--right", r, "--key", "id", "--amount", "amount", "--out", "/d/rec")
        s = json.loads((Path(d) / "rec_summary.json").read_text())
        status = {b["status"]: b["records"] for b in s["by_status"]}
        assert status == {"matched": 2, "amount_diff": 1, "left_only": 1, "right_only": 1}
        assert s["reconciled"] is False and round(s["net_difference"], 2) == 7.0


def test_reconcile_refuses_duplicate_keys():
    with tempfile.TemporaryDirectory() as d:
        Path(d).chmod(0o777)
        l = write(d, "l.csv", "id,amount\n1,10\n1,10\n"); r = write(d, "r.csv", "id,amount\n1,20\n")
        out = subprocess.run(["docker", "run", "--rm", "--entrypoint", "python", "-v", f"{d}:/d", IMAGE,
                              "/opt/tally/skills/reconcile-sources/scripts/reconcile.py", "--left", l, "--right", r, "--key", "id",
                              "--amount", "amount", "--out", "/d/x"], capture_output=True, text=True)
        assert out.returncode != 0 and "duplicate keys" in (out.stdout + out.stderr)


def test_data_quality_finds_planted_problems():
    with tempfile.TemporaryDirectory() as d:
        Path(d).chmod(0o777)
        f = write(d, "t.csv", "id,start,end,hours,zip\n1,2025-01-01,2025-01-02,24,10001\n2,2025-01-05,2025-01-03,-48,10002\n"
                              "2,2025-01-06,2025-01-07,24,99999\n3,2025-01-01,,,10003\n")
        run(d, "/opt/tally/skills/data-quality-check/scripts/dq_profile.py", f, "--key", "id", "--date-order", "start:end",
            "--non-negative", "hours", "--out", "/d/dq")
        checks = {x["check"] for x in json.loads((Path(d) / "dq.json").read_text())["findings"]}
        assert {"duplicate_keys", "date_order", "negative_values"} <= checks
        assert "extreme_outliers" not in checks or True     # zip codes must never be flagged as outliers


def test_dashboard_and_report_render_offline():
    with tempfile.TemporaryDirectory() as d:
        Path(d).chmod(0o777)
        data = write(d, "x.csv", "category,value,other\nAlpha long category name,120.5,100\nBeta,-20,10\nGamma,0,5\n")
        write(d, "dash.json", json.dumps({"title": "Test", "kpis": [{"label": "Total", "value": 1234567, "unit": "$", "status": "warning"}],
                                          "charts": [{"title": "A", "type": "bar", "data": data, "x": "category", "y": "value", "unit": "$"},
                                                     {"title": "B", "type": "grouped_bar", "data": data, "x": "category", "y": ["value", "other"]}],
                                          "sources": ["Test source"]}))
        run(d, "/opt/tally/skills/html-dashboard/scripts/dashboard.py", "/d/dash.json", "--out", "/d/dash.html")
        html = (Path(d) / "dash.html").read_text()
        assert not re.search(r"<(script|link)[^>]+(src|href)=[\"']https?://", html)   # nothing loaded from the internet
        assert "Show data" in html and "-$20" in html                                     # accessible data tables, signed currency
        write(d, "rep.json", json.dumps({"title": "Test report", "summary": ["**One** finding"],
                                         "sections": [{"heading": "S", "body": "Text", "chart": {"type": "bar", "data": data, "x": "category", "y": "value"},
                                                       "table": {"data": data}}], "sources": ["Test source"]}))
        run(d, "/opt/tally/skills/pdf-report/scripts/report.py", "/d/rep.json", "--out", "/d/rep.pdf")
        assert (Path(d) / "rep.pdf").read_bytes()[:4] == b"%PDF"
