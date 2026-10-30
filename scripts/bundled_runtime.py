"""Locate an optional, platform-specific offline runtime without downloading anything."""
from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import platform
import sys

ROOT = Path(__file__).resolve().parents[1]


def runtime_root(root: Path | None = None) -> Path:
    root=(root or ROOT).resolve()
    pointer=root/'.runtime-path'
    if pointer.exists():
        if pointer.is_symlink():raise ValueError('运行环境指针不能是链接')
        selected=Path(pointer.read_text(encoding='utf-8').strip())
        if not selected.is_absolute() or selected.is_symlink():raise ValueError('运行环境位置无效')
        if not (selected/'runtime/runtime.json').is_file():raise ValueError('共用转写环境不完整，请重新运行setup')
        return selected.resolve()
    return root


def target_platform() -> str:
    machine = platform.machine().lower()
    if sys.platform == 'darwin':
        return 'macos-arm64' if machine in {'arm64', 'aarch64'} else 'macos-x64'
    if sys.platform == 'win32' and machine in {'amd64', 'x86_64'}:
        return 'windows-x64'
    return sys.platform + '-' + machine


def runtime_info(root: Path | None = None) -> dict | None:
    root = runtime_root(root)
    path = root / 'runtime/runtime.json'
    if not path.exists():
        return None
    if path.is_symlink():
        raise ValueError('内置转写配置不能是符号链接')
    info = json.loads(path.read_text(encoding='utf-8'))
    if info.get('schema_version') != 1 or info.get('target') != target_platform():
        raise ValueError('完整包与当前电脑不匹配；请下载对应 Windows／Mac 芯片的包')
    return info


def resource(relative: str, root: Path | None = None) -> Path:
    root = runtime_root(root)
    rel = PurePosixPath(relative)
    if rel.is_absolute() or '..' in rel.parts or '\\' in relative or not rel.parts or rel.parts[0] != 'runtime':
        raise ValueError('内置转写资源路径无效')
    path = root / rel
    if not path.exists() and relative.startswith('runtime/models/') and (root/'.models-path').is_file():
        pointer=root/'.models-path'
        if pointer.is_symlink():raise ValueError('模型指针不能是链接')
        model_root=Path(pointer.read_text(encoding='utf-8').strip())
        if not model_root.is_absolute() or model_root.is_symlink():raise ValueError('模型位置无效')
        root=model_root.resolve();path=root/rel
    if any((root / Path(*rel.parts[:i])).is_symlink() for i in range(1, len(rel.parts) + 1)):
        raise ValueError('内置转写资源不能经过符号链接')
    if not path.is_file():
        raise ValueError('完整包缺少文件：' + relative + '；请重新解压完整包')
    return path


def bundled_tool(name: str, root: Path | None = None) -> Path | None:
    info = runtime_info(root)
    if info is None:
        return None
    relative = info.get('tools', {}).get(name)
    if relative is None:
        return None
    return resource(relative, root)


def bundled_model(root: Path | None = None) -> Path | None:
    info = runtime_info(root)
    return resource(info['model'], root) if info else None


def prepare_environment(root: Path | None = None) -> None:
    root = runtime_root(root)
    info = runtime_info(root)
    if not info:
        return
    vendor = str(root / 'runtime/vendor')
    if vendor not in sys.path:
        sys.path.insert(0, vendor)
    os.environ['PYTHONPATH'] = vendor
    os.environ['PYTHONUTF8'] = '1'
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    private=[str(root/'runtime/bin'),str(resource(info['python'],root).parent)]
    existing=os.environ.get('PATH','').split(os.pathsep)
    os.environ['PATH']=os.pathsep.join(private+[p for p in existing if p not in private])
    # This affects this process and its children, never the computer's global
    # settings. It also lets the preserved core find the included FFmpeg.

