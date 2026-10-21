#!/usr/bin/env python3
"""Export the current ephemeral workspace before an upgrade; output must stay outside Git."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import urllib.request
from backup_helpers import select_backup_root

parser = argparse.ArgumentParser()
parser.add_argument("--context", required=True)
parser.add_argument("--base-url", required=True)
parser.add_argument("--output", default=".data/upgrade-backup")
args = parser.parse_args()
output = Path(args.output)
output.mkdir(parents=True, exist_ok=True)
command = [
    "kubectl",
    "--context",
    args.context,
    "--request-timeout=30s",
    "-n",
    "rancher-log-analyzer",
]
pod = json.loads(
    subprocess.check_output(
        command
        + [
            "get",
            "pods",
            "-l",
            "app.kubernetes.io/instance=rancher-log-analyzer",
            "-o",
            "json",
        ]
    )
)["items"][0]["metadata"]["name"]


def get(path):
    with urllib.request.urlopen(
        args.base_url.rstrip("/") + "/api/v1" + path, timeout=30
    ) as response:
        return json.load(response)


cases = get("/cases")
remote = """import json,hashlib; from pathlib import Path
roots=set()
for marker in ('collector-output.log','summary.txt'):
 for p in Path('/data/session').glob('*/files/**/'+marker):roots.add(p.parent)
result=[]
for root in sorted(roots):
 inventory=[];fingerprint=hashlib.sha256()
 for path in sorted(root.rglob('*')):
  if path.is_symlink():raise ValueError('Unexpected symlink in collected data')
  if not path.is_file():continue
  size=path.stat().st_size;relative=path.relative_to(root).as_posix();digest=hashlib.sha256()
  with path.open('rb') as stream:
   while chunk:=stream.read(1024*1024):digest.update(chunk)
  inventory.append([relative,size])
  fingerprint.update(json.dumps([relative,size,digest.hexdigest()],ensure_ascii=True).encode()+b'\\n')
 result.append({'name':root.name,'path':str(root),'inventory':inventory,'fingerprint':fingerprint.hexdigest()})
print(json.dumps(result))
"""
roots = json.loads(
    subprocess.check_output(command + ["exec", pod, "--", "python", "-c", remote])
)
manifest = {"createdAt": datetime.now().astimezone().isoformat(), "cases": []}
for case in cases:
    saved = {"name": case["name"], "bundles": []}
    for record in case["bundles"]:
        if record["state"] != "ready":
            raise SystemExit("Only ready bundles can be backed up safely")
        summary = get("/bundles/" + record["id"] + "/summary")
        try:
            matched = select_backup_root(roots, summary)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        archive = record["id"] + ".tar.gz"
        script = "import sys,tarfile; from pathlib import Path; p=Path(sys.argv[1]); t=tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz'); t.add(p,arcname=p.name); t.close()"
        with (output / archive).open("wb") as stream:
            subprocess.run(
                command + ["exec", pod, "--", "python", "-c", script, matched["path"]],
                stdout=stream,
                check=True,
            )
        saved["bundles"].append(
            {
                "name": record["name"],
                "archive": archive,
                "oldId": record["id"],
                "files": len(summary["files"]),
                "contentSha256": matched["fingerprint"],
            }
        )
    manifest["cases"].append(saved)
(output / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
)
print(
    f'Backed up {len(cases)} cases and {sum(len(c["bundles"]) for c in manifest["cases"])} bundles to {output}'
)
