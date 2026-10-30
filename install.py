#!/usr/bin/env python3
"""Verified install, idempotent re-run and explicit upgrade with a complete backup."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'scripts'))
from local_support import LocalLock


def file_hash(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):value.update(block)
    return value.hexdigest()


def executable_files(source, files):
    names=json.loads((source/'PACKAGE-MANIFEST.json').read_text(encoding='utf-8')).get('executable_files',[])
    if not isinstance(names,list) or any(not isinstance(n,str) or n not in files for n in names):
        raise ValueError('安装包执行权限清单无效')
    return set(names)


def checked_files(source):
    manifest = source/'PACKAGE-MANIFEST.json'
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError('请使用完整下载包，缺少安装清单。')
    meta = json.loads(manifest.read_text(encoding='utf-8')); files = meta.get('files')
    if meta.get('name') != 'media-editor' or not isinstance(files, dict) or not files:
        raise ValueError('安装包清单无效')
    for name, expected in files.items():
        if not isinstance(name, str) or not isinstance(expected, str): raise ValueError('清单无效')
        rel = PurePosixPath(name)
        if rel.is_absolute() or '..' in rel.parts or chr(92) in name or rel.as_posix()!=name:
            raise ValueError('安装包路径无效')
        path = source/rel
        if any((source/Path(*rel.parts[:i])).is_symlink() for i in range(1,len(rel.parts)+1)):
            raise ValueError('安装包包含符号链接')
        if not path.is_file() or file_hash(path)!=expected:
            raise ValueError('安装包文件校验失败：'+name)
    executable_files(source,files)
    if (source/'runtime/runtime.json').is_file() or (source/'.runtime-path').exists():
        from bundled_runtime import runtime_info
        runtime_info(source)
    return files


def backup_path(target, backup_dir=None):
    folder = (backup_dir or target.parent.parent/'skill-backups').expanduser().resolve()
    if folder.is_relative_to(target.parent) or target.is_relative_to(folder):
        raise ValueError('备份目录必须在技能扫描目录之外')
    folder.mkdir(parents=True, exist_ok=True)
    return folder/(target.name+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))


def install(source: Path, target: Path, *, upgrade=False, backup_dir=None) -> dict:
    source=source.resolve(); raw=target.expanduser().absolute()
    if raw.is_symlink(): raise ValueError('安装位置是符号链接，请确认实际位置')
    target=raw.resolve()
    if source==target or source.is_relative_to(target) or target.is_relative_to(source):
        raise ValueError('安装目录不能与解压目录互相包含')
    files=checked_files(source)
    executables=executable_files(source,files)
    target.parent.mkdir(parents=True,exist_ok=True)
    with LocalLock(target.parent/'.media-editor-install.lock'):
        if target.exists():
            if not target.is_dir(): raise FileExistsError('安装位置不是文件夹')
            present={p.relative_to(target).as_posix() for p in target.rglob('*')
                     if (p.is_file() or p.is_symlink()) and '__pycache__' not in p.relative_to(target).parts
                     and p.suffix!='.pyc' and p.name not in {'.DS_Store','.runtime-path'}}
            identical=present==set(files)|{'PACKAGE-MANIFEST.json'}
            identical=identical and not any(p.is_symlink() for p in target.rglob('*'))
            if (source/'.runtime-path').is_file():
                identical=identical and (target/'.runtime-path').is_file() and (target/'.runtime-path').read_bytes()==(source/'.runtime-path').read_bytes()
            if identical:
                identical=all(file_hash(target/name)==sha for name,sha in files.items())
                identical=identical and (target/'PACKAGE-MANIFEST.json').read_bytes()==(source/'PACKAGE-MANIFEST.json').read_bytes()
            if identical:
                for name in executables:(target/name).chmod(0o755)
                return {'target':str(target),'status':'unchanged','backup':None}
            if not upgrade: raise FileExistsError('已有不同版本或人工修改；请明确使用 --upgrade，旧版会完整备份。')
        backup=None
        if target.exists():
            backup=backup_path(target,backup_dir)
            if backup.is_relative_to(source) or source.is_relative_to(backup):raise ValueError('备份目录不能与下载目录互相包含')
        with tempfile.TemporaryDirectory(prefix='.media-editor-install-',dir=target.parent) as temp:
            stage=Path(temp)/'media-editor';stage.mkdir()
            for name,sha in files.items():
                out=stage/PurePosixPath(name);out.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(source/PurePosixPath(name),out)
                if name in executables:out.chmod(0o755)
                if file_hash(out)!=sha: raise ValueError('复制校验失败')
            shutil.copyfile(source/'PACKAGE-MANIFEST.json',stage/'PACKAGE-MANIFEST.json')
            if not (stage/'runtime').exists() and (source/'.runtime-path').is_file():
                if (source/'.runtime-path').is_symlink():raise ValueError('运行环境指针不能是链接')
                shutil.copyfile(source/'.runtime-path',stage/'.runtime-path')
            # A rules-only update must not remove a working transcription runtime.
            if target.exists() and not (stage/'runtime').exists() and not (stage/'.runtime-path').exists():
                if (target/'.runtime-path').is_file():
                    pointer=target/'.runtime-path'
                    if pointer.is_symlink():raise ValueError('运行环境指针不能是链接')
                    from bundled_runtime import runtime_info
                    runtime_info(target)
                    shutil.copyfile(pointer,stage/'.runtime-path')
                elif (target/'runtime').is_dir():
                    meta=json.loads((stage/'PACKAGE-MANIFEST.json').read_text(encoding='utf-8'))
                    old=json.loads((target/'PACKAGE-MANIFEST.json').read_text(encoding='utf-8'))
                    for name,sha in old['files'].items():
                        if name.startswith('runtime/'):
                            p=target/PurePosixPath(name)
                            if p.is_symlink() or file_hash(p)!=sha:raise ValueError('原运行环境已变更：'+name)
                    if any(p.is_symlink() for p in (target/'runtime').rglob('*')):raise ValueError('原运行环境包含链接')
                    shutil.copytree(target/'runtime',stage/'runtime')
                    for name,sha in old['files'].items():
                        if name.startswith('runtime/'):meta['files'][name]=sha
                    meta['executable_files']=sorted(set(meta.get('executable_files',[]))|{n for n in old.get('executable_files',[]) if n.startswith('runtime/')})
                    (stage/'PACKAGE-MANIFEST.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            if backup:shutil.move(str(target),str(backup))
            try: stage.rename(target)
            except Exception:
                if backup and not target.exists():shutil.move(str(backup),str(target))
                raise
        return {'target':str(target),'status':'upgraded' if backup else 'installed','backup':str(backup) if backup else None}


def restore(backup: Path, target: Path):
    if backup.expanduser().absolute().is_symlink() or target.expanduser().absolute().is_symlink(): raise ValueError('请使用实际备份及安装目录')
    backup=backup.expanduser().resolve();target=target.expanduser().resolve()
    if not (backup/'SKILL.md').is_file() or backup==target or backup.is_relative_to(target) or target.is_relative_to(backup):
        raise ValueError('备份目录无效或与目标重叠')
    if backup.is_relative_to(target.parent):raise ValueError('备份须在技能扫描目录之外')
    if target.exists() and not target.is_dir():raise ValueError('恢复目标不是安装文件夹，原文件保留')
    target.parent.mkdir(parents=True,exist_ok=True)
    with LocalLock(target.parent/'.media-editor-install.lock'):
        previous=backup_path(target) if target.exists() else None
        with tempfile.TemporaryDirectory(prefix='.restore-',dir=target.parent) as temp:
            stage=Path(temp)/'media-editor';shutil.copytree(backup,stage,symlinks=True)
            if previous:shutil.move(str(target),str(previous))
            try:stage.rename(target)
            except Exception:
                if previous and not target.exists():shutil.move(str(previous),str(target))
                raise
    return {'status':'restored','target':str(target),'previous_backup':str(previous) if previous else None}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='安装或备份升级文稿整理，原资料保留')
    parser.add_argument('--target',type=Path,default=Path.home()/'.agents/skills/media-editor')
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--upgrade',action='store_true');mode.add_argument('--restore',type=Path)
    parser.add_argument('--backup-dir',type=Path)
    args=parser.parse_args()
    try:
        result=restore(args.restore,args.target) if args.restore else install(ROOT,args.target,upgrade=args.upgrade,backup_dir=args.backup_dir)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        installed=Path(result.get('target',ROOT))
        if (installed/'runtime/runtime.json').is_file():
            print('文稿整理及内置转写文件已安装；请运行包内启动器 doctor --task local-asr 检查本机可用性。')
        else:
            print('文稿整理 Skill 已安装。本包未包含转写程序与语音模型；只有音视频时需另配环境，或下载对应系统的转写完整包。')
    except (OSError,ValueError,TypeError) as exc:
        print('INSTALL=BLOCKED: '+str(exc));raise SystemExit(1)
