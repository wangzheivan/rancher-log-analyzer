from dataclasses import dataclass
import os
from pathlib import Path

GiB = 1024**3


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(os.environ.get("DATA_DIR", "/tmp/rancher-log-analyzer"))
    upload_limit: int = int(os.environ.get("MAX_UPLOAD_BYTES", GiB))
    unpack_limit: int = int(os.environ.get("MAX_UNPACK_BYTES", 5 * GiB))
    session_limit: int = int(os.environ.get("MAX_SESSION_BYTES", 10 * GiB))
    max_files: int = int(os.environ.get("MAX_ARCHIVE_FILES", 20000))
    max_depth: int = int(os.environ.get("MAX_ARCHIVE_DEPTH", 32))
    frontend_dir: Path = Path(os.environ.get("FRONTEND_DIR", "frontend/dist"))
    index_limit: int = int(os.environ.get("MAX_INDEX_BYTES", 128 * 1024 * 1024))
    classification_rules: str = os.environ.get("LOG_CLASSIFICATION_RULES", "[]")

    analysis_limit: int = int(os.environ.get("MAX_ANALYSIS_BYTES", 32 * 1024 * 1024))
    analysis_scan_bytes: int = int(
        os.environ.get("ANALYSIS_SCAN_BYTES", 128 * 1024 * 1024)
    )
    analysis_scan_files: int = int(os.environ.get("ANALYSIS_SCAN_FILES", 200))
    analysis_file_bytes: int = int(
        os.environ.get("ANALYSIS_FILE_BYTES", 8 * 1024 * 1024)
    )
    analysis_thresholds: str = os.environ.get("ANALYSIS_THRESHOLDS", "{}")
