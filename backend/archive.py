"""Bounded streaming extraction. Never apply archive permissions or create links."""
from pathlib import Path, PurePosixPath
import tarfile
import gzip
import re

class ImportFailure(ValueError):
    pass

class Cancelled(ImportFailure):
    pass


class BoundedTarInfo(tarfile.TarInfo):
    def _proc_pax(self, archive):
        if self.size > 65536:
            raise ImportFailure('归档扩展元数据过大')
        return super()._proc_pax(archive)

    def _proc_gnulong(self, archive):
        if self.size > 65536:
            raise ImportFailure('归档扩展路径过长')
        return super()._proc_gnulong(archive)


class ExpandedStream:
    def __init__(self, stream, limit, cancelled):
        self.stream, self.limit, self.cancelled = stream, limit, cancelled
        self.count = 0

    def read(self, size):
        if self.cancelled.is_set():
            raise Cancelled('导入已取消')
        value = self.stream.read(size)
        self.count += len(value)
        if self.count > self.limit:
            raise ImportFailure('归档解压流大小超过限制')
        return value


def extract(archive, destination, settings, reserve, cancelled):
    total = count = 0
    seen = set()
    with gzip.open(archive, 'rb') as compressed:
        expanded = ExpandedStream(compressed, settings.unpack_limit + settings.max_files * 8192, cancelled)
        with tarfile.open(fileobj=expanded, mode='r|', tarinfo=BoundedTarInfo) as source:
            for member in source:
                if cancelled.is_set():
                    raise Cancelled('导入已取消')
                count += 1
                name = PurePosixPath(member.name)
                if count > settings.max_files:
                    raise ImportFailure('归档条目数量超过限制')
                if name.is_absolute() or '..' in name.parts or '\\' in member.name or any(re.match(r'^[A-Za-z]:', part) for part in name.parts) or len(name.parts) > settings.max_depth:
                    raise ImportFailure('归档含不安全路径或目录过深')
                if not (member.isdir() or member.isreg()) or member.issparse():
                    raise ImportFailure('归档含链接、特殊文件或稀疏文件')
                target = destination.joinpath(*name.parts)
                if not target.resolve().is_relative_to(destination.resolve()):
                    raise ImportFailure('归档路径超出采集目录')
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if name in seen or target.exists():
                    raise ImportFailure('归档含重复文件路径')
                seen.add(name)
                if member.size < 0 or total + member.size > settings.unpack_limit:
                    raise ImportFailure('单包解压大小超过限制')
                target.parent.mkdir(parents=True, exist_ok=True)
                stream = source.extractfile(member)
                if stream is None:
                    raise ImportFailure('归档文件不可读取')
                written = 0
                with stream, target.open('xb') as output:
                    while chunk := stream.read(1024 * 1024):
                        if cancelled.is_set():
                            raise Cancelled('导入已取消')
                        if total + len(chunk) > settings.unpack_limit:
                            raise ImportFailure('单包解压大小超过限制')
                        reserve(len(chunk))
                        output.write(chunk)
                        total += len(chunk)
                        written += len(chunk)
                if written != member.size:
                    raise ImportFailure('归档不完整')
        # Read the gzip trailer too, so truncated archives and CRC failures are rejected.
        while expanded.read(1024 * 1024):
            pass
    return total
