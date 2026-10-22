"""Disk-backed bundle metadata. Normal browsing never materializes a whole resource list."""

from contextlib import contextmanager
import base64
import codecs
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import ijson
from threading import BoundedSemaphore

from .archive import Cancelled, ImportFailure
from .file_catalog import file_group, GROUPS, directory_prefix, grouped_catalog
from .classification import classify, load_rules
from .component_sources import identify, GROUPS as COMPONENT_GROUPS
from .certificates import build_certificates
from .parsers.bundle import Bundle
from .parsers.details import describe_blocks, parse_describe
from .parsers.streaming import encoded, json_items, text_rows

READERS = BoundedSemaphore(4)
STATES = {
    "ok": "已采集",
    "empty": "有效无数据",
    "partial": "部分可用",
    "failed": "采集失败",
    "missing": "未发现",
    "na": "不适用",
    "unknown": "无法判断",
}
ERROR_PREFIX = re.compile(
    r"^(?:Error from server\b|error: (?:previous terminated container|container|pods?|unable|failed|the server)|(?:bash:|/bin/sh:).*command not found|Unable to connect to the server)",
    re.I,
)


def identity(*parts):
    return hashlib.sha256("\0".join(str(p) for p in parts).encode()).hexdigest()[:24]


def pod_row(row, source):
    count = re.match(r"\d+", row.get("RESTARTS", "0"))
    ready = row.get("READY", "")
    return {
        **row,
        "id": identity("pods", row.get("NAMESPACE", "default"), row.get("NAME", "")),
        "namespace": row.get("NAMESPACE", "default"),
        "name": row.get("NAME", ""),
        "uid": "",
        "node": row.get("NODE", ""),
        "status": row.get("STATUS", "Unknown"),
        "ready": ready,
        "restartCount": int(count.group()) if count else 0,
        "attention": row.get("STATUS") not in ("Running", "Completed", "Succeeded")
        or (
            row.get("STATUS") == "Running"
            and not bool(re.fullmatch(r"([1-9]\d*)/\1", ready))
        ),
        "source": source,
    }


def pod_json(item, source):
    meta, spec, status = item["metadata"], item.get("spec", {}), item.get("status", {})
    containers = status.get("containerStatuses", [])
    phase = status.get("phase", "Unknown")
    if phase == "Succeeded":
        phase = "Completed"
    phase = next(
        (
            c.get("state", {}).get("waiting", {}).get("reason")
            for c in status.get("initContainerStatuses", []) + containers
            if c.get("state", {}).get("waiting", {}).get("reason")
        ),
        phase,
    )
    row = pod_row(
        {
            "NAME": meta["name"],
            "NAMESPACE": meta.get("namespace", "default"),
            "NODE": spec.get("nodeName", ""),
            "STATUS": phase,
            "READY": f"{sum(bool(c.get('ready')) for c in containers)}/{len(spec.get('containers', []))}",
            "RESTARTS": str(
                sum(
                    c.get("restartCount", 0)
                    for c in containers + status.get("initContainerStatuses", [])
                )
            ),
            "AGE": "—",
            "IP": status.get("podIP", "未知"),
        },
        source,
    )
    row["uid"] = meta.get("uid", "")
    return row


def node_json(item, source):
    meta, status = item["metadata"], item.get("status", {})
    return {
        "id": identity("nodes", meta["name"]),
        "name": meta["name"],
        "namespace": "",
        "uid": meta.get("uid", ""),
        "roles": ", ".join(
            k.split("/")[-1]
            for k in meta.get("labels", {})
            if k.startswith("node-role.kubernetes.io/")
        )
        or "worker",
        "ip": next(
            (
                a["address"]
                for a in status.get("addresses", [])
                if a["type"] == "InternalIP"
            ),
            "未知",
        ),
        "ready": next(
            (c["status"] for c in status.get("conditions", []) if c["type"] == "Ready"),
            "Unknown",
        ),
        "conditions": status.get("conditions", []),
        "capacity": status.get("capacity", {}),
        "allocatable": status.get("allocatable", {}),
        "source": source,
        **status.get("nodeInfo", {}),
    }


class IndexedBundle:
    def __init__(
        self, root, db_path, limit=128 * 1024 * 1024, rules="[]", cancelled=None
    ):
        self.root, self.db_path = Path(root).resolve(), Path(db_path).resolve()
        self.cancelled = cancelled
        self.rules = load_rules(rules)
        self.warnings = []
        self.distro = next(
            (
                d
                for d in ("rke2", "k3s", "rke", "kubeadm", "pod")
                if (self.root / d).is_dir()
            ),
            "",
        )
        self.header = self._header()
        writer = sqlite3.connect(self.db_path)
        writer.row_factory = sqlite3.Row
        writer.executescript(
            """PRAGMA journal_mode=MEMORY; PRAGMA cache_size=-8192; PRAGMA temp_store=MEMORY;
            CREATE TABLE items(seq INTEGER PRIMARY KEY, kind TEXT NOT NULL, key TEXT NOT NULL,
              ns TEXT NOT NULL DEFAULT '', name TEXT NOT NULL DEFAULT '', uid TEXT NOT NULL DEFAULT '',
              node TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT '', scope TEXT NOT NULL DEFAULT '',
              component TEXT NOT NULL DEFAULT '', search TEXT NOT NULL DEFAULT '', payload TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',
              UNIQUE(kind,key));
            CREATE INDEX item_names ON items(kind,ns,name);
            CREATE INDEX item_nodes ON items(kind,node,seq);
            CREATE INDEX item_scope ON items(kind,scope,component,seq);
            CREATE INDEX item_uid ON items(kind,uid);
            CREATE INDEX item_log_pod ON items(kind,json_extract(payload,'$.podId'));
            CREATE TABLE sources(name TEXT PRIMARY KEY, source TEXT, state TEXT, note TEXT, columns TEXT);
            CREATE TABLE table_sources(name TEXT PRIMARY KEY, source TEXT, state TEXT, note TEXT, columns TEXT);
            CREATE TABLE descriptions(kind TEXT, ns TEXT, name TEXT, source TEXT, start INTEGER, end INTEGER,
              PRIMARY KEY(kind,ns,name));
            CREATE TABLE relations(pod TEXT, file TEXT, PRIMARY KEY(pod,file));
        """
        )
        writer.execute(f"PRAGMA max_page_count={max(1,limit//4096)}")
        self.writer = writer
        try:
            self._files()
            self._resources()
            self._descriptions()
            self._logs()
            build_certificates(self)
            writer.commit()
            self._finish()
        except sqlite3.DatabaseError as exc:
            raise ImportFailure(
                "元数据索引超过预算或无法写入，请检查索引配置与空间"
            ) from exc
        finally:
            writer.close()
            self.writer = None
        self.index_bytes = self.db_path.stat().st_size
        if self.index_bytes > limit:
            raise ImportFailure("元数据索引超过预算，请增加 MAX_INDEX_BYTES")

    def check(self):
        if self.cancelled and self.cancelled.is_set():
            raise Cancelled("导入已取消")

    def read(self, path, limit=65536):
        target = self.root / path
        if (
            not target.resolve().is_relative_to(self.root)
            or target.is_symlink()
            or not target.is_file()
        ):
            return ""
        with target.open("rb") as stream:
            return stream.read(limit).decode("utf-8", errors="replace")

    def _header(self):
        summary = self.read("summary.txt")

        def field(key):
            match = re.search(r"^" + key + r":[ \t]*(.*)$", summary, re.M)
            return match.group(1).strip() if match else "未知"

        os = re.search(r'PRETTY_NAME="(.*?)"', summary)
        version = re.search(r"(?:rke2|k3s) version (\S+)", self.read("versions"))
        return {
            "name": self.root.name,
            "hostname": field("Hostname"),
            "generated": field("Generated"),
            "kernel": field("Kernel"),
            "distro": self.distro or field("Distro"),
            "os": os.group(1) if os else "未知",
            "version": version.group(1) if version else "未知",
        }

    def put(self, kind, key, data, detail=""):
        self.check()
        self.writer.execute(
            """INSERT OR REPLACE INTO items(kind,key,ns,name,uid,node,status,scope,component,search,payload,detail)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                kind,
                key,
                data.get("namespace", ""),
                data.get("name", data.get("path", "")),
                data.get("uid", ""),
                data.get("node", ""),
                data.get("status", ""),
                data.get("scope", ""),
                data.get("component", ""),
                " ".join(
                    str(data.get(k, ""))
                    for k in (
                        (
                            tuple(data.keys())
                            if kind.startswith("resource:")
                            else (
                                "name",
                                "ip",
                                "IP",
                                "namespace",
                                "path",
                                "node",
                                "reason",
                                "message",
                                "objectName",
                                "objectKind",
                            )
                        )
                    )
                ).lower(),
                encoded(data),
                encoded(detail) if detail else "",
            ),
        )

    def source(self, name, path, state, note="", columns=()):
        self.writer.execute(
            "INSERT OR REPLACE INTO sources VALUES(?,?,?,?,?)",
            (name, path, state, note, encoded(columns)),
        )

    def _files(self):
        for path in self.root.rglob("*"):
            self.check()
            if (
                not path.is_file()
                or path.is_symlink()
                or not path.resolve().is_relative_to(self.root)
            ):
                continue
            key = path.relative_to(self.root).as_posix()
            size = path.stat().st_size
            self.put(
                "files",
                identity(key),
                {
                    "id": identity(key),
                    "path": key,
                    "size": size,
                    "name": key,
                    "group": file_group(key),
                    "groupLabel": GROUPS[file_group(key)],
                    "category": key.split("/")[0] if "/" in key else "采集元数据",
                },
            )
        self.writer.commit()

    def _resources(self):
        directory = self.root / self.distro / "kubectl"
        if not self.distro or not directory.is_dir():
            return
        for path in sorted(directory.iterdir()):
            if (
                not path.is_file()
                or path.suffix == ".json"
                or path.name.endswith("describe")
            ):
                continue
            name, source = path.name, path.relative_to(self.root).as_posix()
            self.writer.execute("SAVEPOINT resource")
            count, columns = 0, []
            try:
                for columns, row in text_rows(path):
                    self._resource_row(name, row, source, count)
                    count += 1
                self.source(name, source, "ok" if count else "empty", columns=columns)
                self.writer.execute(
                    "INSERT OR REPLACE INTO table_sources SELECT * FROM sources WHERE name=?",
                    (name,),
                )
                self.writer.execute("RELEASE resource")
            except (ValueError, UnicodeError) as exc:
                self.writer.execute("ROLLBACK TO resource")
                self.writer.execute("RELEASE resource")
                state, note = self.file_status(source, path.stat().st_size)
                self.source(
                    name,
                    source,
                    "failed" if state == "failed" else "unknown",
                    note or str(exc),
                )
                self.warnings.append(f"{source} 无法完整解析，请查看原文。")
            self.writer.commit()
        for path in sorted(directory.glob("*.json")):
            name, source = path.stem, path.relative_to(self.root).as_posix()
            table = self.writer.execute(
                "SELECT * FROM table_sources WHERE name=?", (name,)
            ).fetchone()
            if table and name not in ("pods", "nodes", "events"):
                continue
            self.writer.execute("SAVEPOINT structured")
            try:
                kind = (
                    name if name in ("pods", "nodes", "events") else "resource:" + name
                )
                self.writer.execute("DELETE FROM items WHERE kind=?", (kind,))
                if not table:
                    self.writer.execute(
                        "DELETE FROM items WHERE kind=?", ("resource:" + name,)
                    )
                count = 0
                for item in json_items(path):
                    self.check()
                    if name == "pods":
                        row = pod_json(item, source)
                        self.put("pods", row["id"], row, item)
                    elif name == "nodes":
                        row = node_json(item, source)
                        self.put("nodes", row["id"], row, item)
                    elif name == "events":
                        self._event_json(item, source)
                    else:
                        meta = item.get("metadata", {})
                        row = {
                            "NAMESPACE": meta.get("namespace", ""),
                            "NAME": meta.get("name", ""),
                            "KIND": item.get("kind", name),
                        }
                        self.put(
                            "resource:" + name,
                            str(count),
                            {**row, "namespace": row["NAMESPACE"], "name": row["NAME"]},
                        )
                    count += 1
                self.source(
                    name,
                    source,
                    "ok" if count else "empty",
                    columns=(
                        ["NAMESPACE", "NAME", "KIND"]
                        if name not in ("pods", "nodes", "events")
                        else []
                    ),
                )
                self.writer.execute("RELEASE structured")
            except (
                ValueError,
                KeyError,
                TypeError,
                AttributeError,
                OverflowError,
                ijson.JSONError,
            ) as exc:
                self.writer.execute("ROLLBACK TO structured")
                self.writer.execute("RELEASE structured")
                self.warnings.append(f"{source} 无法完整解析，已保留可用文本来源。")
                existing = self.writer.execute(
                    "SELECT * FROM sources WHERE name=?", (name,)
                ).fetchone()
                if existing:
                    self.source(
                        name,
                        existing["source"],
                        "partial",
                        "JSON 无法完整解析，使用文本回退",
                        json.loads(existing["columns"]),
                    )
                else:
                    self.source(name, source, "unknown", "JSON 无法完整解析")
            self.writer.commit()

    def _resource_row(self, name, row, source, number):
        self.put(
            "resource:" + name,
            str(number),
            {
                **row,
                "namespace": row.get("NAMESPACE", ""),
                "name": row.get("NAME", ""),
                "source": source,
            },
        )
        if name == "pods":
            data = pod_row(row, source)
            self.put("pods", data["id"], data)
        elif name == "nodes":
            data = {
                "id": identity("nodes", row.get("NAME", "")),
                "name": row.get("NAME", ""),
                "uid": "",
                "roles": row.get("ROLES", "未知"),
                "ip": row.get("INTERNAL-IP", "未知"),
                "ready": "True" if row.get("STATUS") == "Ready" else "Unknown",
                "status": row.get("STATUS", "Unknown"),
                "kubeletVersion": row.get("VERSION", "未知"),
                "osImage": row.get("OS-IMAGE", "未知"),
                "kernelVersion": row.get("KERNEL-VERSION", "未知"),
                "containerRuntimeVersion": row.get("CONTAINER-RUNTIME", "未知"),
                "capacity": {},
                "allocatable": {},
                "conditions": [],
                "source": source,
            }
            self.put("nodes", data["id"], data)
        elif name == "events":
            obj = row.get("OBJECT", row.get("INVOLVEDOBJECT", ""))
            kind, _, obj_name = obj.partition("/")
            self._event(
                {
                    "namespace": row.get("NAMESPACE", ""),
                    "objectKind": kind,
                    "objectName": obj_name,
                    "objectUid": "",
                    "type": row.get("TYPE", ""),
                    "reason": row.get("REASON", ""),
                    "message": row.get("MESSAGE", ""),
                    "time": row.get("LAST SEEN", row.get("LASTSEEN", "")),
                    "count": row.get("COUNT", ""),
                    "source": source,
                }
            )

    def _event_json(self, item, source):
        obj = item.get("regarding", item.get("involvedObject", {}))
        self._event(
            {
                "namespace": item.get("metadata", {}).get(
                    "namespace", obj.get("namespace", "")
                ),
                "objectKind": obj.get("kind", ""),
                "objectName": obj.get("name", ""),
                "objectUid": obj.get("uid", ""),
                "type": item.get("type", ""),
                "reason": item.get("reason", ""),
                "message": item.get("note", item.get("message", "")),
                "time": item.get("series", {}).get("lastObservedTime")
                or item.get("lastTimestamp")
                or item.get("eventTime")
                or "",
                "count": item.get("series", {}).get("count", item.get("count", "")),
                "source": source,
                "uid": item.get("metadata", {}).get("uid", ""),
            }
        )

    def _event(self, data):
        key = data.get("uid") or identity(
            "event",
            data["namespace"],
            data["objectKind"].lower(),
            data["objectName"],
            data["type"],
            data["reason"],
            data["message"],
        )
        data["id"] = key
        data["association"] = "UID" if data.get("objectUid") else "名称关联，未确认 UID"
        data["status"] = data["type"]
        self.put("events", key, data)

    def _descriptions(self):
        candidates = []
        for row in self.writer.execute("SELECT payload FROM items WHERE kind='files'"):
            path = json.loads(row["payload"])["path"]
            if "/poddescribe/" in path:
                candidates.append(("pods", path))
            elif path.endswith("/nodesdescribe"):
                candidates.append(("nodes", path))
        for kind, source in candidates:
            try:
                for name, namespace, start, end in describe_blocks(self.root / source):
                    self.check()
                    if kind == "pods" and not namespace:
                        namespace = source.rsplit("/", 1)[-1]
                    self.writer.execute(
                        "INSERT OR REPLACE INTO descriptions VALUES(?,?,?,?,?,?)",
                        (kind, namespace, name, source, start, end),
                    )
                    # Describe events remain useful when the global events list is absent or empty.
                    with (self.root / source).open("rb") as stream:
                        stream.seek(start)
                        text = stream.read(min(end - start, 1024 * 1024)).decode(
                            errors="replace"
                        )
                    parsed = parse_describe(text)
                    events = parsed["sections"].get("Events", "")
                    for line in events.splitlines():
                        values = re.split(r"\s{2,}", line.strip(), maxsplit=4)
                        if len(values) == 5 and values[0] in ("Warning", "Normal"):
                            self._event(
                                {
                                    "namespace": namespace,
                                    "objectKind": "Pod" if kind == "pods" else "Node",
                                    "objectName": name,
                                    "objectUid": "",
                                    "type": values[0],
                                    "reason": values[1],
                                    "time": values[2],
                                    "reporter": values[3],
                                    "message": values[4],
                                    "source": source,
                                    "sourceOffset": start,
                                }
                            )
            except (ValueError, OSError):
                self.warnings.append(f"{source} 的部分详情无法识别，请查看原文。")
        self.writer.commit()

    def _logs(self):
        namespaces = set()
        for row in self.writer.execute("SELECT DISTINCT ns FROM items WHERE ns<>''"):
            if row["ns"]:
                namespaces.add(row["ns"])
        for row in self.writer.execute(
            "SELECT name FROM items WHERE kind='resource:namespaces'"
        ):
            if row["name"]:
                namespaces.add(row["name"])
        for row in self.writer.execute(
            "SELECT DISTINCT ns FROM descriptions WHERE ns<>''"
        ):
            namespaces.add(row["ns"])
        files = self.writer.execute("SELECT payload FROM items WHERE kind='files'")
        # At most the archive entry limit of small metadata records, never file contents.
        for entry in files:
            self.check()
            file = json.loads(entry["payload"])
            path = file["path"]
            is_pod = "/podlogs/" in path
            is_component = (
                path.startswith(("journald/", "systemlogs/", "rancher/"))
                or any(
                    s in path
                    for s in ("/agent-logs/", "/server-logs/", "/containerlogs/")
                )
                or bool(
                    re.search(r"^(?:rke2|k3s)/(?:containerd|rke2|k3s)[^/]*\.log", path)
                )
            )
            if not is_pod and not is_component:
                continue
            namespace = pod = uid = container = ""
            instance = -1
            rotation = ""
            variant, basis = "source", "组件日志文件"
            if is_pod:
                tail = path.split("/podlogs/", 1)[1]
                nested = re.match(r"^([^/]+)_([^/]+)_([^/]+)/([^/]+)/([^/]+)$", tail)
                if nested:
                    namespace, pod, uid, container, filename = nested.groups()
                    number = re.match(r"^(\d+)\.log(.*)$", filename)
                    if number:
                        instance, rotation = int(number.group(1)), number.group(2)
                    variant, basis = (
                        "instance",
                        "CRI 目录中的命名空间、Pod UID、容器与实例",
                    )
                elif "/" not in tail:
                    previous = tail.endswith("-previous")
                    label = tail[:-9] if previous else tail
                    candidates = []
                    for ns in namespaces:
                        if label.startswith(ns + "-"):
                            name = label[len(ns) + 1 :]
                            existing = self.writer.execute(
                                "SELECT payload FROM items WHERE kind='pods' AND ns=? AND name=?",
                                (ns, name),
                            ).fetchone()
                            if existing:
                                candidates.append((ns, name, ""))
                            else:
                                rotated = re.match(
                                    r"^(.*?)(\.log(?:\..+)?|\.\d[\dTZ._-]*)$", name
                                )
                                if rotated:
                                    existing = self.writer.execute(
                                        "SELECT 1 FROM items WHERE kind='pods' AND ns=? AND name=?",
                                        (ns, rotated.group(1)),
                                    ).fetchone()
                                    if existing:
                                        candidates.append(
                                            (ns, rotated.group(1), rotated.group(2))
                                        )
                    if len(candidates) == 1:
                        namespace, pod, rotation = candidates[0]
                        variant, basis = (
                            "previous" if previous else "current"
                        ), "扁平文件名与资源清单唯一匹配；容器日志合并输出"
                    else:
                        basis = "扁平文件名无法唯一匹配资源清单"
                else:
                    basis = "目录布局暂无法识别"
            metadata = None
            if pod:
                found = self.writer.execute(
                    "SELECT payload FROM items WHERE kind='pods' AND ns=? AND name=?",
                    (namespace, pod),
                ).fetchone()
                if found:
                    metadata = json.loads(found["payload"])
            pod_id = identity("log-pod", namespace, pod, uid) if pod else ""
            snapshot_match = bool(
                metadata
                and (not uid or not metadata.get("uid") or metadata["uid"] == uid)
            )
            node = metadata.get("node", "") if snapshot_match else ""
            if not node and (is_component or variant == "instance"):
                node = (
                    self.header["hostname"] if self.header["hostname"] != "未知" else ""
                )
            scope, component, reason = classify(namespace, pod, path, self.rules)
            if is_component and scope == "unknown":
                scope, component, reason = (
                    "system",
                    component or Path(path).name,
                    "组件日志目录",
                )
            status, note = self.file_status(path, file["size"])
            log = {
                **file,
                "id": file["id"],
                "fileId": file["id"],
                "namespace": namespace,
                "name": pod or Path(path).name,
                "pod": pod,
                "uid": uid,
                "podId": pod_id,
                "container": container,
                "instance": instance,
                "rotation": rotation,
                "variant": variant,
                "basis": basis,
                "node": node,
                "scope": scope,
                "component": component,
                "classificationReason": reason,
                "status": status,
                "note": note,
                "snapshotPodId": metadata["id"] if snapshot_match else "",
            }
            service = identify(path, namespace, pod, container)
            log.update(service)
            if service["serviceComponent"]:
                log["component"] = service["serviceComponent"]
            self.put("logs", file["id"], log)
            if service["componentGroup"]:
                component = service["serviceComponent"]
                self.put(
                    "components",
                    component,
                    {
                        "id": component,
                        "name": component,
                        "scope": "system",
                        "componentGroup": service["componentGroup"],
                    },
                )
            if snapshot_match:
                self.writer.execute(
                    "INSERT OR IGNORE INTO relations VALUES(?,?)",
                    (metadata["id"], file["id"]),
                )
            if pod:
                self.put(
                    "logPods",
                    pod_id,
                    {
                        "id": pod_id,
                        "name": pod,
                        "namespace": namespace,
                        "uid": uid,
                        "node": node,
                        "scope": scope,
                        "snapshotPodId": metadata["id"] if snapshot_match else "",
                        "status": "有采集文件",
                    },
                )
                namespaces.add(namespace)
        for namespace in namespaces:
            self.put(
                "namespaces",
                namespace,
                {"id": namespace, "name": namespace, "namespace": namespace},
            )
        self.writer.commit()

    def file_status(self, path, size):
        if not size:
            return "empty", "文件为空"
        target = self.root / path
        with target.open("rb") as stream:
            prefix = stream.read(4096)
        if prefix.startswith(b"\x1f\x8b") or b"\x00" in prefix:
            return "unsupported", "二进制或压缩源文件，暂不支持直接展示"
        text = prefix.decode(errors="replace").lstrip()
        if text.strip() == "-- No entries --":
            return "empty", "有效无记录"
        if ERROR_PREFIX.match(text):
            return "failed", text.splitlines()[0][:400]
        try:
            codecs.getincrementaldecoder("utf-8")().decode(prefix, final=False)
        except UnicodeDecodeError:
            return (
                "ok",
                "检测到非 UTF-8 内容或截断字符；阅读时使用替换字符，请核对原文。",
            )
        return "ok", ""

    def _finish(self):
        # Cached overview contains bounded summaries only.
        conn = self.writer
        counts = {
            kind: conn.execute(
                "SELECT count(*) FROM items WHERE kind=?", (kind,)
            ).fetchone()[0]
            for kind in ("pods", "nodes", "files", "logs", "events", "namespaces")
        }
        size = conn.execute(
            "SELECT coalesce(sum(json_extract(payload,'$.size')),0) FROM items WHERE kind='files'"
        ).fetchone()[0]
        statuses = {
            r["status"]: r["n"]
            for r in conn.execute(
                "SELECT status,count(*) n FROM items WHERE kind='pods' GROUP BY status"
            )
        }
        samples = [
            json.loads(r["payload"])
            for r in conn.execute(
                "SELECT payload FROM items WHERE kind='nodes' ORDER BY seq LIMIT 10"
            )
        ]
        for sample in samples:
            sample["podCount"] = conn.execute(
                "SELECT count(*) FROM items WHERE kind='pods' AND node=?",
                (sample["name"],),
            ).fetchone()[0]
        ns = [
            {"name": r["ns"], "count": r["n"]}
            for r in conn.execute(
                "SELECT ns,count(*) n FROM items WHERE kind='pods' GROUP BY ns ORDER BY n DESC LIMIT 10"
            )
        ]
        resources = []
        for r in conn.execute("SELECT * FROM sources ORDER BY name"):
            count = conn.execute(
                "SELECT count(*) FROM items WHERE kind=?", ("resource:" + r["name"],)
            ).fetchone()[0]
            if r["name"] in counts:
                count = counts[r["name"]]
            resources.append(
                {
                    "name": r["name"],
                    "count": count,
                    "source": r["source"],
                    "state": r["state"],
                    "note": r["note"],
                }
            )
        self.overview = {
            **self.header,
            "counts": counts,
            "bytes": size,
            "podStatus": statuses,
            "nodePreview": samples,
            "namespaceDistribution": ns,
            "resources": resources[:200],
            "warnings": self.warnings[:50],
            "warningCount": len(self.warnings),
            "readyNodes": conn.execute(
                "SELECT count(*) FROM items WHERE kind='nodes' AND json_extract(payload,'$.ready')='True'"
            ).fetchone()[0],
            "podLogCoverage": conn.execute(
                "SELECT count(DISTINCT pod) FROM relations"
            ).fetchone()[0],
            "system": {
                k: self.read("systeminfo/" + k, 8192)
                for k in ("freeh", "dfh", "uptime", "lscpu")
            },
            "etcd": {
                k: self.read("etcd/" + k, 8192)
                for k in ("endpointhealth", "endpointstatus", "memberlist", "alarmlist")
            },
        }

    @contextmanager
    def connection(self):
        with READERS:
            conn = sqlite3.connect(
                self.db_path.as_uri() + "?mode=ro&immutable=1", uri=True
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA cache_size=-8192")
            try:
                yield conn
            finally:
                conn.close()

    def catalog(
        self,
        kind,
        limit=50,
        cursor="",
        q="",
        namespace="",
        node="",
        status="",
        scope="",
        component="",
        resource="",
        pod="",
        object_name="",
        object_kind="",
        object_uid="",
        has_logs=False,
        name="",
        reason="",
        group="",
        directory="",
        component_group="",
    ):
        if component_group and component_group not in COMPONENT_GROUPS:
            raise ValueError("未知组件分组")
        if group and group not in GROUPS:
            raise ValueError("未知文件用途")
        if kind in ("fileGroups", "fileDirectories"):
            return grouped_catalog(self, kind, limit, cursor, q, group, directory)
        allowed = {
            "pods",
            "nodes",
            "namespaces",
            "files",
            "logs",
            "logPods",
            "events",
            "resources",
            "components",
            "componentLogs",
        }
        if kind not in allowed:
            raise ValueError("未知目录类型")
        if kind == "resources" and not resource:
            signature = identity("resourceTypes", q)
            offset = 0
            if cursor:
                try:
                    decoded = json.loads(base64.urlsafe_b64decode(cursor))
                    offset = int(decoded["offset"])
                    if (
                        decoded["signature"] != signature
                        or offset < 0
                        or offset > 10000000
                    ):
                        raise ValueError()
                except Exception as exc:
                    raise ValueError("分页游标无效或筛选条件已改变") from exc
            with self.connection() as conn:
                total = conn.execute(
                    "SELECT count(*) FROM sources WHERE instr(lower(name),?)>0",
                    (q.lower(),),
                ).fetchone()[0]
                rows = []
                for source in conn.execute(
                    "SELECT * FROM sources WHERE instr(lower(name),?)>0 ORDER BY name LIMIT ? OFFSET ?",
                    (q.lower(), limit, offset),
                ):
                    actual = (
                        source["name"]
                        if source["name"] in ("pods", "nodes", "events")
                        else "resource:" + source["name"]
                    )
                    if conn.execute(
                        "SELECT 1 FROM table_sources WHERE name=?", (source["name"],)
                    ).fetchone():
                        actual = "resource:" + source["name"]
                    count = conn.execute(
                        "SELECT count(*) FROM items WHERE kind=?", (actual,)
                    ).fetchone()[0]
                    rows.append(
                        {
                            "id": source["name"],
                            "name": source["name"],
                            "count": count,
                            "source": source["source"],
                            "state": source["state"],
                            "note": source["note"],
                        }
                    )

            def token(at):
                return base64.urlsafe_b64encode(
                    encoded({"offset": at, "signature": signature}).encode()
                ).decode()

            return {
                "items": rows,
                "total": total,
                "nextCursor": (
                    token(offset + len(rows)) if offset + len(rows) < total else None
                ),
                "previousCursor": token(max(0, offset - limit)) if offset else None,
            }
        table_source = None
        if kind == "resources":
            with self.connection() as conn:
                table_source = conn.execute(
                    "SELECT * FROM table_sources WHERE name=?", (resource,)
                ).fetchone()
        actual = (
            (
                resource
                if resource in ("pods", "nodes", "events")
                else "resource:" + resource
            )
            if kind == "resources"
            else "logs" if kind == "componentLogs" else kind
        )
        if table_source:
            actual = "resource:" + resource
        params = [actual]
        where = ["i.kind=?"]
        for column, value in (
            ("ns", namespace),
            ("node", node),
            ("status", status),
            ("scope", scope),
            ("component", component),
        ):
            if value and not (kind == "components" and column == "node"):
                where.append(f"i.{column}=?")
                params.append(value)
        if kind == "componentLogs":
            where.append("coalesce(json_extract(i.payload,'$.componentGroup'),'')<>''")
        if component_group:
            where.append("json_extract(i.payload,'$.componentGroup')=?")
            params.append(component_group)
        if kind == "components" and node:
            # Components themselves have no node; derive candidates from matching sources.
            where.append(
                "EXISTS(SELECT 1 FROM items l WHERE l.kind='logs' AND l.node=? AND l.component=i.name AND coalesce(json_extract(l.payload,'$.componentGroup'),'')<>'')"
            )
            params.append(node)
        if kind == "files":
            if group:
                where.append("json_extract(i.payload,'$.group')=?")
                params.append(group)
            if directory:
                prefix = directory_prefix(directory)
                where.append("substr(json_extract(i.payload,'$.path'),1,?)=?")
                params.extend([len(prefix), prefix])
        if name:
            where.append("i.name=?")
            params.append(name)
        if reason:
            where.append("json_extract(i.payload,'$.reason')=?")
            params.append(reason)
        if q:
            where.append("instr(i.search,?)>0")
            params.append(q.lower())
        if pod == "unassociated":
            where.append(
                "coalesce(json_extract(i.payload,'$.podId'),'')='' AND instr(json_extract(i.payload,'$.path'),'/podlogs/')>0"
            )
        elif pod:
            where.append("json_extract(i.payload,'$.podId')=?")
            params.append(pod)
        if object_name:
            where.append("json_extract(i.payload,'$.objectName')=?")
            params.append(object_name)
        if object_kind:
            where.append("lower(json_extract(i.payload,'$.objectKind'))=?")
            params.append(object_kind.lower())
        if object_uid:
            where.append(
                "(json_extract(i.payload,'$.objectUid')=? OR (coalesce(json_extract(i.payload,'$.objectUid'),'')='' AND json_extract(i.payload,'$.objectName')=?))"
            )
            params.extend([object_uid, object_name])
        if has_logs and kind == "pods":
            where.append("EXISTS(SELECT 1 FROM relations r WHERE r.pod=i.key)")
        signature = identity(kind, *params, has_logs)
        offset = 0
        if cursor:
            try:
                decoded = json.loads(base64.urlsafe_b64decode(cursor))
                offset = int(decoded["offset"])
                if decoded["signature"] != signature or offset < 0 or offset > 10000000:
                    raise ValueError()
            except Exception as exc:
                raise ValueError("分页游标无效或筛选条件已改变") from exc
        condition = " AND ".join(where)
        with self.connection() as conn:
            total = conn.execute(
                f"SELECT count(*) FROM items i WHERE {condition}", params
            ).fetchone()[0]
            order = (
                "CASE WHEN json_extract(i.payload,'$.variant')='current' THEN 0 ELSE 1 END,json_extract(i.payload,'$.instance') DESC,json_extract(i.payload,'$.rotation'),i.seq"
                if kind in ("logs", "componentLogs")
                else (
                    "i.name COLLATE NOCASE,i.key"
                    if kind in ("namespaces", "files")
                    else "i.seq"
                )
            )
            records = conn.execute(
                f"SELECT i.payload,i.key FROM items i WHERE {condition} ORDER BY {order} LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
            rows = []
            for r in records:
                data = json.loads(r["payload"])
                if kind == "nodes":
                    data["podCount"] = conn.execute(
                        "SELECT count(*) FROM items WHERE kind='pods' AND node=?",
                        (data["name"],),
                    ).fetchone()[0]
                if kind in ("pods", "logPods"):
                    if kind == "pods":
                        logs = conn.execute(
                            "SELECT i.payload FROM items i JOIN relations r ON r.file=i.key WHERE r.pod=? AND i.kind='logs'",
                            (r["key"],),
                        ).fetchall()
                    else:
                        logs = conn.execute(
                            "SELECT payload FROM items WHERE kind='logs' AND json_extract(payload,'$.podId')=?",
                            (r["key"],),
                        ).fetchall()
                    data["logCount"] = len(logs)
                    if logs:
                        choices = [json.loads(l["payload"]) for l in logs]
                        choices.sort(
                            key=lambda x: (
                                x.get("variant") != "current",
                                -x.get("instance", -1),
                                x.get("container", ""),
                                x.get("rotation", ""),
                            )
                        )
                        data["logPodId"] = choices[0].get("podId", "")
                        data["logFileId"] = choices[0]["fileId"]
                    log_states = {json.loads(l["payload"])["status"] for l in logs}
                    data["logState"] = (
                        "ok"
                        if "ok" in log_states
                        else (
                            "partial"
                            if len(log_states) > 1
                            else next(iter(log_states), "missing")
                        )
                    )
                rows.append(data)
        next_cursor = (
            base64.urlsafe_b64encode(
                encoded({"offset": offset + len(rows), "signature": signature}).encode()
            ).decode()
            if offset + len(rows) < total
            else None
        )
        previous_cursor = (
            base64.urlsafe_b64encode(
                encoded(
                    {"offset": max(0, offset - limit), "signature": signature}
                ).encode()
            ).decode()
            if offset > 0
            else None
        )
        result = {
            "items": rows,
            "total": total,
            "nextCursor": next_cursor,
            "previousCursor": previous_cursor,
        }
        if kind == "resources":
            with self.connection() as conn:
                source = (
                    table_source
                    or conn.execute(
                        "SELECT * FROM sources WHERE name=?", (resource,)
                    ).fetchone()
                )
            if source:
                result.update(
                    {
                        "source": source["source"],
                        "columns": json.loads(source["columns"]),
                        "state": source["state"],
                        "note": source["note"],
                    }
                )
            if not result.get("columns") and rows:
                columns = [k for k in rows[0] if k.upper() == k]
                if not columns:
                    mapping = {
                        "name": "NAME",
                        "namespace": "NAMESPACE",
                        "ready": "READY",
                        "roles": "ROLES",
                        "ip": "INTERNAL-IP",
                        "kubeletVersion": "VERSION",
                        "type": "TYPE",
                        "reason": "REASON",
                        "objectName": "OBJECT",
                        "message": "MESSAGE",
                        "time": "TIME",
                    }
                    columns = [v for k, v in mapping.items() if k in rows[0]]
                    result["items"] = [
                        {mapping[k]: row.get(k, "") for k in mapping if k in rows[0]}
                        for row in rows
                    ]
                result["columns"] = columns
        if kind == "files":
            with self.connection() as conn:
                result["bytes"] = conn.execute(
                    f"SELECT coalesce(sum(json_extract(i.payload,'$.size')),0) FROM items i WHERE {condition}",
                    params,
                ).fetchone()[0]

        return result

    def entity(self, kind, entity_id):
        if kind not in ("pods", "nodes"):
            raise FileNotFoundError(entity_id)
        with self.connection() as conn:
            row = conn.execute(
                "SELECT payload,detail FROM items WHERE kind=? AND key=?",
                (kind, entity_id),
            ).fetchone()
            if row is None:
                raise FileNotFoundError(entity_id)
            data = json.loads(row["payload"])
            result = {
                "summary": data,
                "object": json.loads(row["detail"]) if row["detail"] else None,
                "describe": None,
            }
            ref = conn.execute(
                "SELECT * FROM descriptions WHERE kind=? AND ns=? AND name=?",
                (kind, data.get("namespace", ""), data["name"]),
            ).fetchone()
            if ref:
                path = self.root / ref["source"]
                with path.open("rb") as stream:
                    stream.seek(ref["start"])
                    text = stream.read(
                        min(ref["end"] - ref["start"], 1024 * 1024)
                    ).decode(errors="replace")
                result["describe"] = {
                    **parse_describe(text),
                    "source": ref["source"],
                    "fileId": identity(ref["source"]),
                    "offset": ref["start"],
                    "endOffset": ref["end"],
                    "truncated": ref["end"] - ref["start"] > 1024 * 1024,
                    "raw": text,
                }
            return result

    def file(self, file_id):
        with self.connection() as conn:
            row = conn.execute(
                "SELECT payload FROM items WHERE kind='files' AND key=?", (file_id,)
            ).fetchone()
        if row is None:
            raise FileNotFoundError(file_id)
        return json.loads(row["payload"])

    def file_page(
        self, file_id, offset=0, query="", direction="forward", anchor="", end=None
    ):
        from .reader import read_page

        file = self.file(file_id)
        path = self.root / file["path"]
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise FileNotFoundError(file_id)
        return read_page(path, file["path"], offset, query, direction, anchor, end)

    def completeness(self):
        groups = [
            (
                "resources",
                "资源清单",
                lambda p: "/kubectl/" in p
                and "/poddescribe/" not in p
                and not p.endswith("nodesdescribe"),
            ),
            (
                "details",
                "Pod / Node 详情与事件",
                lambda p: "/poddescribe/" in p
                or p.endswith(("nodesdescribe", "/events", "/events.json")),
            ),
            ("podLogs", "Pod 日志", lambda p: "/podlogs/" in p),
            (
                "componentLogs",
                "组件与系统日志",
                lambda p: p.startswith(("journald/", "systemlogs/", "rancher/"))
                or any(
                    s in p for s in ("/agent-logs/", "/server-logs/", "/containerlogs/")
                ),
            ),
            ("host", "主机信息", lambda p: p.startswith("systeminfo/")),
            ("network", "网络信息", lambda p: p.startswith("networking/")),
            ("etcd", "etcd", lambda p: p.startswith("etcd/")),
            (
                "config",
                "配置与证书",
                lambda p: "/certs/" in p
                or "/pod-manifests/" in p
                or p.endswith((".yaml", ".toml")),
            ),
        ]
        result = []
        with self.connection() as conn:
            files = [
                json.loads(r["payload"])
                for r in conn.execute("SELECT payload FROM items WHERE kind='files'")
            ]
            sources = {
                r["source"]: dict(r) for r in conn.execute("SELECT * FROM sources")
            }
            component_paths = {
                json.loads(r["payload"])["path"]
                for r in conn.execute(
                    "SELECT payload FROM items WHERE kind='logs' AND coalesce(json_extract(payload,'$.componentGroup'),'')<>''"
                )
            }
        collector = self.read("collector-output.log", 1024 * 1024)
        covered = {
            f["path"] for f in files if any(match(f["path"]) for _, _, match in groups)
        } | component_paths
        groups.append(("other", "其他采集数据", lambda p: p not in covered))
        for key, title, match in groups:
            selected = [
                f
                for f in files
                if (
                    f["path"] in component_paths
                    if key == "componentLogs"
                    else match(f["path"])
                )
            ]
            states = []
            examples = []
            for file in selected:
                source = sources.get(file["path"])
                state, note = (
                    (source["state"], source["note"])
                    if source
                    else self.file_status(file["path"], file["size"])
                )
                states.append(state)
                if len(examples) < 20 or state in ("failed", "unknown"):
                    if len(examples) < 50:
                        examples.append({**file, "state": state, "note": note})
            state = "missing"
            if states:
                kinds = set(states)
                state = "partial" if len(kinds) > 1 else states[0]
                if state == "unsupported":
                    state = "unknown"
            evidence = ""
            if not states:
                token = {
                    "etcd": "etcd",
                    "podLogs": "pod logs",
                    "network": "network",
                    "details": "describe",
                }.get(key, "")
                for line in collector.splitlines():
                    if (
                        token
                        and token in line.lower()
                        and re.search(
                            r"not applicable|not an? .* node|not supported", line, re.I
                        )
                    ):
                        state, evidence = "na", line[:400]
                        break
            result.append(
                {
                    "id": key,
                    "name": title,
                    "state": state,
                    "label": STATES[state],
                    "count": len(selected),
                    "counts": {s: states.count(s) for s in set(states)},
                    "files": examples,
                    "evidence": evidence,
                    "note": "未发现不代表采集器曾尝试采集；覆盖情况不代表集群健康。",
                }
            )
        return {
            "groups": result,
            "podCount": self.overview["counts"]["pods"],
            "podsWithLogs": self.overview["podLogCoverage"],
            "warnings": self.warnings[:50],
        }

    @property
    def files(self):
        with self.connection() as conn:
            return [
                json.loads(r["payload"])
                for r in conn.execute("SELECT payload FROM items WHERE kind='files'")
            ]

    @property
    def summary(self):
        with self.connection() as conn:
            pods = [
                json.loads(r["payload"])
                for r in conn.execute("SELECT payload FROM items WHERE kind='pods'")
            ]
            nodes = [
                json.loads(r["payload"])
                for r in conn.execute("SELECT payload FROM items WHERE kind='nodes'")
            ]
            namespaces = [
                r["name"]
                for r in conn.execute("SELECT name FROM items WHERE kind='namespaces'")
            ]
        return {
            **self.header,
            **{
                k: self.overview[k]
                for k in (
                    "bytes",
                    "podStatus",
                    "resources",
                    "system",
                    "etcd",
                    "warnings",
                )
            },
            "pods": pods,
            "nodes": nodes,
            "namespaces": namespaces,
            "files": self.files,
        }

    @property
    def resources(self):
        result = {}
        with self.connection() as conn:
            for source in conn.execute("SELECT * FROM sources"):
                kind = (
                    source["name"]
                    if source["name"] in ("pods", "nodes", "events")
                    else "resource:" + source["name"]
                )
                rows = [
                    json.loads(r["payload"])
                    for r in conn.execute(
                        "SELECT payload FROM items WHERE kind=?", (kind,)
                    )
                ]
                result[source["name"]] = {
                    "columns": json.loads(source["columns"]),
                    "rows": rows,
                    "source": source["source"],
                    "message": (
                        "No resources found"
                        if source["state"] == "empty"
                        else source["note"]
                    ),
                }
        return result
