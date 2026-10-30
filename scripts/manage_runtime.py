"""Transactional per-user runtime setup. Only downloads public software/models."""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
import sys

from bundled_runtime import target_platform, prepare_environment, bundled_model
from local_support import LocalLock


def digest(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def verify(root):
    manifest=root/'PACKAGE-MANIFEST.json'
    if manifest.is_symlink():raise ValueError('组件清单不能是链接')
    meta=json.loads(manifest.read_text(encoding='utf-8'))
    if meta.get('name')!='media-editor-component' or meta.get('schema_version')!=1 or not meta.get('files'):raise ValueError('组件清单无效')
    for name,expected in meta['files'].items():
        rel=PurePosixPath(name)
        if rel.is_absolute() or '..' in rel.parts or '\\' in name or not name.startswith('runtime/'):raise ValueError('组件路径无效')
        if any((root/Path(*rel.parts[:i])).is_symlink() for i in range(1,len(rel.parts)+1)):raise ValueError('组件不能包含链接')
        if digest(root/rel)!=expected:raise ValueError('组件文件校验失败：'+name)
    for name in meta.get('executable_files',[]):
        if name not in meta['files']:raise ValueError('执行清单无效')
        (root/name).chmod(0o755)
    return meta


def fetch(item, directory, base_url):
    print('准备公开组件：'+item['name']+'（可续传，不上传媒体）',file=sys.stderr,flush=True)
    name=item['name']
    if Path(name).name!=name or not name.endswith('.zip'):raise ValueError('组件文件名无效')
    target=directory/name;part=directory/(name+'.part');directory.mkdir(parents=True,exist_ok=True)
    if target.exists():
        if digest(target)!=item['sha256']:raise ValueError('已有下载不匹配，保留现场：'+name)
        return target
    offset=part.stat().st_size if part.exists() else 0
    if offset==item['bytes'] and digest(part)==item['sha256']:
        part.rename(target);return target
    request=urllib.request.Request(base_url.rstrip('/')+'/'+name,headers={'Range':f'bytes={offset}-'} if offset else {})
    with urllib.request.urlopen(request,timeout=60) as response:
        resumed=offset and response.status==206
        if resumed and not response.headers.get('Content-Range','').startswith(f'bytes {offset}-'):raise ValueError('续传偏移不匹配')
        with part.open('ab' if resumed else 'wb') as out:shutil.copyfileobj(response,out)
    if part.stat().st_size!=item['bytes'] or digest(part)!=item['sha256']:raise ValueError('组件下载校验失败；未切换现有环境')
    part.rename(target);return target


def component(item, kind, cache, base_url, source=None):
    if len(item['sha256'])!=64 or any(c not in '0123456789abcdef' for c in item['sha256']):raise ValueError('组件哈希无效')
    parent=cache/kind/item['sha256'];root=parent/'media-editor'
    if root.exists():verify(root);return root
    parent.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.component-',dir=parent.parent) as tmp:
        stage=Path(tmp)
        if source:shutil.copytree(source,stage/'media-editor')
        else:
            archive=fetch(item,cache/'downloads'/item['sha256'],base_url)
            with zipfile.ZipFile(archive) as z:
                for info in z.infolist():
                    rel=PurePosixPath(info.filename)
                    if rel.is_absolute() or '..' in rel.parts or '\\' in info.filename or not info.filename.startswith('media-editor/'):raise ValueError('组件归档路径无效')
                    if (info.external_attr>>16)&0o170000==0o120000:raise ValueError('组件归档不能含链接')
                z.extractall(stage)
        verify(stage/'media-editor')
        stage.rename(parent)
    return root


def setup(skill, catalog_path, cache, base_url, runtime_source=None):
    data=json.loads(catalog_path.read_text(encoding='utf-8'))
    if data.get('schema_version')!=1 or data.get('target')!=target_platform():raise ValueError('组件与电脑系统不匹配')
    if data.get('version')!=(skill/'VERSION').read_text().strip():raise ValueError('组件与Skill版本不匹配')
    cache=cache.expanduser().resolve();cache.mkdir(parents=True,exist_ok=True)
    if cache.is_relative_to(skill.resolve()) or skill.resolve().is_relative_to(cache):raise ValueError('环境目录必须与Skill分开')
    with LocalLock(cache/'.setup.lock'):
        runtime=component(data['runtime'],'programs',cache,base_url,runtime_source)
        models=component(data['models'],'models',cache,base_url)
        (runtime/'.models-path').write_text(str(models),encoding='utf-8')
        prepare_environment(runtime);bundled_model(runtime)
        for name in ('ffmpeg','ffprobe','whisper-cli'):
            from bundled_runtime import bundled_tool
            subprocess.run([str(bundled_tool(name,runtime)),'--version' if name=='whisper-cli' else '-version'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
        pointer=skill/'.runtime-path'
        if pointer.is_symlink():raise ValueError('运行环境指针不能是链接')
        previous=pointer.read_text() if pointer.exists() else None
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=skill,delete=False) as f:f.write(str(runtime));temp=Path(f.name)
        temp.replace(pointer)
        saved=cache/'catalogs'/data['version']/(data['target']+'.json');saved.parent.mkdir(parents=True,exist_ok=True)
        saved.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return {'status':'ready','runtime':str(runtime),'models':str(models),'previous_runtime':previous,'media_uploaded':False}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--catalog',type=Path,required=True);p.add_argument('--cache',type=Path,required=True)
    p.add_argument('--base-url',required=True);p.add_argument('--runtime-source',type=Path);a=p.parse_args()
    print(json.dumps(setup(Path(__file__).resolve().parents[1],a.catalog,a.cache,a.base_url,a.runtime_source),ensure_ascii=False,indent=2))
