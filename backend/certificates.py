"""Bounded offline OpenSSL text parsing and request-time validity checks."""

import base64
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc
MAX_CERT_BYTES = 1024 * 1024
STATES = ("expired", "expiring", "notYetValid", "valid", "unknown")
PURPOSES = {
    "ca": "CA 证书",
    "client": "客户端证书",
    "server": "服务端证书",
    "other": "其他证书",
}


def cert_date(raw):
    try:
        return datetime.strptime(
            re.sub(r"\s+", " ", raw.strip()), "%b %d %H:%M:%S %Y GMT"
        ).replace(tzinfo=UTC)
    except ValueError:
        return None


def parse_certificates(text):
    blocks = re.split(r"(?m)^\s*Certificate:\s*$", text)[1:]
    if not blocks:
        unsupported = (
            "-----BEGIN CERTIFICATE-----" in text or "\0" in text or "\ufffd" in text
        )
        return [
            {
                "parseState": ("unsupported" if unsupported else "invalid"),
                "note": (
                    "暂不支持此证书格式"
                    if unsupported
                    else "未找到有效的 OpenSSL 证书文本"
                ),
            }
        ]
    records = []
    for block in blocks:

        def field(label):
            match = re.search(r"(?m)^\s*" + label + r"\s*:\s*(.*)$", block)
            return match.group(1).strip() if match else ""

        before, after = cert_date(field("Not Before")), cert_date(field("Not After"))
        ca = bool(re.search(r"\bCA:TRUE\b", block))
        purpose = (
            "ca"
            if ca
            else (
                "server"
                if "TLS Web Server Authentication" in block
                else "client" if "TLS Web Client Authentication" in block else "other"
            )
        )
        san = re.search(r"X509v3 Subject Alternative Name:\s*\n([^\n]+)", block)
        valid = before is not None and after is not None and before < after
        records.append(
            {
                "subject": field("Subject"),
                "issuer": field("Issuer"),
                "serial": field("Serial Number"),
                "notBefore": before.isoformat() if before else None,
                "notAfter": after.isoformat() if after else None,
                "notBeforeEpoch": before.timestamp() if before else None,
                "notAfterEpoch": after.timestamp() if after else None,
                "isCA": ca,
                "san": san.group(1).strip() if san else "",
                "purpose": purpose,
                "parseState": "ok" if valid else "invalid",
                "note": "" if valid else "证书有效期缺失、无效或顺序错误",
            }
        )
    return records


def build_certificates(bundle):
    files = bundle.writer.execute("SELECT payload FROM items WHERE kind='files'")
    for row in files:
        bundle.check()
        file = json.loads(row["payload"])
        path = file["path"]
        if "/certs/" not in path or PurePosixPath(path).suffix.lower() not in (
            ".crt",
            ".cer",
            ".pem",
        ):
            continue
        if file["size"] > MAX_CERT_BYTES:
            records = [
                {"parseState": "oversize", "note": "证书文件超过 1 MiB 解析上限"}
            ]
        else:
            records = parse_certificates(bundle.read(path, MAX_CERT_BYTES))
        for index, data in enumerate(records, 1):
            key = hashlib.sha256(f"{path}\0{index}".encode()).hexdigest()[:24]
            bundle.put(
                "certificates",
                key,
                {
                    "id": key,
                    "name": PurePosixPath(path).name,
                    "path": path,
                    "source": path,
                    "sourceIndex": index,
                    "node": bundle.header["hostname"],
                    "purpose": "other",
                    **data,
                },
            )


def reference_time(bundle, basis, zone, now):
    if basis not in ("current", "collected"):
        raise ValueError("未知证书检查时间基准")
    if zone:
        try:
            tz = ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("请选择有效的 IANA 时区，例如 Asia/Shanghai") from exc
    else:
        tz = None
    if basis == "current":
        return now, "服务端当前 UTC 时间"
    raw = bundle.header.get("generated", "")
    if raw in ("", "未知"):
        raw = bundle.read("systeminfo/date", 1024).strip()
    # ISO timestamps with explicit offsets are unambiguous.
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo:
            return parsed.astimezone(UTC), "采集时间的明确 UTC 偏移"
        if tz:
            return localize(parsed, tz), "用户指定采集时区：" + zone
    except ValueError:
        pass
    match = re.fullmatch(
        r"(?:[A-Za-z]{3}\s+)?([A-Za-z]{3}\s+\d+\s+\d{2}:\d{2}:\d{2})\s+(\S+)\s+(\d{4})",
        raw,
    )
    if not match:
        return None, "无法解析采集时间，不能进行采集时刻判断"
    try:
        parsed = datetime.strptime(
            re.sub(r"\s+", " ", match[1] + " " + match[3]), "%b %d %H:%M:%S %Y"
        )
    except ValueError:
        return None, "采集时间无效"
    token = match[2]
    if token in ("UTC", "GMT"):
        return parsed.replace(tzinfo=UTC), "采集时间的明确 UTC 时区"
    if re.fullmatch(r"[+-]\d{4}", token):
        try:
            parsed = datetime.strptime(
                match[1] + " " + match[3] + " " + token, "%b %d %H:%M:%S %Y %z"
            )
            return parsed.astimezone(UTC), "采集时间的明确 UTC 偏移"
        except ValueError:
            return None, "采集时间偏移无效"
    # timedatectl can disambiguate abbreviations, but never infer CST from the host/browser locale.
    if not tz:
        info = bundle.read("systeminfo/timedatectl", 8192)
        candidate = re.search(
            r"Time zone:\s*([A-Za-z_+-]+(?:/[A-Za-z_+-]+)+|UTC)\b", info
        )
        if candidate:
            try:
                tz = ZoneInfo(candidate[1])
                zone = candidate[1]
            except ZoneInfoNotFoundError:
                pass
    if tz:
        return localize(parsed, tz), "采集时区：" + zone
    return None, f"采集时区 {token} 不明确，请选择时区后检查"


def localize(value, tz):
    # Ambiguous/nonexistent DST wall times cannot be silently chosen.
    first, second = value.replace(tzinfo=tz, fold=0), value.replace(tzinfo=tz, fold=1)
    if (
        first.utcoffset() != second.utcoffset()
        or first.astimezone(UTC).astimezone(tz).replace(tzinfo=None) != value
    ):
        raise ValueError("采集时间位于夏令时歧义或不存在的时段，无法可靠判断")
    return first.astimezone(UTC)


def certificate_page(
    bundle,
    limit=50,
    cursor="",
    q="",
    status="",
    purpose="",
    basis="current",
    zone="",
    now=None,
):
    if status and status not in STATES:
        raise ValueError("未知证书状态")
    if purpose and purpose not in PURPOSES:
        raise ValueError("未知证书用途")
    now = now or datetime.now(UTC)
    signature = hashlib.sha256(
        json.dumps([q, status, purpose, basis, zone, limit]).encode()
    ).hexdigest()
    offset = 0
    if cursor:
        try:
            decoded = json.loads(base64.urlsafe_b64decode(cursor))
            offset = int(decoded["offset"])
            if decoded["signature"] != signature or not 0 <= offset <= 10000000:
                raise ValueError()
            now = datetime.fromisoformat(decoded["checkedAt"])
            if now.tzinfo is None:
                raise ValueError()
        except Exception as exc:
            raise ValueError("分页游标无效或筛选条件已改变") from exc
    reference, message = reference_time(bundle, basis, zone, now)
    timestamp = reference.timestamp() if reference else None
    # CASE and filters execute in SQLite; complete certificate payloads are never loaded as a list.
    state_sql = """CASE WHEN json_extract(payload,'$.parseState')<>'ok' OR ? IS NULL THEN 'unknown'
      WHEN json_extract(payload,'$.notBeforeEpoch')>? THEN 'notYetValid'
      WHEN json_extract(payload,'$.notAfterEpoch')<=? THEN 'expired'
      WHEN json_extract(payload,'$.notAfterEpoch')<=? THEN 'expiring' ELSE 'valid' END"""
    cte = f"WITH certs AS (SELECT *,{state_sql} validity FROM items WHERE kind='certificates') "
    params = [
        timestamp,
        timestamp,
        timestamp,
        timestamp + 90 * 86400 if timestamp is not None else None,
    ]
    where = ["1=1"]
    filters = []
    if q:
        where.append("instr(lower(payload),?)>0")
        filters.append(q.lower())
    if purpose:
        where.append("json_extract(payload,'$.purpose')=?")
        filters.append(purpose)
    if status:
        where.append("validity=?")
        filters.append(status)
    with bundle.connection() as conn:
        counts = {s: 0 for s in STATES}
        counts.update(
            {
                r["validity"]: r["n"]
                for r in conn.execute(
                    cte + "SELECT validity,count(*) n FROM certs GROUP BY validity",
                    params,
                )
            }
        )
        total = conn.execute(
            cte + "SELECT count(*) FROM certs WHERE " + " AND ".join(where),
            params + filters,
        ).fetchone()[0]
        order = "CASE validity WHEN 'expired' THEN 0 WHEN 'expiring' THEN 1 WHEN 'notYetValid' THEN 2 WHEN 'unknown' THEN 3 ELSE 4 END,json_extract(payload,'$.notAfterEpoch'),name,key"
        rows = []
        for row in conn.execute(
            cte
            + "SELECT payload,validity FROM certs WHERE "
            + " AND ".join(where)
            + " ORDER BY "
            + order
            + " LIMIT ? OFFSET ?",
            params + filters + [limit, offset],
        ):
            item = json.loads(row["payload"])
            item["validity"] = row["validity"]
            after = item.get("notAfterEpoch")
            item["remainingDays"] = (
                math.floor((after - timestamp) / 86400)
                if after is not None and timestamp is not None
                else None
            )
            rows.append(item)

    def token(at):
        return base64.urlsafe_b64encode(
            json.dumps(
                {"offset": at, "signature": signature, "checkedAt": now.isoformat()}
            ).encode()
        ).decode()

    return {
        "items": rows,
        "total": total,
        "nextCursor": token(offset + len(rows)) if offset + len(rows) < total else None,
        "previousCursor": token(max(0, offset - limit)) if offset else None,
        "counts": counts,
        "checkedAt": now.isoformat(),
        "referenceTime": reference.isoformat() if reference else None,
        "referenceMessage": message,
        "basis": basis,
        "collectedTime": bundle.header.get("generated", "未知"),
        "warningDays": 90,
    }
