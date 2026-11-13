"""Sandbox attack tests: run hostile code inside a task sandbox, with exactly the settings tasks use,
and check that every attempt to break out fails. No model calls, so these cost nothing.

Run: cd tests && ../.venv/bin/python -m pytest test_sandbox.py -q
"""
import json, subprocess, sys, tempfile, textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from orchestrator import IMAGE, sandbox_args

PROBE = r'''
import json, os, socket, subprocess, pathlib
r = {}
def tcp(host, port, t=2):
    s = socket.socket(); s.settimeout(t)
    try: s.connect((host, port)); return "OPEN"
    except Exception as e: return type(e).__name__
    finally: s.close()
# network
r["internet_ip"] = tcp("1.1.1.1", 443)
r["dns"] = (lambda: (socket.gethostbyname("api.anthropic.com"), "RESOLVED")[1])() if False else None
try: socket.gethostbyname("api.anthropic.com"); r["dns"] = "RESOLVED"
except Exception as e: r["dns"] = type(e).__name__
r["host_ports"] = {p: tcp("172.30.0.1", p, 1) for p in (22, 80, 443, 2283, 5432, 5433, 5901, 8080, 8088, 8096, 3493)}
r["db"] = tcp("172.30.0.10", 5432)
r["proxy"] = tcp("172.30.0.11", 8080)
# identity and kernel
r["uid"] = os.getuid(); r["kernel"] = os.uname().release
r["caps"] = [l for l in open("/proc/self/status") if l.startswith("CapEff")][0].split()[1]
# filesystem
def can_write(p):
    try: pathlib.Path(p).write_text("x"); return "WRITABLE"
    except Exception as e: return type(e).__name__
r["write"] = {p: can_write(p) for p in ("/etc/x", "/usr/x", "/opt/tally/x", "/workspace/x", "/tmp/x")}
r["host_files"] = {p: os.path.exists(p) for p in ("/home/karthick1288", "/var/run/docker.sock", "/opt/stacks", "/root/.ssh")}
try: os.setuid(0); r["setuid0"] = "SUCCEEDED"
except Exception as e: r["setuid0"] = type(e).__name__
print(json.dumps(r))
'''


@pytest.fixture(scope="module")
def probe():
    with tempfile.TemporaryDirectory() as d:
        run = Path(d)
        for sub in ("workspace", "task"):
            (run / sub).mkdir(); (run / sub).chmod(0o777)
        out = subprocess.run(["docker", "run", "--rm", "--entrypoint", "python"] + sandbox_args(run, {}) + [IMAGE, "-c", PROBE],
                             capture_output=True, text=True, timeout=180)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout.strip().splitlines()[-1])


def test_no_internet(probe):
    assert probe["internet_ip"] != "OPEN"
    assert probe["dns"] != "RESOLVED"


def test_host_services_unreachable(probe):
    open_ports = [p for p, v in probe["host_ports"].items() if v == "OPEN"]
    assert open_ports == [], f"sandbox can reach Lasso services on ports {open_ports}"


def test_only_db_and_proxy_reachable(probe):
    assert probe["db"] == "OPEN" and probe["proxy"] == "OPEN"


def test_unprivileged_under_gvisor(probe):
    assert probe["uid"] == 1000
    assert "gvisor" in probe["kernel"]
    assert int(probe["caps"], 16) == 0, "process has Linux capabilities"
    assert probe["setuid0"] != "SUCCEEDED"


def test_filesystem_is_contained(probe):
    w = probe["write"]
    assert w["/workspace/x"] == "WRITABLE" and w["/tmp/x"] == "WRITABLE"
    assert all(w[p] != "WRITABLE" for p in ("/etc/x", "/usr/x", "/opt/tally/x"))
    assert not any(probe["host_files"].values()), probe["host_files"]
