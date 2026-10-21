"""Read a bounded window in either direction; cursors are byte positions, not line counts."""

from collections import deque
from pathlib import Path
from types import SimpleNamespace
from .parsers.bundle import Bundle, PAGE_BYTES


def read_page(
    path, label, offset=0, query="", direction="forward", anchor="", end=None
):
    path = Path(path)
    size = path.stat().st_size
    with path.open("rb") as stream:
        prefix = stream.read(8192)
    if b"\0" in prefix or prefix.startswith(b"\x1f\x8b"):
        return {
            "path": label,
            "binary": True,
            "lines": [],
            "segments": [],
            "nextOffset": 0,
            "hasMore": False,
            "size": size,
            "scannedBytes": 0,
            "beforeCursor": None,
            "afterCursor": None,
            "message": "二进制或压缩源文件暂不支持直接展示。",
        }
    if direction not in ("forward", "backward") or anchor not in ("", "start", "end"):
        raise ValueError("日志读取方向无效")
    if direction == "forward" and anchor != "end":
        if anchor == "start":
            offset = 0
        source = SimpleNamespace(
            root=path.parent, paths={label: path}, file_ids={"file": label}
        )
        data = Bundle.file_page(source, "file", offset, query)
        data["beforeCursor"] = offset if offset > 0 else None
        data["afterCursor"] = data["nextOffset"] if data["hasMore"] else None
        return data
    stop = size if anchor == "end" or end is None else min(max(0, end), size)
    start = max(0, stop - PAGE_BYTES)
    lines = deque(maxlen=250)
    with path.open("rb") as stream:
        stream.seek(start)
        carry = ""
        while stream.tell() < stop:
            position = stream.tell()
            raw = stream.readline(min(65536, stop - position))
            if not raw:
                break
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError as error:
                if error.reason == "unexpected end of data" and stream.tell() < stop:
                    stream.seek(-(len(raw) - error.start), 1)
                    raw = raw[: error.start]
                    if not raw:
                        break
            text = raw.decode(errors="replace").rstrip("\r\n")
            combined = carry + text
            needle = query.casefold()
            haystack = combined.casefold()
            at = haystack.find(needle) if query else 0
            found = not query
            while query and at >= 0:
                if at + len(needle) > len(carry.casefold()):
                    found = True
                    break
                at = haystack.find(needle, at + 1)
            if found:
                crossed = bool(query and needle not in text.casefold())
                lines.append(
                    (
                        combined if crossed else text,
                        {
                            "offset": (
                                max(0, position - len(carry.encode()))
                                if crossed
                                else position
                            ),
                            "continued": not raw.endswith(b"\n")
                            and stream.tell() < size,
                        },
                        stream.tell(),
                    )
                )
            carry = combined[-500:] if not raw.endswith(b"\n") else ""
        scanned = stream.tell() - start
    before = (
        lines[0][1]["offset"]
        if lines
        else (
            min(stop - 1, start + len(query.encode("utf-8")))
            if query and start > 0
            else start
        )
    )
    after = stop
    return {
        "path": label,
        "binary": False,
        "lines": [x[0] for x in lines],
        "segments": [x[1] for x in lines],
        "offset": start,
        "nextOffset": after,
        "hasMore": after < size,
        "size": size,
        "scannedBytes": scanned,
        "beforeCursor": before if before > 0 else None,
        "afterCursor": after if after < size else None,
        "windowLimited": start > 0,
        "query": query,
    }
