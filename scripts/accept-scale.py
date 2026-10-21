#!/usr/bin/env python3
"""Measure bounded metadata APIs against a running resource-limited container."""
import argparse, json, time, urllib.request, urllib.parse, subprocess, statistics, threading
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--base-url", default="http://127.0.0.1:18080")
parser.add_argument("--container", default="rancher-validation")
parser.add_argument("--archive", default="/tmp/rancher-scale.tar.gz")
parser.add_argument("--output", default="artifacts/scale.json")
args = parser.parse_args()


def request(path, data=None, method=None):
    raw = (
        None
        if data is None
        else json.dumps(data).encode() if isinstance(data, dict) else data
    )
    req = urllib.request.Request(
        args.base_url + "/api/v1" + path,
        data=raw,
        method=method,
        headers={
            "Content-Type": (
                "application/json" if isinstance(data, dict) else "application/gzip"
            )
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r) if r.status != 204 else None


peak = [0]
running = [True]


def monitor():
    while running[0]:
        try:
            current = int(
                subprocess.check_output(
                    [
                        "docker",
                        "exec",
                        args.container,
                        "cat",
                        "/sys/fs/cgroup/memory.current",
                    ]
                )
            )
            peak[0] = max(peak[0], current)
        except Exception:
            pass
        time.sleep(0.1)


thread = threading.Thread(target=monitor)
thread.start()
case = request("/cases", {"name": "Synthetic scale acceptance"})
start = time.perf_counter()
try:
    bundle = request(
        f'/cases/{case["id"]}/bundles?filename=scale.tar.gz',
        Path(args.archive).read_bytes(),
    )
    base = "/bundles/" + bundle["id"]
    while True:
        status = request(base)
        if status["state"] in ("ready", "failed"):
            break
        if time.perf_counter() - start > 180:
            raise RuntimeError("import timeout")
        time.sleep(0.05)
    assert status["state"] == "ready", status
    elapsed = time.perf_counter() - start
    overview = request(base + "/overview")
    assert overview["counts"]["pods"] == 10000 and overview["counts"]["nodes"] == 300
    durations = []
    for i in range(20):
        startq = time.perf_counter()
        data = request(
            base + "/catalog/pods?namespace=ns-" + f"{i%100:03d}" + "&limit=50"
        )
        durations.append(time.perf_counter() - startq)
        assert len(data["items"]) == 50 and data["total"] == 100 and data["nextCursor"]
    options = request(base + "/catalog/pods?limit=50")
    assert len(options["items"]) == 50
    p95 = sorted(durations)[18]
    assert p95 < 1
    overview_bytes = len(json.dumps(overview, ensure_ascii=False).encode())
    assert overview_bytes < 256 * 1024
    index = status["indexBytes"]
    events = request(base + "/catalog/events")
    assert events["total"] == 1
    measured = int(
        subprocess.check_output(
            ["docker", "exec", args.container, "cat", "/sys/fs/cgroup/memory.peak"]
        )
    )
    peak[0] = max(peak[0], measured)
    oom_events = subprocess.check_output(
        ["docker", "exec", args.container, "cat", "/sys/fs/cgroup/memory.events"]
    ).decode()
    assert "oom_kill 0" in oom_events
    hwm = (
        subprocess.check_output(
            [
                "docker",
                "exec",
                args.container,
                "sh",
                "-c",
                "sed -n '/VmHWM/p' /proc/1/status",
            ]
        )
        .decode()
        .strip()
    )
    print("Server process high water mark: " + hwm)
    print(
        json.dumps(
            {
                "importSeconds": elapsed,
                "peakCgroupMemoryBytes": peak[0],
                "indexBytes": index,
                "overviewBytes": overview_bytes,
                "queryP95Seconds": p95,
                "pods": 10000,
                "nodes": 300,
                "samples": 20,
                "limits": "2 CPU / 1 GiB",
            },
            indent=2,
        )
    )
    output = Path(args.output)
    output.parent.mkdir(exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "importSeconds": elapsed,
                "peakCgroupMemoryBytes": peak[0],
                "indexBytes": index,
                "overviewBytes": overview_bytes,
                "queryP95Seconds": p95,
                "pods": 10000,
                "nodes": 300,
                "samples": 20,
            },
            indent=2,
        )
        + "\n"
    )
finally:
    request("/cases/" + case["id"], method="DELETE")
    running[0] = False
    thread.join()
