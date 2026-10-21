#!/usr/bin/env python3
"""Reimport a private pre-upgrade backup into an empty workspace."""
import argparse, json, time, http.client
from pathlib import Path
from urllib.parse import urlsplit, quote

parser = argparse.ArgumentParser()
parser.add_argument("--base-url", required=True)
parser.add_argument("--input", default=".data/upgrade-backup")
args = parser.parse_args()
url = urlsplit(args.base_url)
folder = Path(args.input)
manifest = json.loads((folder / "manifest.json").read_text())


def connection():
    return (
        http.client.HTTPSConnection
        if url.scheme == "https"
        else http.client.HTTPConnection
    )(url.netloc, timeout=120)


def request(path, data=None):
    conn = connection()
    conn.request(
        "POST" if data else "GET",
        "/api/v1" + path,
        json.dumps(data).encode() if data else None,
        {"Content-Type": "application/json"},
    )
    res = conn.getresponse()
    raw = res.read()
    assert res.status < 300, (res.status, raw)
    conn.close()
    return json.loads(raw)


assert not request("/cases"), "Restore requires an empty workspace to avoid duplicates"
restored = []
for case in manifest["cases"]:
    created = request("/cases", {"name": case["name"]})
    for bundle in case["bundles"]:
        path = folder / bundle["archive"]
        conn = connection()
        conn.putrequest(
            "POST",
            f'/api/v1/cases/{created["id"]}/bundles?filename=' + quote(bundle["name"]),
        )
        conn.putheader("Content-Type", "application/gzip")
        conn.putheader("Content-Length", str(path.stat().st_size))
        conn.endheaders()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                conn.send(chunk)
        res = conn.getresponse()
        raw = res.read()
        assert res.status == 202, (res.status, raw)
        record = json.loads(raw)
        conn.close()
        start = time.monotonic()
        while True:
            status = request("/bundles/" + record["id"])
            if status["state"] in ("ready", "failed"):
                break
            assert time.monotonic() - start < 300, "Import timed out"
            time.sleep(0.2)
        assert status["state"] == "ready", status
        summary = request("/bundles/" + record["id"] + "/overview")
        assert summary["counts"]["files"] == bundle["files"]
        logs = request("/bundles/" + record["id"] + "/catalog/logs?limit=200")["items"]
        nested = [l for l in logs if l["variant"] == "instance"]
        restored.append(
            {
                "files": summary["counts"]["files"],
                "pods": summary["counts"]["pods"],
                "nodes": summary["counts"]["nodes"],
                "nestedLogs": len(nested),
                "linkedNestedLogs": sum(bool(l["snapshotPodId"]) for l in nested),
                "podCoverage": summary["podLogCoverage"],
            }
        )
print(json.dumps({"restored": restored}, indent=2))
