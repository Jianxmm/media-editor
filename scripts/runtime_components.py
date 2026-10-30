"""Split tested offline bundles into reusable runtime and platform-neutral models."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import zipfile


def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def split(archive, output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        manifest=json.loads(source.read('media-editor/PACKAGE-MANIFEST.json'))
        runtime=json.loads(source.read('media-editor/runtime/runtime.json'))
        target=runtime['target'];version=manifest['version'];parts={}
        for kind,name in [('runtime','media-editor-runtime-'+target+'.zip'),('models','media-editor-models.zip')]:
            dest=output/name
            if dest.exists():raise FileExistsError(dest)
            hashes={};executable=[]
            with zipfile.ZipFile(dest,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
                for rel,expected in sorted(manifest['files'].items()):
                    is_model=rel.startswith('runtime/models/') or rel in {'runtime/licenses/Whisper-model-MIT.txt','runtime/licenses/Silero-VAD-MIT.txt'}
                    if not rel.startswith('runtime/') or is_model!=(kind=='models'):continue
                    info=zipfile.ZipInfo('media-editor/'+rel,(2026,1,1,0,0,0));info.create_system=3
                    info.compress_type=zipfile.ZIP_STORED if kind=='models' else zipfile.ZIP_DEFLATED
                    mode=0o755 if rel in manifest.get('executable_files',[]) else 0o644
                    info.external_attr=(0o100000|mode)<<16
                    if mode==0o755:executable.append(rel)
                    h=hashlib.sha256()
                    with source.open('media-editor/'+rel) as src,z.open(info,'w',force_zip64=True) as dst:
                        if kind=='models' and rel.endswith('.txt'):
                            data=src.read().replace(b'\r\n',b'\n');dst.write(data);h.update(data)
                        else:
                            for block in iter(lambda:src.read(4*1024*1024),b''):dst.write(block);h.update(block)
                    hashes[rel]=h.hexdigest()
                    if not (kind=='models' and rel.endswith('.txt')) and hashes[rel]!=expected:raise ValueError('源包校验失败：'+rel)
                meta={'name':'media-editor-component','schema_version':1,'kind':kind,'files':hashes,'executable_files':executable}
                i=zipfile.ZipInfo('media-editor/PACKAGE-MANIFEST.json',(2026,1,1,0,0,0));i.create_system=3;i.external_attr=0o100644<<16
                i.compress_type=zipfile.ZIP_STORED if kind=='models' else zipfile.ZIP_DEFLATED
                z.writestr(i,json.dumps(meta,sort_keys=True,ensure_ascii=False,indent=2)+'\n')
            parts[kind]={'name':name,'sha256':sha(dest),'bytes':dest.stat().st_size}
        catalog={'schema_version':1,'version':version,'target':target,**parts}
        path=output/('components-'+target+'.json');path.write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n')
        return catalog


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('archive',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    print(json.dumps(split(a.archive,a.output),ensure_ascii=False,indent=2))
