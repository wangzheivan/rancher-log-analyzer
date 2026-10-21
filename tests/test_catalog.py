import json
import pytest
from backend.catalog import IndexedBundle, identity
from backend.archive import ImportFailure
from backend.reader import read_page


def write(root, path, value):
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(value if isinstance(value, str) else json.dumps(value))
    return p


def fixture(root):
    write(root, "summary.txt", "Hostname: node1\nDistro: rke2\n")
    pods = [
        {
            "metadata": {
                "name": "app-with-dashes",
                "namespace": "business-ns",
                "uid": "new",
            },
            "spec": {
                "nodeName": "node1",
                "containers": [
                    {
                        "name": "web",
                        "image": "test",
                        "resources": {"requests": {"cpu": "1"}},
                    }
                ],
                "initContainers": [{"name": "init"}],
            },
            "status": {
                "phase": "Running",
                "containerStatuses": [
                    {"name": "web", "ready": True, "restartCount": 9}
                ],
            },
        },
        {
            "metadata": {"name": "job", "namespace": "business-ns", "uid": "job"},
            "spec": {"containers": [{"name": "job"}]},
            "status": {"phase": "Succeeded"},
        },
    ]
    write(root, "rke2/kubectl/pods.json", {"items": pods})
    write(
        root,
        "rke2/kubectl/nodes.json",
        {
            "items": [
                {
                    "metadata": {"name": "node1"},
                    "status": {
                        "capacity": {"cpu": "4"},
                        "conditions": [{"type": "Ready", "status": "True"}],
                    },
                }
            ]
        },
    )
    for uid in ("new", "old"):
        for instance in (0, 1):
            write(
                root,
                f"rke2/podlogs/business-ns_app-with-dashes_{uid}/web/{instance}.log",
                "hello 中文\n",
            )
    write(root, "rke2/podlogs/business-ns_app-with-dashes_new/init/0.log", "")
    write(
        root,
        "rke2/podlogs/business-ns_app-with-dashes_new/web/1.log.20261020",
        "rotated\n",
    )
    write(
        root,
        "rke2/podlogs/business-ns-app-with-dashes-previous",
        "Error from server (BadRequest): previous terminated container\n",
    )
    write(root, "rke2/podlogs/ambiguous-orphan", "unassociated")
    write(
        root,
        "rke2/kubectl/events.json",
        {
            "items": [
                {
                    "metadata": {"uid": "event", "namespace": "business-ns"},
                    "involvedObject": {
                        "name": "app-with-dashes",
                        "kind": "Pod",
                        "uid": "new",
                    },
                    "type": "Warning",
                    "reason": "BackOff",
                    "message": "retry",
                    "lastTimestamp": "2026-01-01T00:00:00Z",
                },
                {
                    "metadata": {"uid": "old-event", "namespace": "business-ns"},
                    "involvedObject": {
                        "name": "app-with-dashes",
                        "kind": "Pod",
                        "uid": "old",
                    },
                    "type": "Warning",
                    "reason": "Old",
                    "message": "old",
                },
            ]
        },
    )
    write(
        root,
        "rke2/kubectl/poddescribe/business-ns",
        "Name:         app-with-dashes\nNamespace:    business-ns\nContainers:\n  web:\n    Image: test\nEvents:\n  Type    Reason  Age  From     Message\n  Normal  Pulled  2m   kubelet  done\n\nName: job\nNamespace: business-ns\nEvents: <none>\n",
    )
    write(root, "journald/kubelet", "journal")
    return IndexedBundle(root, root.parent / "meta.sqlite")


def test_log_identity_details_events(tmp_path):
    b = fixture(tmp_path / "files")
    pods = b.catalog("pods")["items"]
    p = next(p for p in pods if p["name"] == "app-with-dashes")
    assert p["logCount"] == 5
    assert p["restartCount"] == 9 and not p["attention"]
    assert next(p for p in pods if p["name"] == "job")["attention"] is False
    logs = b.catalog("logs")["items"]
    assert len(logs) == 9
    assert len(b.catalog("logPods")["items"]) == 3
    assert any(l["rotation"] for l in logs)
    assert any(l["status"] == "failed" and l["container"] == "合并日志" for l in logs)
    assert any(l["status"] == "empty" for l in logs)
    old = [l for l in logs if l["uid"] == "old"]
    assert all(not l["snapshotPodId"] for l in old)
    detail = b.entity("pods", p["id"])
    assert detail["object"]["spec"]["initContainers"][0]["name"] == "init"
    assert (
        detail["describe"]["raw"].startswith("Name:")
        and "Name: job" not in detail["describe"]["raw"]
    )
    events = b.catalog(
        "events",
        object_name=p["name"],
        object_kind="Pod",
        object_uid="new",
        namespace="business-ns",
    )["items"]
    assert {e["reason"] for e in events} == {"BackOff", "Pulled"}
    assert {e["association"] for e in events} == {"UID", "名称关联，未确认 UID"}
    assert b.catalog("logs", scope="business")["total"] == 7
    assert b.catalog("logs", scope="unknown")["total"] == 1
    assert b.overview["podLogCoverage"] == 1


def test_pagination_and_source_fallback(tmp_path):
    root = tmp_path / "files"
    write(root, "summary.txt", "Hostname: test")
    write(
        root,
        "rke2/kubectl/pods",
        "NAMESPACE  NAME  READY  STATUS  RESTARTS  AGE\ndefault    app   1/1    Running  0         1d\n",
    )
    write(root, "rke2/kubectl/pods.json", "{broken")
    write(root, "rke2/kubectl/events", "No resources found\n")
    b = IndexedBundle(root, tmp_path / "meta.sqlite")
    assert b.catalog("pods")["total"] == 1
    page = b.catalog("files", limit=1)
    assert len(page["items"]) == 1 and page["nextCursor"]
    second = b.catalog("files", limit=1, cursor=page["nextCursor"])
    assert second["previousCursor"]
    assert (
        b.catalog("files", limit=1, cursor=second["previousCursor"])["items"]
        == page["items"]
    )
    with pytest.raises(ValueError):
        b.catalog("files", cursor=page["nextCursor"], q="changed")
    assert b.overview["warningCount"] and any(
        g["state"] == "empty"
        for g in b.completeness()["groups"]
        if g["id"] == "details"
    )
    with pytest.raises(FileNotFoundError):
        b.file(identity("../../etc/passwd"))


def test_bounded_tail_forward_search(tmp_path):
    path = write(
        tmp_path, "large.log", "".join(f"{i:05d} 中文 line\n" for i in range(1000))
    )
    last = read_page(path, "large.log", direction="backward", anchor="end")
    assert len(last["lines"]) == 250 and last["lines"][0].startswith("00750")
    prev = read_page(path, "large.log", direction="backward", end=last["beforeCursor"])
    assert prev["lines"][-1].startswith("00749")
    forward = read_page(path, "large.log", offset=last["beforeCursor"])
    assert forward["lines"] == last["lines"]
    found = read_page(
        path, "large.log", query="中文 LINE", direction="backward", anchor="end"
    )
    assert len(found["lines"]) == 250
    path.write_bytes(b"x" * (3 * 1024 * 1024))
    r = read_page(path, "large.log", query="absent", direction="backward", anchor="end")
    assert r["scannedBytes"] <= 2 * 1024 * 1024 and r["beforeCursor"]


def test_classification_budget_and_large_counts(tmp_path):
    root = tmp_path / "files"
    write(root, "summary.txt", "Hostname: test")
    write(
        root,
        "rke2/kubectl/pods.json",
        {
            "items": [
                {
                    "metadata": {
                        "name": f"app-{i}",
                        "namespace": f"ns-{i%100}",
                        "uid": str(i),
                    },
                    "spec": {
                        "nodeName": f"node-{i%300}",
                        "containers": [{"name": "app"}],
                    },
                    "status": {"phase": "Running"},
                }
                for i in range(10000)
            ]
        },
    )
    write(
        root,
        "rke2/kubectl/nodes.json",
        {"items": [{"metadata": {"name": f"node-{i}"}} for i in range(300)]},
    )
    write(root, "rke2/podlogs/ns-0_app-0_0/app/0.log", "hello")
    b = IndexedBundle(
        root, tmp_path / "meta.sqlite", rules='[{"namespace":"ns-0","scope":"system"}]'
    )
    assert (
        b.overview["counts"]["pods"] == 10000 and b.overview["counts"]["nodes"] == 300
    )
    assert len(json.dumps(b.overview).encode()) < 256 * 1024
    assert (
        len(b.catalog("pods")["items"]) == 50
        and b.catalog("pods", namespace="ns-0")["total"] == 100
    )
    assert b.catalog("logs")["items"][0]["scope"] == "system"
    with pytest.raises(ImportFailure):
        IndexedBundle(root, tmp_path / "tiny.sqlite", limit=65536)


def test_ambiguous_flat_rotations_and_encoding(tmp_path):
    root = tmp_path / "files"
    write(root, "summary.txt", "Hostname: node1")
    items = [
        {"metadata": {"name": name, "namespace": ns}, "spec": {}, "status": {}}
        for ns, name in [("a", "b-c"), ("a-b", "c"), ("apps", "unique")]
    ]
    write(root, "rke2/kubectl/pods.json", {"items": items})
    write(root, "rke2/podlogs/a-b-c", "ambiguous")
    write(root, "rke2/podlogs/apps-unique.1", "rotated")
    path = write(root, "rke2/podlogs/apps-unique", "")
    path.write_bytes(b"hello\xff")
    write(root, "rke2/podlogs/gone_deleted_old/web/0.log", "orphan")
    write(root, "rke/containerlogs/kube-apiserver", "control plane")
    b = IndexedBundle(root, tmp_path / "meta.sqlite")
    logs = b.catalog("logs")["items"]
    assert b.catalog("logs", pod="unassociated")["total"] == 1
    assert next(l for l in logs if l["path"].endswith(".1"))["rotation"] == ".1"
    assert next(l for l in logs if l["path"].endswith("apps-unique"))["note"]
    assert any(p["name"] == "deleted" for p in b.catalog("logPods")["items"])
    assert any(l["component"] == "kube-apiserver" for l in logs)


def test_index_budget_cleanup_and_lightweight_cases(tmp_path, sample):
    from fastapi.testclient import TestClient
    from backend.app import create_app
    from backend.config import Settings
    from conftest import upload

    with TestClient(
        create_app(Settings(data_dir=tmp_path, index_limit=4096))
    ) as client:
        record = upload(client, sample)
        assert record["state"] == "failed"
        assert client.get("/api/v1/session").json()["usedBytes"] == 0
        assert not list((tmp_path / "session").glob("*/metadata.sqlite"))
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        record = upload(client, sample)
        assert record["state"] == "ready"
        result = client.get("/api/v1/cases").json()
        assert "pods" not in result[0]["bundles"][0]
        assert (
            client.get("/api/v1/bundles/" + record["id"] + "/overview").json()[
                "counts"
            ]["pods"]
            == 3
        )
        assert (
            client.get(
                "/api/v1/bundles/" + record["id"] + "/catalog/pods?limit=201"
            ).status_code
            == 422
        )
        client.delete("/api/v1/cases/" + record["caseId"])
        assert client.get("/api/v1/session").json()["usedBytes"] == 0


def test_reverse_long_line_search_and_valid_empty(tmp_path):
    path = tmp_path / "long"
    path.write_bytes(b"x" * 65530 + b"CROSSBOUNDARY" + b"y" * 65536 + b"\nlast\n")
    page = read_page(
        path, "long", query="crossboundary", direction="backward", anchor="end"
    )
    assert (
        len(page["lines"]) == 1
        and "CROSSBOUNDARY" in page["lines"][0]
        and page["segments"][0]["continued"]
    )
    root = tmp_path / "files"
    write(root, "summary.txt", "Hostname: node1")
    write(root, "rke2/kubectl/events.json", {"items": []})
    b = IndexedBundle(root, tmp_path / "meta.sqlite")
    assert b.catalog("events")["total"] == 0
    assert (
        next(g for g in b.completeness()["groups"] if g["id"] == "details")["state"]
        == "empty"
    )


def test_reverse_search_across_scan_windows(tmp_path):
    path = tmp_path / "boundary"
    path.write_bytes(b"x" * 100 + b"CROSSBOUNDARY" + b"y" * (2 * 1024 * 1024 - 6))
    first = read_page(
        path, "boundary", query="crossboundary", direction="backward", anchor="end"
    )
    assert not first["lines"] and first["beforeCursor"]
    second = read_page(
        path,
        "boundary",
        query="crossboundary",
        direction="backward",
        end=first["beforeCursor"],
    )
    assert any("CROSSBOUNDARY" in line for line in second["lines"])
    assert (
        first["scannedBytes"] <= 2 * 1024 * 1024
        and second["scannedBytes"] <= 2 * 1024 * 1024
    )


def test_file_groups_directories_and_resource_tables(tmp_path):
    root = tmp_path / "files"
    write(root, "summary.txt", "Hostname: node1")
    write(root, "etcd/etcd-metrics-127.0.0.1:2381.txt", "metric 1")
    write(
        root,
        "rke2/kubectl/nodes",
        "NAME   STATUS   ROLES    INTERNAL-IP   VERSION\nnode1  Ready    worker   192.0.2.9     v1.34\n",
    )
    write(
        root,
        "rke2/kubectl/nodes.json",
        {
            "items": [
                {
                    "metadata": {"name": "node1"},
                    "status": {
                        "addresses": [{"type": "InternalIP", "address": "192.0.2.9"}]
                    },
                }
            ]
        },
    )
    write(
        root,
        "rke2/kubectl/pods.json",
        {
            "items": [
                {
                    "metadata": {"name": "app", "namespace": "apps"},
                    "spec": {"nodeName": "node1"},
                }
            ]
        },
    )
    write(
        root,
        "rke2/kubectl/services",
        "NAMESPACE  NAME  CLUSTER-IP\nother      svc   192.0.2.10\n",
    )
    write(
        root,
        "rke2/kubectl/poddescribe/empty-namespace",
        "No resources found in empty-namespace namespace.\n",
    )
    write(
        root, "rke2/kubectl/poddescribe/described", "Name: app2\nNamespace: described\n"
    )
    b = IndexedBundle(root, tmp_path / "meta.sqlite")
    assert b.catalog("nodes", q="192.0.2.9")["items"][0]["podCount"] == 1
    assert {r["name"] for r in b.catalog("namespaces")["items"]} == {
        "apps",
        "other",
        "described",
    }
    groups = b.catalog("fileGroups")["items"]
    assert sum(g["count"] for g in groups) == b.overview["counts"]["files"]
    assert sum(g["bytes"] for g in groups) == b.overview["bytes"]
    assert b.catalog("files", group="etcd")["total"] == 1
    dirs = b.catalog("fileDirectories", directory="rke2", group="resources")["items"]
    assert dirs[0]["name"] == "kubectl"
    assert b.catalog("files", directory="rke2/kubectl", group="resources")["total"] == 4
    assert b.catalog("files", directory="rke2/kubectl/pod")["total"] == 0
    with pytest.raises(ValueError):
        b.catalog("fileDirectories", directory="../escape")
    table = b.catalog("resources", resource="nodes")
    assert table["source"].endswith("/nodes") and table["columns"] == [
        "NAME",
        "STATUS",
        "ROLES",
        "INTERNAL-IP",
        "VERSION",
    ]
    assert table["items"][0]["INTERNAL-IP"] == "192.0.2.9"
    assert b.catalog("resources", resource="services", q="192.0.2.10")["total"] == 1


def test_namespace_search_beyond_first_page(tmp_path):
    root = tmp_path / "files"
    write(root, "summary.txt", "Hostname: test")
    write(
        root,
        "rke2/kubectl/namespaces.json",
        {"items": [{"metadata": {"name": f"ns-{i:03d}"}} for i in range(101)]},
    )
    b = IndexedBundle(root, tmp_path / "meta.sqlite")
    first = b.catalog("namespaces")
    assert first["total"] == 101 and len(first["items"]) == 50
    assert first["items"][0]["name"] == "ns-000"
    second = b.catalog("namespaces", cursor=first["nextCursor"])
    third = b.catalog("namespaces", cursor=second["nextCursor"])
    assert third["items"][0]["name"] == "ns-100"
    assert b.catalog("namespaces", q="ns-100")["total"] == 1


def test_linux_colon_filename_and_drive_rejection(client):
    from conftest import make_archive, upload

    good = upload(
        client,
        make_archive(
            {
                "summary.txt": "Hostname: test",
                "etcd/etcd-metrics-127.0.0.1:2381.txt": "ok",
            }
        ),
    )
    assert good["state"] == "ready"
    for name in ["C:relative", "outer/C:/escape", "C:/absolute"]:
        bad = upload(
            client, make_archive({"summary.txt": "Hostname: test", name: "bad"})
        )
        assert bad["state"] == "failed"


def test_collector_metadata_classification():
    from backend.file_catalog import file_group

    assert file_group("collector-output.log") == "metadata"
    assert file_group("rke2/agent-logs/kubelet.log") == "components"
