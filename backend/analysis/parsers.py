"""Small host snapshots; unrecognized output remains unknown, never healthy."""

import re
import math


def number(value):
    try:
        result = float(value.rstrip("%").replace(",", "."))
        return result if math.isfinite(result) else None
    except (ValueError, AttributeError):
        return None


def size(value):
    m = re.fullmatch(r"([\d.]+)([KMGTPE]?)(?:i?B?)", value, re.I)
    return (
        float(m[1]) * 1024 ** ("KMGTPE".index(m[2].upper()) + 1 if m and m[2] else 0)
        if m
        else None
    )


def memory(text):
    lines = [l.split() for l in text.splitlines() if l.strip()]
    header = next((l for l in lines if "available" in l), [])
    row = next((l for l in lines if l[0] == "Mem:"), [])
    swap = next((l for l in lines if l[0] == "Swap:"), [])
    result = {}
    if header and row:
        result = {k: size(v) for k, v in zip(header, row[1:])}
    if len(swap) >= 4:
        result.update(swapTotal=size(swap[1]), swapUsed=size(swap[3]))
    return result


def cpu(vmstat, top):
    rows, header = [], []
    for line in vmstat.splitlines():
        values = line.split()
        if "us" in values and "sy" in values and "id" in values:
            header = values
        elif header and len(values) >= len(header) and values and values[0].isdigit():
            row = dict(zip(header, values))
            idle, wait = number(row.get("id", "")), number(row.get("wa", ""))
            if (
                idle is not None
                and wait is not None
                and 0 <= idle <= 100
                and 0 <= wait <= 100
            ):
                rows.append((100 - idle, wait))
    # First vmstat record is since boot, even when it has a wall-clock timestamp.
    if len(rows) > 1:
        rows = rows[1:]
        return {
            "busy": sum(r[0] for r in rows) / len(rows),
            "iowait": sum(r[1] for r in rows) / len(rows),
            "samples": len(rows),
            "source": "systeminfo/vmstat",
            "note": "短时间隔样本均值；已排除首条启动以来平均值，非持续监控",
        }
    matches = list(re.finditer(r"%?Cpu\(s\):([^\n]+)", top, re.I))
    if matches:
        values = {
            label: float(n.replace(",", "."))
            for n, label in re.findall(
                r"([\d.,]+)\s+(us|sy|ni|id|wa|hi|si|st)\b", matches[-1][1]
            )
        }
        if "id" in values and "wa" in values:
            return {
                "busy": 100 - values["id"],
                "iowait": values["wa"],
                "samples": 1,
                "source": "systeminfo/top",
                "note": "top 最后一帧的单次快照，非持续监控",
            }
    return None


def disks(text):
    seen = {}
    for line in text.splitlines()[1:]:
        parts = line.split(None, 5)
        if len(parts) != 6 or not parts[4].endswith("%"):
            continue
        fs, total, used, available, percent, mount = parts
        if fs in (
            "tmpfs",
            "devtmpfs",
            "overlay",
            "shm",
            "udev",
            "none",
            "efivarfs",
        ) or fs.startswith("/dev/loop"):
            continue
        value = number(percent)
        if value is None or not 0 <= value <= 100:
            continue
        key = (fs, total, used, percent)
        if key not in seen:
            seen[key] = {
                "filesystem": fs,
                "total": total,
                "used": used,
                "percent": value,
                "mounts": [],
                "mountCount": 0,
            }
        seen[key]["mountCount"] += 1
        if len(seen[key]["mounts"]) < 5:
            seen[key]["mounts"].append(mount)
    return list(seen.values())


def processes(text):
    lines = text.splitlines()
    if not lines:
        return None
    header = lines[0].split()
    if "STAT" not in header or "PID" not in header:
        return None
    index = header.index("STAT")
    result = []
    for line in lines[1:]:
        row = line.split(None, len(header) - 1)
        if len(row) > index and row[index].startswith("Z"):
            result.append({"pid": row[header.index("PID")], "state": row[index]})
    return result


def units(text):
    result = {}
    for line in text.splitlines():
        row = line.lstrip(" *●").split(None, 4)
        if len(row) >= 4 and row[0].endswith((".service", ".timer")):
            result[row[0]] = {"load": row[1], "active": row[2], "sub": row[3]}
    return result


def sysctls(text):
    return dict(re.findall(r"(?m)^([\w.]+)\s*=\s*([^\n]+)", text))


def metrics(text):
    result = {}
    for line in text.splitlines():
        match = re.fullmatch(r"([a-zA-Z_:][\w:]*)\s+([-+\deE.]+)(?:\s+\d+)?", line)
        if match:
            try:
                result[match[1]] = float(match[2])
            except ValueError:
                pass
    return result


def pipe_table(text):
    result, header = [], []
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        row = [v.strip() for v in line.strip().strip("|").split("|")]
        if "ENDPOINT" in row:
            header = row
        elif header and len(row) == len(header):
            result.append(dict(zip(header, row)))
    return result
