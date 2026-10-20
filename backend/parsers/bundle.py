"""Read-only parsers for Rancher collector output; no service state."""
from collections import Counter
from pathlib import Path
import hashlib
import json
import re

PAGE_BYTES = 2 * 1024 * 1024


def table(text):
    """Parse aligned kubectl wide tables without splitting spaces within cells."""
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if not lines or 'No resources found' in lines[0]:
        return {'columns': [], 'rows': [], 'message': lines[0] if lines else '未收集或文件为空'}
    columns = re.split(r'\s{2,}', lines[0].strip())
    if len(columns) < 2:
        return {'columns': [], 'rows': [], 'message': '此文件不是可识别的资源表，请查看原文'}
    rows = [re.split(r'\s{2,}', line.strip(), maxsplit=len(columns)-1) for line in lines[1:]]
    return {'columns': columns, 'rows': [dict(zip(columns, row)) for row in rows if len(row) == len(columns)],
            'skipped': sum(len(row) != len(columns) for row in rows)}


class Bundle:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.paths = {}
        self.files = []
        for path in sorted(self.root.rglob('*')):
            if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(self.root):
                key = path.relative_to(self.root).as_posix()
                self.paths[key] = path
                self.files.append({'path': key, 'size': path.stat().st_size, 'id': hashlib.sha256(key.encode()).hexdigest()[:24], 'category': key.split('/')[0] if '/' in key else '采集元数据'})
        self.file_ids = {f['id']: f['path'] for f in self.files}
        self.distro = next((d for d in ('rke2', 'k3s', 'rke', 'kubeadm') if (self.root / d).is_dir()), '')
        self.warnings = []
        self.resources = {}
        kubectl = self.root / self.distro / 'kubectl'
        budget = 16 * 1024 * 1024
        if self.distro and kubectl.is_dir():
            for path in sorted(kubectl.iterdir()):
                if path.is_file() and path.relative_to(self.root).as_posix() in self.paths and path.suffix != '.json':
                    key = path.relative_to(self.root).as_posix()
                    limit = min(256 * 1024, budget)
                    if path.stat().st_size > limit:
                        self.warnings.append(f'{key} 超过结构化预览预算，请查看原文。')
                    text = self.read(key, limit)
                    budget -= len(text.encode('utf-8', errors='replace'))
                    budget = max(0, budget)
                    self.resources[path.name] = {**table(text), 'source': key}
        self.load_pods_json()
        self.summary = self.build_summary()

    def load_pods_json(self):
        key = f'{self.distro}/kubectl/pods.json'
        if key not in self.paths:
            return
        try:
            data = json.loads(self.read(key))
            rows = []
            for item in data['items']:
                meta, spec, status = item['metadata'], item.get('spec', {}), item.get('status', {})
                containers = status.get('containerStatuses', [])
                phase = status.get('phase', 'Unknown')
                if phase == 'Succeeded':
                    phase = 'Completed'
                reasons = [c.get('state', {}).get('waiting', {}).get('reason') for c in containers]
                phase = next((r for r in reasons if r), phase)
                rows.append({'NAME': meta['name'], 'NAMESPACE': meta.get('namespace', 'default'),
                    'READY': f"{sum(bool(c.get('ready')) for c in containers)}/{len(spec.get('containers', []))}",
                    'STATUS': phase, 'RESTARTS': str(sum(c.get('restartCount', 0) for c in containers + status.get('initContainerStatuses', []))),
                    'AGE': '—', 'IP': status.get('podIP', '未知'), 'NODE': spec.get('nodeName', '未调度')})
            self.resources['pods'] = {'columns': ['NAMESPACE', 'NAME', 'READY', 'STATUS', 'RESTARTS', 'AGE', 'IP', 'NODE'], 'rows': rows, 'source': key}
        except (ValueError, KeyError, TypeError, AttributeError):
            self.warnings.append('pods.json 无法解析，已回退到 Pod 文本表。')

    def read(self, key, limit=PAGE_BYTES):
        path = self.paths.get(key)
        if path is None:
            return ''
        with path.open('rb') as stream:
            return stream.read(limit).decode('utf-8', errors='replace')

    def build_summary(self):
        raw = self.read('summary.txt', 65536)
        def field(name):
            match = re.search(r'^' + re.escape(name) + r':[ \t]*(.*)$', raw, re.M)
            return match.group(1).strip() if match else '未知'
        nodes = []
        key = f'{self.distro}/kubectl/nodes.json'
        try:
            node_data = json.loads(self.read(key)) if key in self.paths else None
            if node_data is not None:
                for n in node_data.get('items', []):
                    meta, s = n.get('metadata', {}), n.get('status', {})
                    nodes.append({'name': meta.get('name', '未知'), 'roles': ', '.join(k.split('/')[-1] for k in meta.get('labels', {}) if k.startswith('node-role.kubernetes.io/')) or 'worker',
                                  'ip': next((a['address'] for a in s.get('addresses', []) if a['type'] == 'InternalIP'), '未知'),
                                  'ready': next((c['status'] for c in s.get('conditions', []) if c['type'] == 'Ready'), 'Unknown'),
                                  'conditions': s.get('conditions', []), 'capacity': s.get('capacity', {}), 'allocatable': s.get('allocatable', {}), **s.get('nodeInfo', {})})
        except (ValueError, KeyError, TypeError, AttributeError):
            self.warnings.append('nodes.json 无法解析，已回退到节点文本表。')
        if not nodes:
            for n in self.resources.get('nodes', {}).get('rows', []):
                nodes.append({'name': n.get('NAME'), 'roles': n.get('ROLES'), 'ip': n.get('INTERNAL-IP'), 'ready': 'True' if n.get('STATUS') == 'Ready' else 'Unknown', 'capacity': {}, 'conditions': [], 'kubeletVersion': n.get('VERSION'), 'osImage': n.get('OS-IMAGE')})
        pods = self.resources.get('pods', {}).get('rows', [])
        if not pods:
            self.warnings.append('Pod 清单缺失、为空或无法解析，不能据此判断集群健康。')
        for p in pods:
            p['restartCount'] = int(re.match(r'\d+', p.get('RESTARTS', '0')).group()) if re.match(r'\d+', p.get('RESTARTS', '0')) else 0
            p['attention'] = p.get('STATUS') not in ('Running', 'Completed', 'Succeeded') or (p.get('STATUS') == 'Running' and not re.fullmatch(r'(\d+)/\1', p.get('READY', '')))
        os_match = re.search(r'PRETTY_NAME="(.*?)"', raw)
        version = re.search(r'(?:rke2|k3s) version (\S+)', self.read('versions', 65536))
        return {'name': self.root.name, 'hostname': field('Hostname'), 'generated': field('Generated'), 'kernel': field('Kernel'), 'distro': self.distro or field('Distro'),
                'os': os_match.group(1) if os_match else '未知', 'version': version.group(1) if version else '未知',
                'files': self.files, 'bytes': sum(f['size'] for f in self.files), 'nodes': nodes, 'pods': pods,
                'podStatus': dict(Counter(p.get('STATUS', 'Unknown') for p in pods)), 'namespaces': sorted({p.get('NAMESPACE', '') for p in pods}),
                'resources': [{'name': k, 'count': len(v['rows']), 'source': v['source']} for k, v in self.resources.items()],
                'system': {k: self.read('systeminfo/' + k, 8192) for k in ('freeh', 'dfh', 'uptime', 'lscpu')},
                'etcd': {k: self.read('etcd/' + k, 8192) for k in ('endpointhealth', 'endpointstatus', 'alarmlist', 'memberlist')}, 'warnings': self.warnings}

    def file_page(self, file_id, offset=0, query=''):
        key = self.file_ids.get(file_id)
        if key is None:
            raise FileNotFoundError(file_id)
        path = self.paths[key]
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise FileNotFoundError(key)
        size = path.stat().st_size
        offset = min(max(0, offset), size)
        lines, segments = [], []
        with path.open('rb') as stream:
            if b'\x00' in stream.read(8192):
                return {'path': key, 'binary': True, 'lines': [], 'segments': [], 'nextOffset': 0, 'hasMore': False, 'size': size, 'scannedBytes': 0}
            carry = ''
            context_bytes = 0
            if query and offset:
                stream.seek(max(0, offset - 2000))
                prefix = stream.read(offset - stream.tell())
                context_bytes = len(prefix)
                carry = prefix.decode('utf-8', errors='replace').rsplit('\n', 1)[-1][-500:]
            stream.seek(offset)
            start = stream.tell()
            while stream.tell() - start < PAGE_BYTES - context_bytes and len(lines) < 250:
                position = stream.tell()
                remaining = PAGE_BYTES - context_bytes - (position - start)
                raw = stream.readline(min(65536, remaining))
                if not raw:
                    break
                try:
                    raw.decode('utf-8')
                except UnicodeDecodeError as error:
                    if error.reason == 'unexpected end of data' and stream.tell() < size:
                        stream.seek(-(len(raw) - error.start), 1)
                        raw = raw[:error.start]
                        if not raw:
                            break
                text = raw.decode('utf-8', errors='replace').rstrip('\r\n')
                combined = carry + text
                needle = query.casefold()
                found = not query
                if query:
                    haystack = combined.casefold()
                    at = haystack.find(needle)
                    while at >= 0:
                        if at + len(needle) > len(carry.casefold()):
                            found = True
                            break
                        at = haystack.find(needle, at + 1)
                if found:
                    cross_boundary = bool(query and needle not in text.casefold())
                    lines.append(combined if cross_boundary else text)
                    segments.append({'offset': max(0, position - len(carry.encode('utf-8'))) if cross_boundary else position,
                                     'continued': not raw.endswith(b'\n') and stream.tell() < size})
                carry = combined[-500:] if not raw.endswith(b'\n') else ''
            end = stream.tell()
        return {'path': key, 'binary': False, 'lines': lines, 'segments': segments, 'offset': offset,
                'nextOffset': end, 'hasMore': end < size, 'size': size, 'scannedBytes': end-offset+context_bytes, 'query': query}


def discover(root):
    root = Path(root).resolve()
    return sorted({p.parent for p in list(root.rglob('collector-output.log')) + list(root.rglob('summary.txt')) if not p.is_symlink() and p.resolve().is_relative_to(root)})
