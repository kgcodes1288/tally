#!/usr/bin/env python3
"""Download USAspending account data (File A balances, File B program activity/object class, File C awards incl. unlinked)
for chosen agencies and a fiscal year. Usage: fetch_usaspending.py FY AGENCY_ID:slug [...]"""
import json, sys, time, urllib.request, zipfile, io
from pathlib import Path
API = "https://api.usaspending.gov/api/v2/download/accounts/"
OUT = Path(__file__).parent / "raw" / "usaspending"
def post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=120))
fy, jobs = sys.argv[1], {}
for arg in sys.argv[2:]:
    aid, slug = arg.split(":")
    d = post(API, {"account_level": "treasury_account", "file_format": "csv", "filters": {"agency": aid, "fy": fy, "quarter": "4",
         "submission_types": ["account_balances", "object_class_program_activity", "award_financial"]}})
    jobs[slug] = d; print("queued", slug, d["file_name"], flush=True)
while jobs:
    for slug, d in list(jobs.items()):
        st = json.load(urllib.request.urlopen(d["status_url"], timeout=60))
        if st["status"] == "finished":
            dest = OUT / f"{slug}_fy{fy}"; dest.mkdir(parents=True, exist_ok=True)
            zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(d["file_url"], timeout=600).read())).extractall(dest)
            print("done", slug, st.get("total_rows"), "rows", flush=True); jobs.pop(slug)
        elif st["status"] == "failed":
            print("FAILED", slug, st.get("message"), flush=True); jobs.pop(slug)
    time.sleep(10)
