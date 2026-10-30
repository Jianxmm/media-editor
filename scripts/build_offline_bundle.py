#!/usr/bin/env python3
"""Build a platform-native offline distribution from pinned public dependencies."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

from bundled_runtime import target_platform

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ('macos-arm64', 'macos-x64', 'windows-x64')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def download(item, cache):
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / item['filename']
    if path.exists():
        if digest(path) != item['sha256']:
            raise ValueError('依赖缓存已损坏：' + path.name)
        return path
    temporary = path.with_name(path.name + '.part')
    for attempt in range(3):
        try:
            request = urllib.request.Request(item['url'], headers={'User-Agent': 'media-editor-offline-builder'})
            with urllib.request.urlopen(request, timeout=60) as response, temporary.open('wb') as stream:
                shutil.copyfileobj(response, stream)
            if digest(temporary) != item['sha256']:
                raise ValueError('依赖下载校验失败：' + path.name)
            temporary.rename(path)
            return path
        except Exception:
            temporary.unlink(missing_ok=True)
            if attempt == 2:
                raise
    raise RuntimeError('依赖下载未完成')


def extract(archive, folder):
    if folder.exists():
        return next(p for p in folder.iterdir() if p.is_dir())
    folder.mkdir(parents=True)
    with tarfile.open(archive) as stream:
        stream.extractall(folder, filter='data')
    directories = [p for p in folder.iterdir() if p.is_dir()]
    if len(directories) != 1:
        raise ValueError('依赖归档根目录无效')
    return directories[0]


def copy_tree(source, target):
    """Flatten only in-tree links: skill installers deliberately reject symlinks."""
    source = source.resolve()
    for path in source.rglob('*'):
        relative = path.relative_to(source)
        if '__pycache__' in relative.parts or path.suffix == '.pyc':
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(source):
            raise ValueError('依赖链接越界：' + str(relative))
        if path.is_file():
            output = target / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, output, follow_symlinks=True)


def run(args, cwd=None, env=None):
    print('BUILD:', shlex.join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), cwd=cwd, env=env, check=True)


def posix_windows(path):
    value = str(Path(path).resolve()).replace('\\', '/')
    return '/' + value[0].lower() + value[2:] if len(value) > 1 and value[1] == ':' else value


def msys_run(command):
    bash=Path(os.environ.get('MSYS2_BASH','C:/msys64/usr/bin/bash.exe'))
    if not bash.is_file():raise ValueError('Windows构建需要MSYS2/UCRT64；使用仓库的原生构建工作流')
    env=dict(os.environ,MSYSTEM='UCRT64',MSYS2_PATH_TYPE='inherit',CHERE_INVOKING='1')
    run([bash,'-lc','export PATH=/ucrt64/bin:/usr/bin:$PATH; '+command],env=env)


def build_zlib(source,target,jobs):
    if target=='windows-x64':
        msys_run('cd '+shlex.quote(posix_windows(source))+' && make -f win32/Makefile.gcc PREFIX= -j'+str(jobs)+' libz.a')
    else:
        deployment='11.0' if target=='macos-arm64' else '10.15'
        env=dict(os.environ,CFLAGS='-O3 -mmacosx-version-min='+deployment)
        run(['sh','configure','--static'],source,env)
        run(['make','-j'+str(jobs),'libz.a'],source,env)


def build_ffmpeg(source, target, jobs, zlib):
    args = [
        '--disable-everything', '--disable-autodetect', '--disable-network',
        '--disable-doc', '--disable-debug', '--disable-ffplay', '--disable-asm',
        '--disable-gpl', '--disable-nonfree', '--disable-iconv', '--disable-bzlib',
        '--disable-lzma', '--enable-zlib', '--disable-avdevice',
        '--enable-protocol=file,pipe', '--enable-ffmpeg', '--enable-ffprobe',
        '--enable-avcodec', '--enable-avformat', '--enable-avfilter',
        '--enable-swresample', '--enable-swscale',
        '--enable-demuxer=mov,matroska,mp3,wav,aiff,flac,ogg,aac,image2,png_pipe,jpeg_pipe',
        '--enable-decoder=aac,aac_fixed,aac_latm,mp3,mp3float,pcm_s16le,pcm_s16be,pcm_s24le,pcm_s24be,pcm_s32le,pcm_s32be,pcm_f32le,pcm_f64le,alac,flac,opus,vorbis,h264,hevc,vp9,vp8,av1,mjpeg,png,prores',
        '--enable-encoder=pcm_s16le,aac,png,mjpeg', '--enable-muxer=wav,ipod,image2,null',
        '--enable-parser=aac,aac_latm,mpegaudio,flac,opus,vorbis,h264,hevc,vp8,vp9,av1,mjpeg,png',
        '--enable-filter=aresample,aformat,anull,atrim,asetpts,volume,volumedetect,pan,channelsplit,concat,crop,scale,fps,select,thumbnail',
    ]
    location=posix_windows(zlib) if target=='windows-x64' else str(zlib)
    args+=['--extra-cflags=-I'+location,'--extra-ldflags=-L'+location]
    if target.startswith('macos-'):
        deployment = '11.0' if target == 'macos-arm64' else '10.15'
        args += ['--cc=clang', '--extra-cflags=-mmacosx-version-min=' + deployment,
                 '--extra-ldflags=-mmacosx-version-min=' + deployment]
        run(['sh', 'configure', *args], source)
        run(['make', '-j' + str(jobs), 'ffmpeg', 'ffprobe'], source)
    else:
        args += ['--target-os=mingw32', '--cc=gcc', '--cxx=g++', '--extra-ldflags=-static']
        command = 'cd ' + shlex.quote(posix_windows(source))
        command += ' && ' + shlex.join(['sh', 'configure', *args])
        command += ' && make -j' + str(jobs) + ' ffmpeg.exe ffprobe.exe'
        msys_run(command)
    return args


def build_whisper(source, target, jobs):
    build = source / 'build-offline'
    args = ['cmake', '-S', source, '-B', build, '-DCMAKE_BUILD_TYPE=Release',
            '-DBUILD_SHARED_LIBS=OFF', '-DGGML_OPENMP=OFF', '-DGGML_NATIVE=OFF',
            '-DGGML_METAL=OFF', '-DGGML_CUDA=OFF', '-DGGML_VULKAN=OFF',
            '-DWHISPER_BUILD_TESTS=OFF', '-DWHISPER_BUILD_SERVER=OFF',
            '-DGGML_CCACHE=OFF']
    if target.startswith('macos-'):
        args += ['-DCMAKE_OSX_DEPLOYMENT_TARGET=' + ('11.0' if target == 'macos-arm64' else '10.15')]
    else:
        args += ['-A', 'x64', '-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded']
        manifest = source / 'offline-utf8.manifest'
        manifest.write_text('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                            '<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">'
                            '<application xmlns="urn:schemas-microsoft-com:asm.v3"><windowsSettings>'
                            '<activeCodePage xmlns="http://schemas.microsoft.com/SMI/2019/WindowsSettings">UTF-8</activeCodePage>'
                            '</windowsSettings></application></assembly>\n', encoding='utf-8')
        args += ['-DCMAKE_EXE_LINKER_FLAGS=/MANIFEST:EMBED /MANIFESTINPUT:' + str(manifest)]
    if target.endswith('x64'):
        args += ['-DGGML_AVX=OFF', '-DGGML_AVX2=OFF', '-DGGML_AVX512=OFF',
                 '-DGGML_FMA=OFF', '-DGGML_F16C=OFF']
    run(args)
    run(['cmake', '--build', build, '--config', 'Release', '--parallel', str(jobs), '--target', 'whisper-cli'])
    executable = build / 'bin' / ('Release/whisper-cli.exe' if target == 'windows-x64' else 'whisper-cli')
    if not executable.is_file():
        raise ValueError('whisper-cli未生成')
    return executable, list(map(str, args[6:]))


def write_archive(folder, output):
    files = sorted(p for p in folder.rglob('*') if p.is_file() and p.name != 'PACKAGE-MANIFEST.json'
                   and '__pycache__' not in p.parts and p.suffix != '.pyc')
    if any(p.is_symlink() for p in files):
        raise ValueError('分发目录不能有符号链接')
    hashes = {p.relative_to(folder).as_posix(): digest(p) for p in files}
    executable = [p.relative_to(folder).as_posix() for p in files if p.stat().st_mode & 0o111]
    manifest = {'name': 'media-editor', 'version': (folder / 'VERSION').read_text().strip(),
                'files': hashes, 'executable_files': executable}
    (folder / 'PACKAGE-MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError('发布包已存在，拒绝覆盖：' + str(output))
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in [*files, folder / 'PACKAGE-MANIFEST.json']:
            info = zipfile.ZipInfo('media-editor/' + path.relative_to(folder).as_posix(), (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if path.relative_to(folder).as_posix() in executable else 0o100644) << 16
            with z.open(info, 'w', force_zip64=True) as stream, path.open('rb') as source:
                shutil.copyfileobj(source, stream, length=4 * 1024 * 1024)
    return {'path': str(output), 'sha256': digest(output), 'bytes': output.stat().st_size, 'files': len(files) + 1}


def build(target, cache, output, model_dir=None, jobs=4):
    if target != target_platform():
        raise ValueError('必须在目标系统构建和执行测试，不能在Mac上伪装Windows验收')
    cache = cache.expanduser().resolve()
    output = output.expanduser().resolve()
    if output.exists():
        raise FileExistsError('完整包目标已存在，原包保留')
    dependencies = json.loads((ROOT / 'assets/runtime-lock.json').read_text())['dependencies']
    names = ['python-' + target, 'whisper-source', 'ffmpeg-source', 'zlib-source', 'yt-dlp-source', 'speech-model', 'vad-model']
    archives = {}
    for name in names:
        item = dependencies[name]
        existing = (model_dir / item['filename']) if model_dir and name.endswith('model') else None
        if existing and existing.is_file():
            if digest(existing) != item['sha256']:
                raise ValueError('已有模型校验失败：' + name)
            archives[name] = existing
        else:
            archives[name] = download(item, cache / 'downloads')
    work = cache / ('build-' + target)
    whisper = extract(archives['whisper-source'], work / 'whisper')
    ffmpeg = extract(archives['ffmpeg-source'], work / 'ffmpeg')
    python = extract(archives['python-' + target], work / 'python')
    ytdlp = extract(archives['yt-dlp-source'], work / 'yt-dlp')
    zlib=extract(archives['zlib-source'],work/'zlib')
    build_zlib(zlib,target,jobs)
    ffmpeg_args = build_ffmpeg(ffmpeg, target, jobs, zlib)
    whisper_exe, whisper_args = build_whisper(whisper, target, jobs)
    with tempfile.TemporaryDirectory(prefix='offline-package-', dir=cache) as temporary:
        stage = Path(temporary)
        spec = importlib.util.spec_from_file_location('base_package', ROOT / 'build_package.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        base = stage / 'base.zip'
        module.build(base)
        with zipfile.ZipFile(base) as z:
            z.extractall(stage)
        folder = stage / 'media-editor'
        runtime = folder / 'runtime'
        bins = runtime / 'bin'; bins.mkdir(parents=True)
        suffix = '.exe' if target == 'windows-x64' else ''
        for name, source in [('whisper-cli', whisper_exe), ('ffmpeg', ffmpeg / ('ffmpeg' + suffix)),
                             ('ffprobe', ffmpeg / ('ffprobe' + suffix))]:
            destination = bins / (name + suffix)
            shutil.copyfile(source, destination)
            destination.chmod(0o755)
        copy_tree(python, runtime / 'python')
        copy_tree(ytdlp / 'yt_dlp', runtime / 'vendor/yt_dlp')
        (runtime / 'models').mkdir()
        for name in ('speech-model', 'vad-model'):
            shutil.copyfile(archives[name], runtime / 'models' / dependencies[name]['filename'])
        sources = runtime / 'sources'; sources.mkdir()
        for name in ('ffmpeg-source', 'whisper-source', 'zlib-source', 'yt-dlp-source'):
            shutil.copyfile(archives[name], sources / dependencies[name]['filename'])
        licenses = runtime / 'licenses'; licenses.mkdir()
        for name, path in [('FFmpeg-LICENSE.md', ffmpeg / 'LICENSE.md'),
                           ('FFmpeg-LGPLv2.1.txt', ffmpeg / 'COPYING.LGPLv2.1'),
                           ('whisper-MIT.txt', whisper / 'LICENSE'), ('yt-dlp-LICENSE.txt', ytdlp / 'LICENSE')]:
            shutil.copyfile(path, licenses / name)
        (licenses / 'IJG-NOTICE.txt').write_text('FFmpeg includes code based in part on the work of the Independent JPEG Group.\nThe upstream JPEG-derived source files are unmodified; the full FFmpeg source is included.\n', encoding='utf-8')
        shutil.copyfile(zlib/('LICENSE' if (zlib/'LICENSE').is_file() else 'README'),licenses/'zlib-LICENSE.txt')
        info = {'schema_version': 1, 'target': target,
                'model': 'runtime/models/' + dependencies['speech-model']['filename'],
                'tools': {name: 'runtime/bin/' + name + suffix for name in ('ffmpeg', 'ffprobe', 'whisper-cli')},
                'python': 'runtime/python/python.exe' if suffix else 'runtime/python/bin/python3.12',
                'dependencies': {name: dependencies[name] for name in names},
                'build': {'ffmpeg_flags':[a.replace(posix_windows(zlib) if suffix else str(zlib),'<ZLIB_SOURCE>') for a in ffmpeg_args],
                          'whisper_flags':[a.replace(str(whisper),'<WHISPER_SOURCE>') for a in whisper_args],
                          'purpose':'Local transcription; no API key or media upload','ffmpeg_external_libraries':['zlib']}}
        info['tools']['yt-dlp'] = 'runtime/vendor/yt_dlp/__main__.py'
        (runtime / 'runtime.json').write_text(json.dumps(info, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (folder / 'media-editor.command').chmod(0o755)
        # The public upstream sample is validation input, not user media.
        (runtime / 'samples').mkdir()
        shutil.copyfile(whisper / 'samples/jfk.wav', runtime / 'samples/jfk.wav')
        result = write_archive(folder, output)
    result['target'] = target
    receipt = output.with_suffix('.build.json')
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='维护者：在目标系统构建转写完整包')
    parser.add_argument('--target', choices=TARGETS, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model-dir', type=Path)
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    print(json.dumps(build(args.target, args.cache, args.output, args.model_dir, args.jobs), ensure_ascii=False, indent=2))
