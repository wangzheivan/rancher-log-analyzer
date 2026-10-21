"""Bounded readers for large collector resource lists."""

import json
import re
import ijson


class JSONReader:
    """Reject oversized strings/records and excessive nesting before building objects."""

    def __init__(self, stream):
        self.stream = stream
        self.quoted = self.escaped = False
        self.depth = self.string_size = self.record_size = 0

    def read(self, size=-1):
        data = self.stream.read(size)
        for ch in data:
            if self.depth >= 3:
                self.record_size += 1
                if self.record_size > 4 * 1024 * 1024:
                    raise ValueError("单个 JSON 对象超过 4 MiB")
            if self.quoted:
                self.string_size += 1
                if self.string_size > 256 * 1024:
                    raise ValueError("JSON 字符串过长")
                if self.escaped:
                    self.escaped = False
                elif ch == 92:
                    self.escaped = True
                elif ch == 34:
                    self.quoted = False
            elif ch == 34:
                self.quoted = True
                self.string_size = 0
            elif ch in (91, 123):
                self.depth += 1
                if self.depth > 64:
                    raise ValueError("JSON 嵌套过深")
            elif ch in (93, 125):
                self.depth -= 1
                if self.depth < 3:
                    self.record_size = 0
        return data


def json_items(path):
    with path.open("rb") as stream:
        found = False
        for prefix, event, _ in ijson.parse(JSONReader(stream)):
            if prefix == "items" and event == "start_array":
                found = True
                break
        if not found:
            raise ValueError("缺少 Kubernetes items 数组")
    with path.open("rb") as stream:
        yield from ijson.items(JSONReader(stream), "items.item", use_float=True)


def text_rows(path):
    with path.open("rb") as stream:
        header = stream.readline(65537)
        if len(header) > 65536:
            raise ValueError("表头过长")
        title = header.decode("utf-8", errors="replace").strip()
        if not title or title.startswith("No resources found"):
            return
        columns = re.split(r"\s{2,}", title)
        if len(columns) < 2:
            raise ValueError("不是可识别的资源表")
        while line := stream.readline(65537):
            if len(line) > 65536:
                raise ValueError("资源行过长")
            if not line.strip():
                continue
            values = re.split(
                r"\s{2,}",
                line.decode("utf-8", errors="replace").strip(),
                maxsplit=len(columns) - 1,
            )
            if len(values) != len(columns):
                raise ValueError("资源表存在无法识别的行")
            yield columns, dict(zip(columns, values))


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
