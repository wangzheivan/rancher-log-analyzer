"""Narrow signatures only. A match is historical evidence, not a live failure."""

from datetime import datetime
import json
import re
from .config import DOCS

RULES = [
    (
        "etcd.slow",
        "etcd",
        rb"(?:apply (?:request|entries)|read-only range request|request|range request) took too long|failed to send out heartbeat on time|waiting for ReadIndex response took too long",
        "etcd 慢请求或心跳延迟信号",
        "核查同一时段磁盘延迟、CPU争用和请求负载；不能仅凭此日志确定磁盘故障。",
    ),
    (
        "kernel.oom",
        "system",
        rb"Out of memory:|Memory cgroup out of memory|oom-kill:|Killed process\s+\d+|\bTaskOOM\b|\bOOMKilled\b",
        "OOM/进程被杀历史信号",
        "核查同一时段内存、容器限制和内核记录，区分主机OOM与容器内存限制。",
    ),
    (
        "disk.io",
        "system",
        rb"Buffer I/O error|blk_update_request:.*I/O error|\bI/O error, dev\b|EXT4-fs error|XFS[^\n]{0,100}(?:corruption|I/O error)",
        "磁盘或文件系统 I/O 错误信号",
        "核查内核记录、存储设备状态和同一时段I/O延迟。",
    ),
    (
        "disk.full",
        "system",
        rb"\bno space left on device\b|\bmvcc: database space exceeded\b",
        "空间耗尽历史信号",
        "结合磁盘、inode及etcd配额判断耗尽位置，不据此认定当前仍已满。",
    ),
    (
        "disk.readonly",
        "system",
        rb"\bread-only file system\b|Remounting filesystem read-only",
        "文件系统只读历史信号",
        "核查受影响路径、挂载状态和此前的内核I/O错误。",
    ),
    (
        "files.exhausted",
        "system",
        rb"\btoo many open files\b|\bfile table overflow\b",
        "文件句柄耗尽历史信号",
        "核查受影响进程限制、文件句柄数量和泄漏风险。",
    ),
    (
        "runtime.sandbox",
        "system",
        rb"Failed to create pod sandbox|failed to (?:create|setup) (?:pod )?(?:network|sandbox)|NetworkPluginNotReady|cni plugin not initialized",
        "CNI 或 Pod sandbox 失败信号",
        "核查CNI组件状态、IP分配、运行时及对应Pod事件。",
    ),
    (
        "tls.expired",
        "certificates",
        rb"certificate has expired|certificate[^\n]{0,60}not yet valid",
        "TLS 证书时间异常历史信号",
        "核查错误涉及的端点、证书有效期和节点时间；不自动归属本包某张证书。",
    ),
]
RULES = [
    (id, cat, re.compile(pattern, re.I), title, advice)
    for id, cat, pattern, title, advice in RULES
]


def time_in(raw):
    text = raw[:4096].decode("utf-8", "replace")
    match = re.search(r"\b\d{4}-\d{2}-\d{2}[T ][\d:.]+(?:Z|[+-]\d{2}:?\d{2})?", text)
    value = match[0] if match else ""
    if not value:
        # Preserve timestamp strings from JSON logs without interpreting epoch counters or local zones.
        match = re.search(r'"(?:ts|time|timestamp)"\s*:\s*"([^"]{1,100})"', text)
        value = match[1] if match else ""
    parsed = ""
    if value:
        try:
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if date.tzinfo:
                from datetime import timezone

                parsed = date.astimezone(timezone.utc).isoformat()
        except ValueError:
            pass
    return value, parsed


def scan(engine, log, raw, base, overlap, max_start=None):
    etcd = log.get("serviceComponent") == "etcd"
    embedded = log.get("serviceComponent") in ("rke2-server", "k3s", "k3s-server")
    runtime = log.get("componentGroup") in (
        "kubernetes",
        "runtime",
        "host",
        "distribution",
    )
    obj = {
        "kind": "Pod" if log.get("pod") else "Service",
        "id": log.get("podId") or log["id"],
        "name": log.get("pod") or log.get("component") or log["path"],
        "namespace": log.get("namespace", ""),
        "node": log.get("node", ""),
        "uid": log.get("uid", ""),
        "logFileId": log["id"],
        "podId": log.get("podId", ""),
        "snapshotPodId": log.get("snapshotPodId", ""),
        "source": log["path"],
    }
    for rule, category, pattern, title, advice in RULES:
        if rule == "etcd.slow" and not (
            etcd
            or embedded
            and re.search(
                rb"etcdserver|apply (?:request|entries) took too long|ReadIndex",
                raw,
                re.I,
            )
        ):
            continue
        if rule in ("disk.io", "runtime.sandbox") and not runtime:
            continue
        for match in pattern.finditer(raw):
            if (
                match.end() <= overlap
                or max_start is not None
                and match.start() >= max_start
            ):
                continue
            raw_time, parsed = time_in(raw)
            excerpt = raw[
                max(0, match.start() - 200) : min(len(raw), match.end() + 600)
            ].decode("utf-8", "replace")
            engine.emit(
                rule,
                obj,
                category,
                "warning",
                "history",
                title,
                excerpt,
                advice,
                source=log["path"],
                offset=base + match.start(),
                raw_time=raw_time,
                parsed_time=parsed,
                docs=DOCS["etcd"] if category == "etcd" else DOCS["runtime"],
                condition="仅代表已扫描范围内的历史命中，不表示快照仍有故障",
            )
