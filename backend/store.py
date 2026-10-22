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
from .parsers.bundle import discover
from .catalog import IndexedBundle


def new_id():
    return uuid.uuid4().hex


@dataclass
class Record:
    id: str
    case_id: str
    name: str
    folder: Path
    state: str = "uploading"
    error: str = ""
    received: int = 0
    allocated: int = 0
    unpacked: int = 0
    cancelled: Event = field(default_factory=Event)
    bundle: IndexedBundle | None = None
    analysis: object = None
    analysis_busy: bool = False
    analysis_done: Event = field(default_factory=Event)
    analysis_error: str = ""

    def public(self):
        s = self.bundle.header if self.bundle else {}
        return {
            "id": self.id,
            "caseId": self.case_id,
            "name": self.name,
            "state": self.state,
            "error": self.error,
            "receivedBytes": self.received,
            "unpackedBytes": self.unpacked,
            "indexBytes": self.bundle.index_bytes if self.bundle else 0,
            "hostname": s.get("hostname"),
            "generated": s.get("generated"),
            "distro": s.get("distro"),
        }


class Store:
    def __init__(self, settings):
        self.settings = settings
        # Only this dedicated child belongs to the application. Never clear data_dir itself.
        self.folder = settings.data_dir.resolve() / "session"
        self.lock = RLock()
        self.cases = {}
        self.records = {}
        self.used = 0
        self.closing = False
        self.pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="bundle-import"
        )

    def start(self):
        if self.folder.exists() or self.folder.is_symlink():
            if self.folder.is_symlink():
                self.folder.unlink()
            else:
                shutil.rmtree(self.folder)
        self.folder.mkdir(parents=True, mode=0o700)

    def close(self):
        with self.lock:
            self.closing = True
            for record in self.records.values():
                record.cancelled.set()
        self.pool.shutdown(wait=True)
        shutil.rmtree(self.folder, ignore_errors=True)

    def create_case(self, name):
        with self.lock:
            if len(self.cases) >= 100:
                raise ImportFailure("案例数量达到上限，请先删除不用的案例")
            case = {
                "id": new_id(),
                "name": name,
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
            self.cases[case["id"]] = case
            return case

    def case(self, case_id):
        if case_id not in self.cases:
            raise FileNotFoundError("案例不存在")
        return self.cases[case_id]

    def begin(self, case_id, name):
        with self.lock:
            self.case(case_id)
            if len(self.records) >= 100:
                raise ImportFailure("采集包数量达到上限")
            record = Record(new_id(), case_id, name, self.folder / new_id())
            record.folder.mkdir(mode=0o700)
            self.records[record.id] = record
            return record

    def reserve(self, record, count):
        with self.lock:
            if record.cancelled.is_set():
                raise Cancelled("导入已取消")
            if self.used + count > self.settings.session_limit:
                raise ImportFailure("会话累计数据超过限制，请删除采集包后重试")
            self.used += count
            record.allocated += count

    def cleanup(self, record):
        with self.lock:
            if record.analysis:
                with record.analysis.lock:
                    shutil.rmtree(record.folder, ignore_errors=True)
            else:
                shutil.rmtree(record.folder, ignore_errors=True)
            self.used -= record.allocated
            record.allocated = 0
            record.bundle = None

    def fail(self, record, message):
        self.cleanup(record)
        with self.lock:
            record.state, record.error = "failed", message

    def enqueue(self, record):
        with self.lock:
            if record.cancelled.is_set():
                self.cleanup(record)
                return
            record.state = "queued"
            self.pool.submit(self.process, record)

    def process(self, record):
        try:
            if record.cancelled.is_set():
                raise Cancelled("导入已取消")
            record.state = "extracting"
            destination = record.folder / "files"
            destination.mkdir()
            record.unpacked = extract(
                record.folder / "upload.tar.gz",
                destination,
                self.settings,
                lambda n: self.reserve(record, n),
                record.cancelled,
            )
            record.state = "parsing"
            roots = discover(destination)
            if len(roots) != 1:
                raise ImportFailure("未找到唯一采集根目录，请将各节点采集包分别上传")
            record.state = "indexing"
            self.reserve(record, self.settings.index_limit)
            bundle = IndexedBundle(
                roots[0],
                record.folder / "metadata.sqlite",
                self.settings.index_limit,
                self.settings.classification_rules,
                record.cancelled,
            )
            with self.lock:
                if record.cancelled.is_set():
                    raise Cancelled("导入已取消")
                (record.folder / "upload.tar.gz").unlink()
                released = (
                    record.received + self.settings.index_limit - bundle.index_bytes
                )
                self.used -= released
                record.allocated -= released
                record.bundle = bundle
                record.state = "ready"
            try:
                self.analysis_action(record.id, "continue")
            except Exception:
                record.analysis_error = "分析未能排队；采集信息仍可浏览。"
        except ImportFailure as exc:
            self.fail(record, str(exc))
        except (
            OSError,
            tarfile.TarError,
            EOFError,
            ValueError,
            TypeError,
            AttributeError,
            RecursionError,
        ):
            self.fail(record, "采集包损坏、格式不支持或内容无法解析")
        except Exception:
            self.fail(record, "采集包处理失败，请检查文件格式与可用空间")

    def get(self, record_id, ready=False):
        with self.lock:
            record = self.records.get(record_id)
            if record is None or record.cancelled.is_set():
                raise FileNotFoundError("采集包不存在")
            if ready and record.state != "ready":
                raise ImportFailure("采集包尚未就绪")
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
            wait_analysis = record.analysis_busy
            if record.state in ("ready", "failed") and not wait_analysis:
                self.cleanup(record)
        if wait_analysis:
            record.analysis_done.wait(timeout=5)

    def delete_case(self, case_id):
        with self.lock:
            self.case(case_id)
            ids = [r.id for r in self.records.values() if r.case_id == case_id]
            del self.cases[case_id]
        for record_id in ids:
            try:
                self.delete_bundle(record_id)
            except FileNotFoundError:
                pass

    def analysis_action(self, record_id, action):
        from .analysis.engine import Analysis

        with self.lock:
            record = self.get(record_id, ready=True)
            if action not in ("continue", "cancel", "restart"):
                raise ValueError("未知分析操作")
            if action == "cancel":
                if record.analysis:
                    record.analysis.cancelled.set()
                return self.analysis_status(record_id)
            if record.analysis_busy:
                return self.analysis_status(record_id)
            if record.analysis is None:
                try:
                    self.reserve(record, self.settings.analysis_limit)
                except ImportFailure as exc:
                    record.analysis_error = "分析未运行：" + str(exc)
                    return self.analysis_status(record_id)
                record.analysis = Analysis(
                    record.bundle,
                    record.folder / "analysis.sqlite",
                    self.settings,
                    record.cancelled,
                )
            elif action == "restart":
                # No analysis task is queued/running; the source bundle remains immutable.
                with record.analysis.lock:
                    record.analysis.path.unlink(missing_ok=True)
                    record.analysis.path.with_name("analysis.sqlite-journal").unlink(
                        missing_ok=True
                    )
                record.analysis = Analysis(
                    record.bundle,
                    record.folder / "analysis.sqlite",
                    self.settings,
                    record.cancelled,
                )
            elif record.analysis.state in ("complete", "failed"):
                return self.analysis_status(record_id)
            record.analysis.reset_round()
            record.analysis_done.clear()
            record.analysis_busy = True
            self.pool.submit(self.analysis_step, record)
            return self.analysis_status(record_id)

    def analysis_status(self, record_id):
        with self.lock:
            record = self.get(record_id, ready=True)
            if record.analysis:
                return record.analysis.status()
            return {
                "state": "blocked",
                "error": record.analysis_error or "分析尚未排队",
                "counts": {},
                "coverage": {},
                "canContinue": True,
            }

    def analysis_step(self, record):
        more = False
        try:
            if not record.cancelled.is_set() and not self.closing:
                more = record.analysis.step()
        except Cancelled:
            record.analysis.state = "cancelled"
        except Exception:
            record.analysis.state = "failed"
            record.analysis.error = "分析未完成；已提交结果保留，采集信息仍可浏览。"
            record.analysis.can_continue = False
        finally:
            with self.lock:
                if record.cancelled.is_set():
                    record.analysis_busy = False
                    self.cleanup(record)
                    record.analysis_done.set()
                elif more and not self.closing:
                    self.pool.submit(self.analysis_step, record)
                else:
                    record.analysis_busy = False
                    record.analysis_done.set()
