#!/usr/bin/env python3
"""Exercise a relocated full bundle without borrowing globally installed tools."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()


def invoke(args, env, timeout=300):
    result=subprocess.run(list(map(str,args)),env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                          text=True,encoding='utf-8',errors='replace',timeout=timeout)
    if result.returncode:
        raise RuntimeError('运行失败：'+str(args[0])+'\n'+result.stdout[-3000:]+'\n'+result.stderr[-5000:])
    return result


def verify(archive, report):
    archive=archive.expanduser().resolve();started=time.perf_counter()
    env=dict(os.environ)
    for name in ('PYTHONHOME','PYTHONPATH','LD_LIBRARY_PATH','DYLD_LIBRARY_PATH'):
        env.pop(name,None)
    env['PATH']=str(Path(os.environ.get('SystemRoot','C:/Windows'))/'System32') if sys.platform=='win32' else '/usr/bin:/bin'
    env.update(PYTHONUTF8='1',PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1')
    with tempfile.TemporaryDirectory(prefix='media-offline-') as temporary:
        area=Path(temporary)
        with zipfile.ZipFile(archive) as z:
            for item in z.infolist():
                parts=Path(item.filename).parts
                if Path(item.filename).is_absolute() or '..' in parts:
                    raise ValueError('归档路径不安全')
            z.extractall(area/'download')
        source=area/'download/media-editor'
        manifest=json.loads((source/'PACKAGE-MANIFEST.json').read_text(encoding='utf-8'))
        for name,sha in manifest['files'].items():
            if digest(source/name)!=sha:raise ValueError('归档文件校验失败：'+name)
        for name in manifest.get('executable_files',[]):(source/name).chmod(0o755)
        info=json.loads((source/'runtime/runtime.json').read_text(encoding='utf-8'))
        source_launch=[str(source/'media-editor.cmd')] if sys.platform=='win32' else ['/bin/bash',str(source/'media-editor.command')]
        target=area/'验收 空格&目录/skills/media-editor'
        install=invoke([*source_launch,'install','--target',target],env)
        if not target.is_dir():raise ValueError('独立安装没有生成目标')
        python=target/info['python']
        installed_launch=[str(target/'media-editor.cmd')] if sys.platform=='win32' else ['/bin/bash',str(target/'media-editor.command')]
        doctor=invoke([*installed_launch,'doctor','--task','local-asr'],env)
        readiness=json.loads(doctor.stdout)
        if not readiness['ready'] or not readiness['bundled_runtime']:
            raise ValueError('完整包的本机转写检查未通过')
        ffmpeg=target/info['tools']['ffmpeg']
        media=area/'原始 录音&测试.m4a'
        sample=target/'assets/runtime-smoke-zh.wav'
        language='zh' if sample.is_file() else 'en'
        if not sample.is_file():sample=target/'runtime/samples/jfk.wav'
        invoke([ffmpeg,'-v','error','-i',sample,'-c:a','aac',media],env)
        original_hash=digest(media)
        output=area/'转写 输出'
        command=[*installed_launch,'transcribe',media,'--language',language,
                 '--chunk-seconds','30','--threads','2','--output-dir',output]
        network_denied=False
        if sys.platform=='darwin' and Path('/usr/bin/sandbox-exec').is_file():
            command=['/usr/bin/sandbox-exec','-p','(version 1)(allow default)(deny network*)',*command]
            network_denied=True
        first=invoke(command,env,timeout=900)
        text=(output/'transcript.txt').read_text(encoding='utf-8').lower()
        expected=('电脑','转写','录音') if language=='zh' else ('ask','country','you')
        if not all(word in text for word in expected):
            raise ValueError('程序启动但未识别出已知录音内容：'+text[:500])
        second=invoke(command,env,timeout=900)
        resumed=json.loads(second.stdout)
        # The existing timing API counts the mandatory --version probe as one
        # transcription tool call. Only the model inference must be absent.
        if (resumed.get('reused_chunks')!=resumed.get('chunks') or
                resumed.get('timing',{}).get('transcription_calls',0)!=1 or
                resumed.get('timing',{}).get('audio_calls',0)!=0):
            raise ValueError('同输入续用仍重新运行了转写')
        if digest(media)!=original_hash:raise ValueError('原始音频发生变化')
        repeat=invoke([*source_launch,'install','--target',target],env)
        if 'unchanged' not in repeat.stdout:raise ValueError('相同安装重复执行未保持不变')
        restored_mode=True
        if sys.platform!='win32':
            engine=target/info['tools']['whisper-cli'];engine.chmod(0o644)
            invoke([*source_launch,'install','--target',target],env)
            restored_mode=bool(engine.stat().st_mode&0o111)
            if not restored_mode:raise ValueError('没有修复解压后丢失的执行权限')
        result={'status':'PASS','target':info['target'],'archive_sha256':digest(archive),
                'version':manifest['version'],'manifest_files':len(manifest['files']),
                'bundled_python':True,'global_transcription_tools_available':False,
                'unicode_space_and_ampersand_paths':True,'installed_and_relocated':True,
                'transcribed_known_sample':True,'sample_language':language,'sample_text':text[:500],
                'original_unchanged':True,'repeat_install':'unchanged','cache_reused':True,
                'executable_mode_restored':restored_mode,'network_denied_during_asr':network_denied,
                'elapsed_seconds':round(time.perf_counter()-started,3),
                'scope':'完整包安装与本地转写链路；自制合成短句不证明真实整场准确率、说话人归属或文稿终审。'}
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('archive',type=Path)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(verify(args.archive,args.report),ensure_ascii=False,indent=2))
