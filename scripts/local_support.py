"""Local locks, optional profile access and measured tool work; no cloud calls."""
from __future__ import annotations

from contextvars import ContextVar
import functools
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time

METRICS = ContextVar('media_metrics', default=None)


def count(name, seconds=0.0):
    metrics = METRICS.get()
    if metrics is not None:
        metrics[name + '_calls'] = metrics.get(name + '_calls', 0) + 1
        metrics[name + '_seconds'] = metrics.get(name + '_seconds', 0.0) + seconds


def measured(stage):
    def decorate(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            metrics = {}; token = METRICS.set(metrics); started = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                timing = {'stage': stage, 'elapsed_seconds': round(time.perf_counter()-started, 6),
                          **{k: round(v, 6) if isinstance(v, float) else v for k, v in metrics.items()}}
                result['timing'] = timing
                output = Path(args[1] if len(args) > 1 else kwargs['output']).expanduser().absolute()
                log = output / '.run-times.jsonl'
                if log.is_symlink(): raise ValueError('耗时记录不能是符号链接')
                with log.open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(timing, ensure_ascii=False)+'\n')
                return result
            finally:
                METRICS.reset(token)
        return wrapper
    return decorate


def file_state(path):
    stat = Path(path).stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def unchanged(path, expected):
    if file_state(path) != expected:
        raise ValueError('处理期间文件发生变化：'+Path(path).name)


class LocalLock:
    """OS advisory lock releases on exit/crash. Preserve file to avoid inode races."""
    def __init__(self, path): self.path = Path(path); self.stream = None
    def __enter__(self):
        if self.path.is_symlink(): raise ValueError('运行锁不能为符号链接')
        self.stream = self.path.open('a+', encoding='utf-8')
        self.stream.seek(0); previous = self.stream.read().strip()
        if previous.isdigit():
            if os.name == 'nt':
                self.stream.close(); raise ValueError('发现旧版运行锁；确认旧进程结束后再移走该锁文件。')
            try: os.kill(int(previous), 0)
            except ProcessLookupError: pass
            except PermissionError:
                self.stream.close(); raise ValueError('无法确认旧版转写进程，保留运行锁。')
            else:
                self.stream.close(); raise ValueError('旧版转写进程仍存在，不能同时运行。')
        try:
            if os.name == 'nt':
                import msvcrt
                self.stream.seek(0)
                if not previous: self.stream.write(' '); self.stream.flush(); self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close(); raise ValueError('该任务正在另一个进程中运行，请稍后继续。') from None
        self.stream.seek(0); self.stream.truncate()
        self.stream.write(json.dumps({'lock_version': 2, 'pid': os.getpid()})); self.stream.flush()
        return self
    def __exit__(self, *args):
        if os.name == 'nt':
            import msvcrt
            self.stream.seek(0); msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        self.stream.close()


def profile_core():
    path = Path(__file__).resolve().parents[1] / '.livestream-core/scripts/personal_profile.py'
    spec = importlib.util.spec_from_file_location('_media_profile_core', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def profile_terms(directory):
    if Path(directory).expanduser().absolute().is_symlink():raise ValueError('请指定实际个人资料目录')
    location = Path(directory).expanduser().resolve()
    skill = Path(__file__).resolve().parents[1]
    if location.is_relative_to(skill) or skill.is_relative_to(location):
        raise ValueError('个人资料应放在技能安装目录之外')
    core = profile_core(); core.inspect_profile(location)
    rows = core.confirmed_rows((location/'01_专用词库.md').read_text(encoding='utf-8-sig'))
    return [line.split('|')[1].strip() for line in rows]
