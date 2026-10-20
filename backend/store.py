"""Single-process ephemeral workspace; all byte reservations are synchronized."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, RLock
import shutil
import tarfile
import uuid

from .archive import Cancelled, ImportFailure, extract
from .parsers.bundle import Bundle, discover


def new_id():
    return uuid.uuid4().hex


@dataclass
class Record:
    id: str
    case_id: str
    name: str
    folder: Path
    state: str = 'uploading'
    error: str = ''
    received: int = 0
    allocated: int = 0
    unpacked: int = 0
    cancelled: Event = field(default_factory=Event)
    bundle: Bundle | None = None

    def public(self):
        s = self.bundle.summary if self.bundle else {}
        return {'id': self.id, 'caseId': self.case_id, 'name': self.name, 'state': self.state,
                'error': self.error, 'receivedBytes': self.received, 'unpackedBytes': self.unpacked,
                'hostname': s.get('hostname'), 'generated': s.get('generated'), 'distro': s.get('distro')}


class Store:
    def __init__(self, settings):
        self.settings = settings
        # Only this dedicated child belongs to the application. Never clear data_dir itself.
        self.folder = settings.data_dir.resolve() / 'session'
        self.lock = RLock()
        self.cases = {}
        self.records = {}
        self.used = 0
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='bundle-import')

    def start(self):
        if self.folder.exists() or self.folder.is_symlink():
            if self.folder.is_symlink():
                self.folder.unlink()
            else:
                shutil.rmtree(self.folder)
        self.folder.mkdir(parents=True, mode=0o700)

    def close(self):
        with self.lock:
            for record in self.records.values():
                record.cancelled.set()
        self.pool.shutdown(wait=True)
        shutil.rmtree(self.folder, ignore_errors=True)

    def create_case(self, name):
        with self.lock:
            if len(self.cases) >= 100:
                raise ImportFailure('案例数量达到上限，请先删除不用的案例')
            case = {'id': new_id(), 'name': name, 'createdAt': datetime.now(timezone.utc).isoformat()}
            self.cases[case['id']] = case
            return case

    def case(self, case_id):
        if case_id not in self.cases:
            raise FileNotFoundError('案例不存在')
        return self.cases[case_id]

    def begin(self, case_id, name):
        with self.lock:
            self.case(case_id)
            if len(self.records) >= 100:
                raise ImportFailure('采集包数量达到上限')
            record = Record(new_id(), case_id, name, self.folder / new_id())
            record.folder.mkdir(mode=0o700)
            self.records[record.id] = record
            return record

    def reserve(self, record, count):
        with self.lock:
            if record.cancelled.is_set():
                raise Cancelled('导入已取消')
            if self.used + count > self.settings.session_limit:
                raise ImportFailure('会话累计数据超过限制，请删除采集包后重试')
            self.used += count
            record.allocated += count

    def cleanup(self, record):
        with self.lock:
            shutil.rmtree(record.folder, ignore_errors=True)
            self.used -= record.allocated
            record.allocated = 0
            record.bundle = None

    def fail(self, record, message):
        self.cleanup(record)
        with self.lock:
            record.state, record.error = 'failed', message

    def enqueue(self, record):
        with self.lock:
            if record.cancelled.is_set():
                self.cleanup(record)
                return
            record.state = 'queued'
            self.pool.submit(self.process, record)

    def process(self, record):
        try:
            if record.cancelled.is_set():
                raise Cancelled('导入已取消')
            record.state = 'extracting'
            destination = record.folder / 'files'
            destination.mkdir()
            record.unpacked = extract(record.folder / 'upload.tar.gz', destination, self.settings,
                                      lambda n: self.reserve(record, n), record.cancelled)
            record.state = 'parsing'
            roots = discover(destination)
            if len(roots) != 1:
                raise ImportFailure('未找到唯一采集根目录，请将各节点采集包分别上传')
            bundle = Bundle(roots[0])
            with self.lock:
                if record.cancelled.is_set():
                    raise Cancelled('导入已取消')
                (record.folder / 'upload.tar.gz').unlink()
                self.used -= record.received
                record.allocated -= record.received
                record.bundle = bundle
                record.state = 'ready'
        except ImportFailure as exc:
            self.fail(record, str(exc))
        except (OSError, tarfile.TarError, EOFError, ValueError, TypeError, AttributeError, RecursionError):
            self.fail(record, '采集包损坏、格式不支持或内容无法解析')
        except Exception:
            self.fail(record, '采集包处理失败，请检查文件格式与可用空间')

    def get(self, record_id, ready=False):
        with self.lock:
            record = self.records.get(record_id)
            if record is None or record.cancelled.is_set():
                raise FileNotFoundError('采集包不存在')
            if ready and record.state != 'ready':
                raise ImportFailure('采集包尚未就绪')
            return record

    def parsed(self, record_id):
        with self.lock:
            return self.get(record_id, ready=True).bundle

    def delete_bundle(self, record_id):
        with self.lock:
            record = self.get(record_id)
            record.cancelled.set()
            del self.records[record_id]
            # Active writer owns cleanup until it observes cancellation.
            if record.state in ('ready', 'failed'):
                self.cleanup(record)

    def delete_case(self, case_id):
        with self.lock:
            self.case(case_id)
            for record in list(self.records.values()):
                if record.case_id == case_id:
                    self.delete_bundle(record.id)
            del self.cases[case_id]
