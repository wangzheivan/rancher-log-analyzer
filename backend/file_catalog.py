"""Metadata-only file classification and bounded directory browsing."""

import base64
import json
from pathlib import PurePosixPath

GROUPS = {
    "metadata": "采集元信息",
    "host": "主机",
    "network": "网络",
    "resources": "资源清单",
    "details": "资源详情",
    "podLogs": "Pod 日志",
    "components": "组件日志",
    "runtime": "运行时",
    "etcd": "etcd",
    "config": "配置与证书",
    "other": "其他",
}


def file_group(path):
    p = path.lower()
    if p in ("summary.txt", "versions", "collector-output.log"):
        return "metadata"
    if "/podlogs/" in p:
        return "podLogs"
    if "/poddescribe/" in p or p.endswith("/nodesdescribe"):
        return "details"
    if "/kubectl/" in p:
        return "resources"
    if p.startswith("etcd/"):
        return "etcd"
    if (
        "/certs/" in p
        or "/pod-manifests/" in p
        or p.endswith((".yaml", ".yml", ".toml", ".crt", ".pem", ".key"))
    ):
        return "config"
    if (
        p.startswith(("journald/", "systemlogs/"))
        or any(s in p for s in ("/containerlogs/", "/agent-logs/", "/server-logs/"))
        or p.endswith(".log")
    ):
        return "components"
    if (
        "/crictl/" in p
        or p.startswith("docker/")
        or "/containerinspect/" in p
        or "/directories/" in p
    ):
        return "runtime"
    if p.startswith("systeminfo/"):
        return "host"
    if p.startswith("networking/"):
        return "network"
    if "/" not in p:
        return "metadata"
    return "other"


def directory_prefix(directory):
    if not directory:
        return ""
    p = PurePosixPath(directory)
    if p.is_absolute() or ".." in p.parts or "\\" in directory:
        raise ValueError("目录无效")
    return p.as_posix().rstrip("/") + "/"


def grouped_catalog(bundle, kind, limit, cursor, q, group, directory):
    from .catalog import identity

    signature = identity(kind, q, group, directory)
    offset = 0
    if cursor:
        try:
            value = json.loads(base64.urlsafe_b64decode(cursor))
            offset = int(value["offset"])
            if value["signature"] != signature or not 0 <= offset <= 10000000:
                raise ValueError()
        except Exception as exc:
            raise ValueError("分页游标无效或筛选条件已改变") from exc
    with bundle.connection() as conn:
        if kind == "fileGroups":
            stats = {
                r["g"]: (r["n"], r["b"])
                for r in conn.execute(
                    "SELECT json_extract(payload,'$.group') g,count(*) n,sum(json_extract(payload,'$.size')) b FROM items WHERE kind='files' GROUP BY g"
                )
            }
            rows = [
                {
                    "id": key,
                    "name": label,
                    "count": stats.get(key, (0, 0))[0],
                    "bytes": stats.get(key, (0, 0))[1],
                }
                for key, label in GROUPS.items()
                if q.lower() in label.lower()
            ]
            total = len(rows)
            rows = rows[offset : offset + limit]
        else:
            prefix = directory_prefix(directory)
            condition = "kind='files' AND substr(json_extract(payload,'$.path'),1,?)=?"
            # Prefix uses bound arguments, not SQL LIKE wildcards.
            params = [len(prefix) + 1, len(prefix), prefix]
            if group:
                condition += " AND json_extract(payload,'$.group')=?"
                params.append(group)
            sql = f"""WITH paths AS (SELECT substr(json_extract(payload,'$.path'),?) tail,json_extract(payload,'$.size') size FROM items WHERE {condition}), dirs AS (SELECT substr(tail,1,instr(tail,'/')-1) name,count(*) count,sum(size) bytes FROM paths WHERE instr(tail,'/')>0 GROUP BY name) SELECT * FROM dirs WHERE instr(lower(name),?)>0 ORDER BY name"""
            params.append(q.lower())
            total = conn.execute(
                "SELECT count(*) FROM (" + sql + ")", params
            ).fetchone()[0]
            rows = [
                {
                    "id": prefix + r["name"],
                    "name": r["name"],
                    "path": prefix + r["name"],
                    "count": r["count"],
                    "bytes": r["bytes"],
                }
                for r in conn.execute(
                    sql + " LIMIT ? OFFSET ?", params + [limit, offset]
                )
            ]

    def token(at):
        return base64.urlsafe_b64encode(
            json.dumps({"offset": at, "signature": signature}).encode()
        ).decode()

    return {
        "items": rows,
        "total": total,
        "nextCursor": token(offset + len(rows)) if offset + len(rows) < total else None,
        "previousCursor": token(max(0, offset - limit)) if offset else None,
    }
