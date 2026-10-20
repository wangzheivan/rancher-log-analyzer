from dataclasses import dataclass
import os
from pathlib import Path

GiB = 1024 ** 3

@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(os.environ.get('DATA_DIR', '/tmp/rancher-log-analyzer'))
    upload_limit: int = int(os.environ.get('MAX_UPLOAD_BYTES', GiB))
    unpack_limit: int = int(os.environ.get('MAX_UNPACK_BYTES', 5 * GiB))
    session_limit: int = int(os.environ.get('MAX_SESSION_BYTES', 10 * GiB))
    max_files: int = int(os.environ.get('MAX_ARCHIVE_FILES', 20000))
    max_depth: int = int(os.environ.get('MAX_ARCHIVE_DEPTH', 32))
    frontend_dir: Path = Path(os.environ.get('FRONTEND_DIR', 'frontend/dist'))
