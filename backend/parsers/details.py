"""Extract display fields from describe output while retaining exact source ranges."""

import re


def describe_blocks(path):
    with path.open("rb") as stream:
        start = None
        name = namespace = ""
        while True:
            offset = stream.tell()
            raw = stream.readline(65537)
            if not raw:
                if start is not None:
                    yield name, namespace, start, offset
                break
            if len(raw) > 65536:
                raise ValueError("Describe 存在过长行")
            if raw.startswith(b"Name:"):
                if start is not None:
                    yield name, namespace, start, offset
                name = raw.decode(errors="replace").split(":", 1)[1].strip()
                namespace = ""
                start = offset
            elif raw.startswith(b"Namespace:"):
                namespace = raw.decode(errors="replace").split(":", 1)[1].strip()


def parse_describe(text):
    fields, containers, sections = {}, [], {}
    section = ""
    container = None
    group = ""
    for line in text.splitlines():
        top = re.match(r"^([^ :][^:]*):\s*(.*)$", line)
        if top:
            section, value = top.groups()
            fields[section] = value
            sections.setdefault(section, [])
            container = None
            group = ""
            continue
        sections.setdefault(section, []).append(line)
        if section not in ("Containers", "Init Containers", "Ephemeral Containers"):
            continue
        header = re.match(r"^  (\S+):\s*$", line)
        if header:
            container = {
                "name": header.group(1),
                "type": section,
                "fields": {},
                "resources": {},
                "mounts": [],
            }
            containers.append(container)
            group = ""
            continue
        if container is None:
            continue
        field = re.match(r"^    ([^:]+):\s*(.*)$", line)
        if field:
            group, value = field.groups()
            container["fields"][group] = value
            continue
        if group in ("Limits", "Requests"):
            resource = re.match(r"^      ([^:]+):\s*(.*)$", line)
            if resource:
                container["resources"].setdefault(group, {})[resource.group(1)] = (
                    resource.group(2)
                )
        elif group == "Mounts" and line.startswith("      "):
            container["mounts"].append(line.strip())
    return {
        "fields": fields,
        "containers": containers,
        "sections": {k: "\n".join(v).strip() for k, v in sections.items() if v},
    }
