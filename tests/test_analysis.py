import json
import sqlite3
import time
from pathlib import Path
from threading import Event
import pytest
from backend.analysis.engine import Analysis
from backend.analysis.config import thresholds
from backend.analysis import parsers
from backend.catalog import IndexedBundle
from backend.config import Settings
from conftest import upload, make_archive


def make(tmp_path, files, **settings):
    root = tmp_path / "files"
    root.mkdir(parents=True)
    for path, text in {
        "summary.txt": "Hostname: node1\nDistro: rke2\n",
        **files,
    }.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(
            text
            if isinstance(text, bytes)
            else json.dumps(text).encode() if isinstance(text, dict) else text.encode()
        )
    bundle = IndexedBundle(root, tmp_path / "metadata.sqlite")
    return Analysis(
        bundle, tmp_path / "analysis.sqlite", Settings(data_dir=tmp_path, **settings)
    )


def finish(a, max_steps=10000):
    for _ in range(max_steps):
        if not a.step():
            break
    else:
        raise AssertionError("analysis did not yield/finish")
    assert a.state != "failed", a.status()
    return a


def test_host_parser_boundaries():
    assert (
        parsers.memory(
            "total used free shared buff/cache available\nMem: 2Gi 1Gi 1Mi 1Mi 1Gi 900Mi\nSwap: 0B 0B 0B"
        )["available"]
        == 900 * 1024**2
    )
    assert (
        parsers.cpu("r b us sy id wa\n0 0 99 0 1 0\n0 0 2 3 90 5\n", "")["busy"] == 10
    )
    assert parsers.cpu("", "%Cpu(s): 10.0 us, 5.0 sy, 80.0 id, 5.0 wa")["iowait"] == 5
    assert parsers.cpu("corrupt", "corrupt") is None
    assert parsers.processes(
        "USER PID STAT COMMAND\nroot 1 S zombie-app\nroot 2 Z dead"
    ) == [{"pid": "2", "state": "Z"}]
    rows = parsers.disks(
        "Filesystem Size Used Avail Use% Mounted on\n/dev/a 1G 900M 100M 90% /\n/dev/a 1G 900M 100M 90% /var/lib/kubelet\noverlay 1G 1G 0 100% /ignored"
    )
    assert len(rows) == 1 and rows[0]["mountCount"] == 2


def test_snapshots_roles_events_and_etcd_follower(tmp_path):
    a = make(
        tmp_path,
        {
            "systeminfo/systemd-units": "rke2-server.service loaded active running server\nrke2-agent.service loaded inactive dead agent\n",
            "systeminfo/freeh": "total used free shared buff/cache available\nMem: 10Gi 9Gi 1Mi 1Mi 1Gi 400Mi\nSwap: 0B 0B 0B",
            "systeminfo/sysctla": "net.ipv4.ip_forward = 1\nvm.swappiness = 60\n",
            "systeminfo/vmstat": "r b us sy id wa\n0 0 99 0 1 0\n0 0 1 1 96 2\n",
            "systeminfo/lscpu": "CPU(s): 4",
            "systeminfo/uptime": "load average: 2.00, 2.00, 2.00",
            "systeminfo/ps": "USER PID STAT COMMAND\nroot 1 S zombie-app\nroot 2 Z dead",
            "etcd/endpointhealth": "https://127.0.0.1:2379 is healthy: committed",
            "etcd/endpointstatus": "| ENDPOINT | ID | IS LEADER | ERRORS |\n| https://127.0.0.1:2379 | member1 | false | |",
            "etcd/memberlist": "member1, started, node1, https://127.0.0.1:2380, https://127.0.0.1:2379, false\nmember2, started, node2, https://127.0.0.2:2380, https://127.0.0.2:2379, false",
            "etcd/alarmlist": "",
            "etcd/etcd-metrics-local.txt": "etcd_server_has_leader 1\netcd_mvcc_db_total_size_in_bytes 90\netcd_server_quota_backend_bytes 100\netcd_server_leader_changes_seen_total 4",
            "rke2/kubectl/pods": "NAMESPACE   NAME   READY   STATUS   RESTARTS   AGE   NODE\nbusiness    run    1/1     Running  90         1d    node1\nbusiness    done   0/1     Completed   2       1d    node1\nbusiness    bad    0/1     Pending  0          1m    node1\n",
            "rke2/kubectl/events": "NAMESPACE   TYPE      REASON             OBJECT    MESSAGE\nbusiness    Warning   FailedScheduling   pod/bad   insufficient cpu\n",
        },
    )
    finish(a)
    rows = a.findings(limit=200)["items"]
    rules = {r["ruleId"] for r in rows}
    assert "service.distribution" not in rules
    assert "init.swap" not in rules
    assert "etcd.leader" not in rules
    assert "etcd.memberCoverage" in rules
    assert "host.zombies" in rules
    assert (
        next(r for r in rows if r["ruleId"] == "host.memoryAvailable")["severity"]
        == "high"
    )
    assert (
        next(r for r in rows if r["ruleId"] == "etcd.etcdQuota")["severity"]
        == "warning"
    )
    assert not any(r["object"]["name"] in ("run", "done") for r in rows)
    assert (
        next(r for r in rows if r["object"]["name"] == "bad")["severity"] == "warning"
    )
    assert a.status()["coverage"]["structuredComplete"]
    assert a.status()["observations"]


def test_log_scoping_chunk_overlap_continue_and_dedup(tmp_path):
    # A keyword crossing the two-MiB chunk edge and one crossing the scan-window edge.
    text = b"a" * (2 * 1024 * 1024 - 9) + b"apply request took too long\n"
    text += b"b" * (2 * 1024 * 1024 - 15) + b"apply request took too long\n"
    a = make(
        tmp_path,
        {
            "rke2/kubectl/pods": "NAMESPACE   NAME   READY   STATUS   RESTARTS   AGE\nkube-system   etcd-node1   1/1   Running   0   1d",
            "rke2/podlogs/kube-system-etcd-node1": text,
            "rke2/agent-logs/kubelet.log": "2026-10-22T00:00:00Z stats collection took too long\n",
            "systemlogs/syslog": "2026-10-22T00:00:00Z Out of memory: Killed process 99\n",
        },
        analysis_scan_bytes=2 * 1024 * 1024,
        analysis_file_bytes=3 * 1024 * 1024,
    )
    finish(a)
    assert a.state == "partial"
    for _ in range(20):
        if a.state == "complete":
            break
        a.reset_round()
        finish(a)
    assert a.state == "complete"
    rows = a.findings(limit=200, evidence_type="history")["items"]
    slow = next(r for r in rows if r["ruleId"] == "etcd.slow")
    assert slow["count"] == 2
    assert len(a.detail(slow["id"])["evidence"]["items"]) == 2
    assert not any(
        r["ruleId"] == "etcd.slow" and "kubelet" in r["object"]["name"] for r in rows
    )
    assert any(r["ruleId"] == "kernel.oom" for r in rows)
    assert a.status()["coverage"]["remainingBytes"] == 0
    assert (
        a.status()["coverage"]["scannedBytes"]
        == a.status()["coverage"]["candidateBytes"]
    )


def test_analysis_api_lifecycle_and_event_link(client, sample):
    record = upload(client, sample)
    base = "/api/v1/bundles/" + record["id"] + "/analysis"
    for _ in range(500):
        result = client.get(base).json()
        if result["state"] not in ("queued", "running"):
            break
        time.sleep(0.005)
    assert result["state"] == "complete", result
    page = client.get(base + "/findings?limit=1").json()
    assert page["nextCursor"]
    assert (
        client.get(base + "/findings?limit=1&cursor=" + page["nextCursor"]).status_code
        == 200
    )
    assert client.get(base + "/findings?severity=invalid").status_code == 400
    assert client.get(base + "/findings?limit=201").status_code == 422
    assert client.get(base + "/findings/" + page["items"][0]["id"]).status_code == 200
    assert client.post(base, json={"action": "invalid"}).status_code == 422
    assert client.post(base, json={"action": "restart"}).status_code == 202
    assert client.delete("/api/v1/bundles/" + record["id"]).status_code == 204
    assert client.get(base).status_code == 404
    assert client.get("/api/v1/session").json()["usedBytes"] == 0


def test_missing_data_cancellation_and_result_budget(tmp_path):
    a = make(tmp_path, {"systeminfo/freeh": "damaged"})
    finish(a)
    assert a.findings(severity="unknown")["total"] > 0
    a.reset_round()
    a.cancelled.set()
    with pytest.raises(Exception):
        a.step()  # cancellation is checked before opening any writer
    tiny = make(tmp_path / "tiny", {}, analysis_limit=4096)
    assert tiny.step() is False and tiny.state == "failed"


def test_threshold_config():
    assert thresholds('{"cpu":[80,90]}')["cpu"] == [80, 90]
    for raw in (
        "[]",
        '{"x":[1,2]}',
        '{"cpu":[95,85]}',
        '{"memoryAvailable":[5,15]}',
        '{"cpu":[true,90]}',
    ):
        with pytest.raises(ValueError):
            thresholds(raw)


@pytest.mark.parametrize(
    "health,leader,alarm,expected",
    [
        (
            "https://127.0.0.1:2379 is unhealthy: failed",
            0,
            "memberID:1 alarm:NOSPACE",
            {"etcd.health", "etcd.leader", "etcd.alarms"},
        ),
        ("https://127.0.0.1:2379 is healthy: committed", 1, "", set()),
    ],
)
def test_etcd_single_member_and_explicit_failure(
    tmp_path, health, leader, alarm, expected
):
    a = make(
        tmp_path,
        {
            "etcd/endpointhealth": health,
            "etcd/memberlist": "m1, started, node1, https://127.0.0.1:2380, https://127.0.0.1:2379, false",
            "etcd/alarmlist": alarm,
            "etcd/etcd-metrics-local.txt": f"etcd_server_has_leader {leader}\netcd_mvcc_db_total_size_in_bytes 96\netcd_server_quota_backend_bytes 100",
        },
    )
    finish(a)
    rules = {
        r["ruleId"] for r in a.findings(limit=200, evidence_type="snapshot")["items"]
    }
    assert expected <= rules
    assert (
        next(
            r for r in a.findings(limit=200)["items"] if r["ruleId"] == "etcd.etcdQuota"
        )["severity"]
        == "high"
    )
    if not expected:
        assert not {"etcd.health", "etcd.leader", "etcd.member"} & rules


def test_agent_active_is_not_failed_server_and_config_evidence(tmp_path):
    a = make(
        tmp_path,
        {
            "systeminfo/systemd-units": "rke2-server.service loaded inactive dead server\nrke2-agent.service loaded active running agent",
            "rke2/kubelet-config.yaml": "cgroupDriver: systemd",
            "rke2/containerd-config.toml": "SystemdCgroup = false",
        },
    )
    finish(a)
    rows = a.findings(limit=200)["items"]
    assert not any(r["ruleId"] == "service.distribution" for r in rows)
    assert (
        next(r for r in rows if r["ruleId"] == "init.cgroup")["severity"] == "warning"
    )
    assert a.role == "agent"


def test_threshold_exact_edges_and_readonly_counter_no_rate(tmp_path):
    a = make(tmp_path, {})
    a.writer = sqlite3.connect(a.path)
    a.initialize()
    obj = {"kind": "Node", "id": "n", "name": "n"}
    a.metric("host.cpu", obj, "CPU", 85)
    a.metric("host.memoryAvailable", obj, "Mem", 5, invert=True)
    a.writer.commit()
    a.writer.close()
    a.writer = None
    rows = a.findings(limit=200)["items"]
    assert all(r["severity"] == "warning" for r in rows)
    assert len(rows) == 2


def test_result_budget_failure_does_not_fail_bundle(tmp_path, sample):
    from fastapi.testclient import TestClient
    from backend.app import create_app

    with TestClient(
        create_app(Settings(data_dir=tmp_path, analysis_limit=4096))
    ) as client:
        r = upload(client, sample)
        assert r["state"] == "ready"
        base = "/api/v1/bundles/" + r["id"]
        for _ in range(200):
            status = client.get(base + "/analysis").json()
            if status["state"] == "failed":
                break
            time.sleep(0.005)
        assert status["state"] == "failed"
        assert client.get(base + "/overview").status_code == 200
        assert client.delete("/api/v1/cases/" + r["caseId"]).status_code == 204
        assert client.get("/api/v1/session").json()["usedBytes"] == 0


def test_analysis_reservation_failure_and_restart_cleanup(tmp_path, sample):
    from fastapi.testclient import TestClient
    from backend.app import create_app

    with TestClient(
        create_app(
            Settings(
                data_dir=tmp_path,
                analysis_limit=256 * 1024 * 1024,
                session_limit=150 * 1024 * 1024,
            )
        )
    ) as client:
        r = upload(client, sample)
        assert r["state"] == "ready"
        base = "/api/v1/bundles/" + r["id"]
        assert client.get(base + "/analysis").json()["state"] == "blocked"
        assert client.get(base + "/overview").status_code == 200
    assert not list((tmp_path / "session").glob("**/analysis.sqlite"))


def test_keyword_straddles_reverse_window_boundary(tmp_path):
    raw = b"a" * 200 + b"apply request took too long" + b"b" * 120
    a = make(
        tmp_path,
        {
            "rke2/kubectl/pods": "NAMESPACE   NAME   READY   STATUS   RESTARTS   AGE\nkube-system   etcd-node1   1/1   Running   0   1d",
            "rke2/podlogs/kube-system-etcd-node1": raw,
        },
        analysis_file_bytes=128,
        analysis_scan_bytes=128,
    )
    finish(a)
    for _ in range(10):
        if a.state == "complete":
            break
        a.reset_round()
        finish(a)
    assert a.state == "complete"
    hit = a.findings(evidence_type="history")["items"][0]
    assert hit["count"] == 1
    assert a.detail(hit["id"])["evidence"]["items"][0]["offset"] == 200


def test_cancellation_mid_structure_replays_without_lost_or_duplicate_findings(
    tmp_path,
):
    a = make(
        tmp_path,
        {
            "rke2/kubectl/pods.json": {
                "items": [
                    {
                        "metadata": {"name": f"app-{i}", "namespace": "business"},
                        "status": {"phase": "Failed"},
                    }
                    for i in range(500)
                ]
            }
        },
    )
    assert a.step()
    a.cancelled.set()
    with pytest.raises(Exception):
        a.step()
    a.state = "cancelled"
    a.reset_round()
    finish(a)
    assert a.findings(evidence_type="snapshot", category="cluster")["total"] == 500
    assert all(
        r["count"] == 1
        for r in a.findings(evidence_type="snapshot", category="cluster")["items"]
    )


def test_text_node_notready_and_describe_pressure(tmp_path):
    a = make(
        tmp_path,
        {
            "rke2/kubectl/nodes": "NAME   STATUS     ROLES\nnode1  NotReady   worker",
            "rke2/kubectl/nodesdescribe": "Name: node1\nConditions:\n  Type             Status  LastHeartbeatTime  Reason\n  DiskPressure     True    now                KubeletHasDiskPressure\n",
        },
    )
    finish(a)
    rules = {r["ruleId"] for r in a.findings(severity="high")["items"]}
    assert {"node.ready", "node.DiskPressure"} <= rules


def test_wide_events_empty_columns_and_uid_name_fallback(tmp_path):
    columns = [
        "NAMESPACE",
        "LAST SEEN",
        "TYPE",
        "REASON",
        "OBJECT",
        "SUBOBJECT",
        "SOURCE",
        "MESSAGE",
        "FIRST SEEN",
        "COUNT",
        "NAME",
    ]
    widths = [20, 12, 10, 20, 25, 20, 25, 80, 14, 10, 20]

    def line(values):
        return "".join(str(v).ljust(w) for v, w in zip(values, widths)).rstrip() + "\n"

    events = line(columns) + line(
        [
            "business",
            "1m",
            "Warning",
            "FailedScheduling",
            "pod/bad",
            "",
            "scheduler",
            "0/3 nodes available  insufficient cpu",
            "1m",
            "3",
            "event-name",
        ]
    )
    a = make(
        tmp_path,
        {
            "rke2/kubectl/events": events,
            "rke2/kubectl/pods": "NAMESPACE   NAME   READY   STATUS   RESTARTS   AGE\nbusiness   bad   0/1   Pending   0   1m",
        },
    )
    finish(a)
    item = next(
        r
        for r in a.findings(category="cluster", evidence_type="snapshot")["items"]
        if r["object"]["name"] == "bad"
    )
    assert item["severity"] == "warning" and item["eventsTotal"] == 1
    assert item["eventPreview"][0]["association"].startswith("名称")
    assert item["eventPreview"][0]["message"] == "0/3 nodes available  insufficient cpu"


def test_node_uid_does_not_merge_filesystems_and_endpoint_metrics(tmp_path):
    a = make(
        tmp_path,
        {
            "rke2/kubectl/nodes.json": {
                "items": [
                    {
                        "metadata": {"name": "node1", "uid": "node-uid"},
                        "status": {"conditions": [{"type": "Ready", "status": "True"}]},
                    }
                ]
            },
            "systeminfo/dfh": "Filesystem Size Used Avail Use% Mounted on\n/dev/a 100G 96G 4G 96% /\n/dev/b 100G 90G 10G 90% /data",
            "etcd/endpointhealth": "https://127.0.0.1:2379 is healthy: committed",
            "etcd/etcd-metrics-a.txt": "etcd_server_has_leader 1\netcd_mvcc_db_total_size_in_bytes 10\netcd_server_quota_backend_bytes 100",
            "etcd/etcd-metrics-b.txt": "etcd_server_has_leader 0\netcd_mvcc_db_total_size_in_bytes 99\netcd_server_quota_backend_bytes 100",
        },
    )
    finish(a)
    rows = a.findings(limit=200, evidence_type="snapshot", node="node1")["items"]
    disks = [r for r in rows if r["ruleId"] == "host.disk"]
    assert len(disks) == 2 and {r["severity"] for r in disks} == {"high", "warning"}
    assert any(r["ruleId"] == "etcd.leader" and r["severity"] == "high" for r in rows)
    assert any(
        r["ruleId"] == "etcd.etcdQuota" and r["severity"] == "high" for r in rows
    )
    metric = next(m for m in a.status()["observations"] if m["rule"] == "host.disk")
    assert metric["value"] == 96 and metric["measurements"] == 2


def test_utf8_evidence_offsets_and_cumulative_time_kept_raw(tmp_path):
    prefix = "中文".encode() * 100 + b" "
    a = make(
        tmp_path,
        {
            "systemlogs/syslog": prefix
            + b"2026-10-22 08:00:00 Out of memory: Killed process 10\n"
        },
    )
    finish(a)
    hit = a.findings(evidence_type="history")["items"][0]
    detail = a.detail(hit["id"])["evidence"]["items"][0]
    assert detail["offset"] == len(prefix) + len(b"2026-10-22 08:00:00 ")
    assert detail["rawTime"] == "2026-10-22 08:00:00" and not detail["parsedTime"]


def test_quota_over_100_percent_is_high_not_unknown(tmp_path):
    a = make(tmp_path, {})
    a.writer = sqlite3.connect(a.path)
    a.initialize()
    a.metric(
        "etcd.etcdQuota",
        {"kind": "Etcd", "id": "m", "name": "m"},
        "DB quota",
        110,
        category="etcd",
    )
    a.writer.commit()
    a.writer.close()
    a.writer = None
    assert a.findings()["items"][0]["severity"] == "high"
