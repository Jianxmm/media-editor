"""Native first-use bootstrap, model reuse, and rules-update integration test."""
from pathlib import Path
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import zipfile
from bundled_runtime import target_platform


def verify(base, parts, report):
    counts={}
    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            counts[self.path]=counts.get(self.path,0)+1;super().do_GET()
        def log_message(self,*args):pass
    with tempfile.TemporaryDirectory(prefix='shared-runtime-') as tmp:
        area=Path(tmp)
        with zipfile.ZipFile(base) as z:z.extractall(area/'source')
        source=area/'source/media-editor';cache=area/'共用 环境&缓存'
        server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(parts.resolve())))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        env=dict(os.environ,MEDIA_EDITOR_COMPONENT_BASE_URL=f'http://127.0.0.1:{server.server_port}',MEDIA_EDITOR_RUNTIME_CACHE=str(cache),
                 PYTHONUTF8='1',PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1')
        for n in ('PYTHONHOME','PYTHONPATH','DYLD_LIBRARY_PATH'):env.pop(n,None)
        env['PATH']=str(Path(os.environ.get('SystemRoot','C:/Windows'))/'System32') if sys.platform=='win32' else '/usr/bin:/bin'
        def launch(root,*args):
            cmd=[str(root/'media-editor.cmd')] if sys.platform=='win32' else ['/bin/bash',str(root/'media-editor.command')]
            print('COMPONENT VERIFY:',args[0],flush=True)
            return subprocess.run([*cmd,*map(str,args)],env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',check=True,timeout=1200)
        try:
            doctor=json.loads(launch(source,'doctor','--task','local-asr').stdout)
            assert doctor['ready'] and doctor['bundled_runtime']
            target=area/'安装 空格&目录/skills/media-editor'
            launch(source,'install','--target',target)
            assert json.loads(launch(target,'doctor','--task','local-asr').stdout)['ready']
            runtime=Path((target/'.runtime-path').read_text());model=Path((runtime/'.models-path').read_text())
            requests=counts.get('/media-editor-models.zip',0)
            (target/'SKILL.md').write_text((target/'SKILL.md').read_text(encoding='utf-8')+'\nmanual marker\n',encoding='utf-8')
            upgraded=json.JSONDecoder().raw_decode(launch(source,'install','--target',target,'--upgrade').stdout)[0]
            assert upgraded['status']=='upgraded'
            assert 'manual marker' in (Path(upgraded['backup'])/'SKILL.md').read_text(encoding='utf-8')
            assert (target/'.runtime-path').read_text()==str(runtime)
            assert counts.get('/media-editor-models.zip',0)==requests==1
            with zipfile.ZipFile(base) as z:z.extractall(area/'other-agent')
            other=area/'other-agent/media-editor'
            assert json.loads(launch(other,'doctor','--task','local-asr').stdout)['ready']
            assert counts.get('/media-editor-models.zip',0)==1
            assert sum(v for k,v in counts.items() if k.startswith('/media-editor-runtime-'))==1
            inference=json.loads(launch(target,'transcribe',runtime/'runtime/samples/jfk.wav','--language','en','--threads','2','--output-dir',area/'transcript').stdout)
            text=(area/'transcript/transcript.txt').read_text().lower();assert 'country' in text and 'ask' in text
            result={'status':'PASS','target':target_platform(),'first_use_without_global_python':True,'shared_models_downloads':requests,
                    'runtime_outside_skill':not runtime.is_relative_to(target),'upgrade_retains_runtime':True,'transcription_timing':inference['timing'],
                    'second_agent_reuses_programs_and_models':True,'manual_changes_backed_up':True,
                    'scope':'Native bootstrap, shared runtime and actual short-sample transcription; not long-form editorial acceptance.'}
        except subprocess.CalledProcessError as exc:
            raise RuntimeError((exc.stdout or '')[-1500:]+'\n'+(exc.stderr or '')[-4000:]) from exc
        finally:server.shutdown();server.server_close()
    report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--parts',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    print(json.dumps(verify(a.base,a.parts,a.report),ensure_ascii=False,indent=2))
