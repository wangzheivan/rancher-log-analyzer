"""Cooperative, bounded analysis. No complete log body or resource list in memory."""

from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Event, RLock
import base64
import json
import math
import time
import re
import sqlite3
from pathlib import Path

from ..catalog import identity
from ..archive import Cancelled
from .config import VERSION, CATEGORIES, thresholds

CHUNK = 2 * 1024 * 1024


class Analysis:
    def __init__(self, bundle, path, settings, deleted=None):
        self.bundle, self.path, self.settings = bundle, Path(path), settings
        self.deleted = deleted or Event()
        self.cancelled = Event()
        self.lock = RLock()
        self.thresholds = thresholds(settings.analysis_thresholds)
        self.state, self.error = "queued", ""
        self.run_id = identity(datetime.now(timezone.utc).isoformat(), str(path))
        self.checked_at = datetime.now(timezone.utc).isoformat()
        self.processing_seconds = 0.0
        self.phase = "structured"
        self.structured_done = False
        self.generator = None
        self.writer = None
        self.initialized = False
        self.truncated = set()
        self.round_bytes = self.round_files = self.scanned_bytes = 0
        self.round_ids = set()
        self.boundaries = {}
        self.active = None
        self.carry = b""
        self.can_continue = True

    def reset_round(self):
        with self.lock:
            self.cancelled.clear()
            self.round_bytes = self.round_files = 0
            self.round_ids = set()
            self.state, self.error = "queued", ""

    def initialize(self):
        self.writer.execute(
            f"PRAGMA max_page_count={max(1,(self.settings.analysis_limit-262144)//8192)}"
        )
        self.writer.executescript("""
        PRAGMA journal_mode=DELETE; PRAGMA cache_size=-4096; PRAGMA temp_store=MEMORY;
        CREATE TABLE findings(id TEXT PRIMARY KEY,rule TEXT,category TEXT,severity TEXT,evidence_type TEXT,
          namespace TEXT,node TEXT,title TEXT,payload TEXT,count INTEGER DEFAULT 0);
        CREATE INDEX finding_filter ON findings(evidence_type,severity,category,namespace,node);
        CREATE TABLE facts(id TEXT PRIMARY KEY,label TEXT,value TEXT,source TEXT,note TEXT);
        CREATE TABLE observations(id TEXT PRIMARY KEY,rule TEXT,name TEXT,value REAL,source TEXT,note TEXT);
        CREATE TABLE checks(rule TEXT,object_key TEXT,state TEXT,category TEXT,PRIMARY KEY(rule,object_key));
        CREATE TABLE evidence(finding TEXT,file_id TEXT,path TEXT,offset INTEGER,text TEXT,raw_time TEXT,
          parsed_time TEXT,PRIMARY KEY(finding,file_id,offset));
        CREATE TABLE log_files(id TEXT PRIMARY KEY,seq INTEGER,payload TEXT,size INTEGER,next_end INTEGER,
          scanned INTEGER DEFAULT 0,visited INTEGER DEFAULT 0,priority INTEGER);
        """)
        # Reserve room for the rollback journal as well as the database itself.
        self.writer.execute(
            f"PRAGMA max_page_count={max(1,(self.settings.analysis_limit-262144)//8192)}"
        )
        from .rules import structured

        self.generator = structured(self)
        self.initialized = True

    def guard(self):
        if self.deleted.is_set() or self.cancelled.is_set():
            raise Cancelled("分析已取消")

    def objects(self, kind, detail=False):
        last = 0
        while True:
            self.guard()
            detail_column = "detail" if detail else "''"
            with self.bundle.connection() as conn:
                cursor = conn.execute(
                    f"SELECT seq,payload,{detail_column} AS detail FROM items WHERE kind=? AND seq>? ORDER BY seq LIMIT 200",
                    (kind, last),
                )
                rows = []
                budget = 0
                for raw in cursor:
                    rows.append(raw)
                    budget += len(raw["payload"]) + (
                        len(raw["detail"]) if detail else 0
                    )
                    if budget >= 1024 * 1024:
                        break
            if not rows:
                return
            for row in rows:
                self.guard()
                last = row["seq"]
                item = json.loads(row["payload"])
                if detail:
                    item["_detail"] = (
                        json.loads(row["detail"]) if row["detail"] else None
                    )
                yield item
            rows.clear()
            del row, item, raw, cursor
            yield None  # Release the worker/connection between resource batches.

    def read(self, path, limit=CHUNK):
        target = self.bundle.root / path
        if (
            not target.is_file()
            or target.is_symlink()
            or not target.resolve().is_relative_to(self.bundle.root)
        ):
            return ""
        if target.stat().st_size > limit:
            self.truncated.add(path)
            self.check(
                "source.truncated",
                {"kind": "File", "id": identity(path), "name": path, "source": path},
                "unknown",
                "system",
                "源文件超过结构化读取预算，后续内容未检查",
            )
        with target.open("rb") as f:
            return f.read(limit).decode("utf-8", "replace")

    def fact(self, key, label, value, source="", note=""):
        self.writer.execute(
            "INSERT OR REPLACE INTO facts VALUES(?,?,?,?,?)",
            (key, label, str(value)[:500], source, note[:500]),
        )

    def object_key(self, obj):
        return (
            obj.get("analysisObjectKey")
            or obj.get("uid")
            or obj.get("id")
            or identity(obj.get("kind"), obj.get("namespace"), obj.get("name"))
        )

    def check(self, rule, obj, state, category, note="", source=""):
        key = self.object_key(obj)
        self.writer.execute(
            "INSERT OR REPLACE INTO checks VALUES(?,?,?,?)",
            (rule, key, state, category),
        )
        if state == "unknown":
            self.emit(
                rule,
                obj,
                category,
                "unknown",
                "unknown",
                note or "证据不足，无法判断",
                note,
                "请核对对应原始文件，必要时重新采集缺失的数据。",
                source=source or obj.get("source", ""),
            )

    def emit(
        self,
        rule,
        obj,
        category,
        severity,
        evidence_type,
        title,
        observed,
        advice,
        *,
        source="",
        offset=0,
        raw_time="",
        parsed_time="",
        docs="",
        condition="",
    ):
        self.guard()
        key = identity(rule, self.object_key(obj), evidence_type)
        payload = {
            "id": key,
            "ruleId": rule,
            "category": category,
            "severity": severity,
            "evidenceType": evidence_type,
            "title": title,
            "observed": str(observed)[:2000],
            "observedTruncated": len(str(observed)) > 2000,
            "condition": condition,
            "advice": advice,
            "docs": docs,
            "object": {k: v for k, v in obj.items() if k != "_detail"},
            "checkedAt": self.checked_at,
        }
        self.writer.execute(
            "INSERT OR IGNORE INTO findings VALUES(?,?,?,?,?,?,?,?,?,0)",
            (
                key,
                rule,
                category,
                severity,
                evidence_type,
                obj.get("namespace", ""),
                obj.get("node", ""),
                title,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        if evidence_type != "history":
            self.writer.execute(
                "INSERT OR REPLACE INTO checks VALUES(?,?,?,?)",
                (
                    rule,
                    self.object_key(obj),
                    "unknown" if severity == "unknown" else "detected",
                    category,
                ),
            )
        inserted = self.writer.execute(
            "INSERT OR IGNORE INTO evidence VALUES(?,?,?,?,?,?,?)",
            (
                key,
                identity(source),
                source,
                max(0, offset),
                str(observed)[:1200],
                raw_time[:100],
                parsed_time,
            ),
        ).rowcount
        if inserted:
            self.writer.execute("UPDATE findings SET count=count+1 WHERE id=?", (key,))
        return key

    def metric(
        self,
        rule,
        obj,
        name,
        value,
        category="resources",
        source="",
        invert=False,
        note="",
    ):
        if (
            value is None
            or not math.isfinite(value)
            or value < 0
            or (
                rule.split(".")[-1] in ("cpu", "iowait", "memoryAvailable")
                and value > 100
            )
        ):
            self.check(
                rule, obj, "unknown", category, name + "数据缺失或无法解析", source
            )
            return
        self.writer.execute(
            "INSERT OR REPLACE INTO observations VALUES(?,?,?,?,?,?)",
            (
                identity(rule, self.object_key(obj)),
                rule,
                name,
                value,
                source,
                note[:1000],
            ),
        )
        a, b = self.thresholds[rule.split(".")[-1]]
        severity = (
            ("high" if value < b else "warning" if value < a else "")
            if invert
            else ("high" if value >= b else "warning" if value >= a else "")
        )
        condition = (
            f'关注 {"<" if invert else "≥"}{a}；高风险 {"<" if invert else "≥"}{b}'
        )
        text = f"{name} = {value:.2f}；{condition}。{note}"
        if severity:
            self.emit(
                rule,
                obj,
                category,
                severity,
                "snapshot",
                name + "达到初筛阈值",
                text,
                "核对采样时间与工作负载，检查是否持续超限；此阈值为项目初筛配置。",
                source=source,
                condition=condition,
            )
        else:
            self.check(rule, obj, "passed", category)
        return text

    def candidates(self):
        # SQL joins use indexed Pod relations, without materializing all Pods or logs.
        last = 0
        while True:
            with self.bundle.connection() as conn:
                records = conn.execute(
                    """SELECT l.seq,l.payload,
                  EXISTS(SELECT 1 FROM relations r JOIN items p ON p.key=r.pod AND p.kind='pods'
                    WHERE r.file=l.key AND json_extract(p.payload,'$.attention')=1) abnormal
                  FROM items l WHERE l.kind='logs' AND l.seq>? ORDER BY l.seq LIMIT 200""",
                    (last,),
                ).fetchall()
            if not records:
                break
            for row in records:
                last = row["seq"]
                self.guard()
                log = json.loads(row["payload"])
                component = log.get("componentGroup", "")
                if not component and not row["abnormal"]:
                    continue
                if log["status"] in ("empty", "failed", "unsupported"):
                    obj = {
                        "kind": "File",
                        "id": log["id"],
                        "name": log["path"],
                        "source": log["path"],
                        "node": log.get("node", ""),
                    }
                    self.check(
                        "logs.source",
                        obj,
                        "na" if log["status"] == "empty" else "unknown",
                        "system",
                        "日志未扫描："
                        + log.get("note", "")
                        + " ("
                        + log["status"]
                        + ")",
                        log["path"],
                    )
                    continue
                priority = (
                    0
                    if log.get("serviceComponent") == "etcd"
                    else 1 if component else 2
                )
                if log.get("variant") == "previous":
                    priority = 3
                self.writer.execute(
                    "INSERT OR IGNORE INTO log_files(id,seq,payload,size,next_end,priority) VALUES(?,?,?,?,?,?)",
                    (
                        log["id"],
                        row["seq"],
                        json.dumps(log, ensure_ascii=False),
                        log["size"],
                        log["size"],
                        priority,
                    ),
                )
                yield
            yield
        # dmesg is also collected outside the component log directories.
        path = "systeminfo/dmesg"
        file_id = identity(path)
        try:
            file = self.bundle.file(file_id)
            if file["size"] and self.bundle.file_status(path, file["size"])[0] == "ok":
                log = {
                    **file,
                    "componentGroup": "host",
                    "node": self.bundle.header["hostname"],
                    "sourceType": "file",
                }
                self.writer.execute(
                    "INSERT OR IGNORE INTO log_files(id,seq,payload,size,next_end,priority) VALUES(?,?,?,?,?,?)",
                    (file_id, 0, json.dumps(log), file["size"], file["size"], 1),
                )
        except FileNotFoundError:
            pass

    def step(self):
        with self.lock:
            self.guard()
            self.state = "running"
            step_started = time.perf_counter()
            conn = sqlite3.connect(self.path, timeout=2)
            conn.row_factory = sqlite3.Row
            self.writer = conn
            try:
                if not self.initialized:
                    self.initialize()
                if self.phase == "structured":
                    if self.generator is None:
                        from .rules import structured

                        self.generator = structured(self)
                    try:
                        next(self.generator)
                    except StopIteration:
                        self.structured_done = True
                        self.phase = "candidates"
                        self.generator = self.candidates()
                elif self.phase == "candidates":
                    if self.generator is None:
                        self.generator = self.candidates()
                    for _ in range(200):
                        try:
                            next(self.generator)
                        except StopIteration:
                            self.phase = "logs"
                            self.generator = None
                            break
                else:
                    self.scan_chunk()
                conn.commit()
                return self.state == "running"
            except Cancelled:
                conn.rollback()
                if self.phase in ("structured", "candidates"):
                    self.generator = None
                self.state = "cancelled"
                return False
            except (sqlite3.DatabaseError, OSError, ValueError, TypeError) as exc:
                conn.rollback()
                self.state = "failed"
                self.can_continue = False
                self.error = "分析未完成：结果预算不足或源数据无法读取；已提交结果保留，可调整配置后重新分析。"
                return False
            finally:
                self.processing_seconds += time.perf_counter() - step_started
                conn.close()
                self.writer = None

    def scan_chunk(self):
        if self.round_bytes >= self.settings.analysis_scan_bytes:
            self.state = "partial"
            return
        if not self.active:
            rows = self.writer.execute(
                "SELECT * FROM log_files WHERE next_end>0 ORDER BY visited,priority,seq"
            )
            row = next((r for r in rows if r["id"] not in self.round_ids), None)
            if row is None:
                remaining = self.writer.execute(
                    "SELECT count(*) FROM log_files WHERE next_end>0"
                ).fetchone()[0]
                self.state = "partial" if remaining else "complete"
                return
            if self.round_files >= self.settings.analysis_scan_files:
                self.state = "partial"
                return
            log = json.loads(row["payload"])
            end = row["next_end"]
            start = max(0, end - self.settings.analysis_file_bytes)
            self.active = {
                "log": log,
                "start": start,
                "position": start,
                "end": end,
                "prefix": b"",
                "right": self.boundaries.get(log["id"], b""),
            }
            self.carry = b""
            self.round_ids.add(row["id"])
            self.round_files += 1
        active = self.active
        log = active["log"]
        if log["id"] not in self.round_ids:
            self.round_ids.add(log["id"])
            self.round_files += 1
        take = min(
            CHUNK,
            self.settings.analysis_scan_bytes - self.round_bytes,
            active["end"] - active["position"],
        )
        target = self.bundle.root / log["path"]
        if target.is_symlink() or not target.resolve().is_relative_to(self.bundle.root):
            raise ValueError("日志来源无效")
        with target.open("rb") as stream:
            stream.seek(active["position"])
            block = stream.read(take)
        if not block and take:
            raise ValueError("采集文件意外变化")
        from .log_rules import scan

        if active["position"] == active["start"]:
            active["prefix"] = block[:512]
        position = active["position"]
        # Bound long lines and retain a small overlap for keywords crossing segments.
        for raw in block.splitlines(keepends=True):
            for at in range(0, len(raw), 65536):
                self.guard()
                segment = raw[at : at + 65536]
                combined = self.carry + segment
                scan(self, log, combined, position - len(self.carry), len(self.carry))
                position += len(segment)
                self.carry = (
                    b"" if segment.endswith((b"\n", b"\r")) else combined[-512:]
                )
        amount = len(block)
        active["position"] += amount
        self.round_bytes += amount
        self.scanned_bytes += amount
        self.writer.execute(
            "UPDATE log_files SET scanned=scanned+?,next_end=?,visited=1 WHERE id=?",
            (amount, active["end"] - (active["position"] - active["start"]), log["id"]),
        )
        # next_end is only finalized at a window boundary; active remembers the forward cursor.
        if active["position"] >= active["end"]:
            if self.carry and active["right"]:
                scan(
                    self,
                    log,
                    self.carry + active["right"],
                    active["end"] - len(self.carry),
                    0,
                    max_start=len(self.carry),
                )
            self.boundaries[log["id"]] = active["prefix"]
            self.writer.execute(
                "UPDATE log_files SET next_end=? WHERE id=?",
                (active["start"], log["id"]),
            )
            self.active = None
            self.carry = b""

    @contextmanager
    def connection(self):
        with self.lock:
            if self.deleted.is_set():
                raise FileNotFoundError("采集包已删除")
            if not self.path.is_file() or not self.initialized:
                yield None
                return
            conn = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=2)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()

    def status(self):
        with self.connection() as conn:
            counts = {"high": 0, "warning": 0, "info": 0, "unknown": 0}
            checks = {}
            observations = []
            facts = []
            check_coverage = {}
            coverage = {
                "candidateFiles": 0,
                "visitedFiles": 0,
                "completeFiles": 0,
                "candidateBytes": 0,
                "remainingBytes": 0,
            }
            if conn:
                facts = [
                    dict(r)
                    for r in conn.execute("SELECT * FROM facts ORDER BY id LIMIT 16")
                ]
                for r in conn.execute(
                    "SELECT category,state,count(*) n FROM checks GROUP BY category,state"
                ):
                    check_coverage.setdefault(r["category"], {})[r["state"]] = r["n"]
                observations = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT rule,name,max(value) value,source,count(*) measurements,note FROM observations GROUP BY rule ORDER BY rule LIMIT 16"
                    )
                ]
                counts.update(
                    {
                        r["severity"]: r["n"]
                        for r in conn.execute(
                            "SELECT severity,count(*) n FROM findings GROUP BY severity"
                        )
                    }
                )
                checks = {
                    r["state"]: r["n"]
                    for r in conn.execute(
                        "SELECT state,count(*) n FROM checks GROUP BY state"
                    )
                }
                row = conn.execute(
                    "SELECT count(*) total,coalesce(sum(visited),0) visited,coalesce(sum(next_end=0),0) complete,coalesce(sum(size),0) bytes,coalesce(sum(size-scanned),0) remaining FROM log_files"
                ).fetchone()
                coverage = dict(
                    zip(
                        coverage,
                        [
                            row["total"],
                            row["visited"],
                            row["complete"],
                            row["bytes"],
                            row["remaining"],
                        ],
                    )
                )
            return {
                "state": self.state,
                "phase": self.phase,
                "error": self.error,
                "runId": self.run_id,
                "ruleVersion": VERSION,
                "checkedAt": self.checked_at,
                "processingSeconds": self.processing_seconds,
                "counts": counts,
                "checks": checks,
                "observations": observations,
                "facts": facts,
                "checkCoverage": check_coverage,
                "thresholds": self.thresholds,
                "categories": CATEGORIES,
                "coverage": {
                    **coverage,
                    "scannedBytes": self.scanned_bytes,
                    "roundBytes": self.round_bytes,
                    "roundFiles": self.round_files,
                    "structuredComplete": self.structured_done,
                    "candidateListComplete": self.phase == "logs",
                },
                "limits": {
                    "roundBytes": self.settings.analysis_scan_bytes,
                    "roundFiles": self.settings.analysis_scan_files,
                    "fileBytes": self.settings.analysis_file_bytes,
                    "resultBytes": self.settings.analysis_limit,
                },
                "canContinue": self.can_continue
                and self.state in ("partial", "cancelled"),
                "resultBytes": self.path.stat().st_size if self.path.exists() else 0,
            }

    def findings(
        self,
        limit=50,
        cursor="",
        q="",
        category="",
        severity="",
        evidence_type="",
        namespace="",
        node="",
    ):
        if (
            category
            and category not in CATEGORIES
            or severity
            and severity not in ("high", "warning", "info", "unknown")
            or evidence_type
            and evidence_type not in ("snapshot", "history", "unknown")
        ):
            raise ValueError("未知发现筛选条件")
        signature = identity(
            self.run_id, q, category, severity, evidence_type, namespace, node, limit
        )
        offset = 0
        watermark = None
        if cursor:
            try:
                data = json.loads(base64.urlsafe_b64decode(cursor))
                offset = int(data["offset"])
                watermark = int(data["watermark"])
                if watermark < 0:
                    raise ValueError()
                if data["signature"] != signature or not 0 <= offset <= 10000000:
                    raise ValueError()
            except Exception as exc:
                raise ValueError("分析分页游标无效或条件已改变") from exc
        where = ["1=1"]
        params = []
        for field, value in [
            ("category", category),
            ("severity", severity),
            ("evidence_type", evidence_type),
            ("namespace", namespace),
            ("node", node),
        ]:
            if value:
                where.append(field + "=?")
                params.append(value)
        if q:
            where.append("instr(lower(payload),?)>0")
            params.append(q.lower())
        condition = " AND ".join(where)
        rows = []
        total = 0
        with self.connection() as conn:
            if conn:
                if watermark is None:
                    watermark = conn.execute(
                        "SELECT coalesce(max(rowid),0) FROM findings"
                    ).fetchone()[0]
                condition += " AND rowid<=?"
                params.append(watermark)
                total = conn.execute(
                    "SELECT count(*) FROM findings WHERE " + condition, params
                ).fetchone()[0]
                order = "CASE evidence_type WHEN 'snapshot' THEN 0 WHEN 'history' THEN 1 ELSE 2 END,CASE severity WHEN 'high' THEN 0 WHEN 'warning' THEN 1 WHEN 'info' THEN 2 ELSE 3 END,id"
                for r in conn.execute(
                    "SELECT payload,count FROM findings WHERE "
                    + condition
                    + " ORDER BY "
                    + order
                    + " LIMIT ? OFFSET ?",
                    params + [limit, offset],
                ):
                    item = json.loads(r["payload"])
                    item["count"] = r["count"]
                    rows.append(item)
        for item in rows:
            if self.deleted.is_set():
                raise FileNotFoundError("采集包已删除")
            obj = item["object"]
            if obj.get("kind") in ("Pod", "Node") and obj.get("entityId"):
                events = self.bundle.catalog(
                    "events",
                    limit=3,
                    object_name=obj.get("name", ""),
                    object_kind=obj["kind"],
                    object_uid=obj.get("uid", ""),
                    namespace=obj.get("namespace", ""),
                )
                item["eventsTotal"] = events["total"]
                item["eventPreview"] = [
                    {k: (v[:400] if isinstance(v, str) else v) for k, v in ev.items()}
                    for ev in events["items"]
                ]

        def token(at):
            return base64.urlsafe_b64encode(
                json.dumps(
                    {"offset": at, "signature": signature, "watermark": watermark or 0}
                ).encode()
            ).decode()

        return {
            "items": rows,
            "total": total,
            "nextCursor": (
                token(offset + len(rows)) if offset + len(rows) < total else None
            ),
            "previousCursor": token(max(0, offset - limit)) if offset else None,
            "runId": self.run_id,
        }

    def detail(self, finding_id, cursor=""):
        offset = 0
        if cursor:
            try:
                data = json.loads(base64.urlsafe_b64decode(cursor))
                offset = int(data["offset"])
                if (
                    data["id"] != finding_id
                    or data["run"] != self.run_id
                    or not 0 <= offset <= 10000000
                ):
                    raise ValueError()
            except Exception as exc:
                raise ValueError("证据分页游标无效") from exc
        with self.connection() as conn:
            row = (
                conn.execute(
                    "SELECT payload,count FROM findings WHERE id=?", (finding_id,)
                ).fetchone()
                if conn
                else None
            )
            if not row:
                raise FileNotFoundError(finding_id)
            result = json.loads(row["payload"])
            result["count"] = row["count"]
            examples = [
                dict(r)
                for r in conn.execute(
                    "SELECT file_id fileId,path,offset,text,raw_time rawTime,parsed_time parsedTime FROM evidence WHERE finding=? ORDER BY file_id,offset LIMIT 10 OFFSET ?",
                    (finding_id, offset),
                )
            ]

        def token(at):
            return base64.urlsafe_b64encode(
                json.dumps(
                    {"offset": at, "id": finding_id, "run": self.run_id}
                ).encode()
            ).decode()

        result["evidence"] = {
            "items": examples,
            "total": result["count"],
            "nextCursor": (
                token(offset + len(examples))
                if offset + len(examples) < result["count"]
                else None
            ),
            "previousCursor": token(max(0, offset - 10)) if offset else None,
        }
        return result
