import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import runtime_components as components
import manage_runtime as manager
import bundled_runtime as runtime


class ComponentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.area=Path(self.temp.name);self.skill=self.area/'skill';self.skill.mkdir()
        (self.skill/'VERSION').write_text('1.0.2')

    def bundle(self,folder,engine=b'engine'):
        folder.mkdir()
        data={'runtime/runtime.json':json.dumps({'schema_version':1,'target':runtime.target_platform(),'model':'runtime/models/speech.bin',
             'python':'runtime/python/python','tools':{k:'runtime/bin/'+k for k in ('ffmpeg','ffprobe','whisper-cli')}}).encode(),
             'runtime/python/python':b'python','runtime/models/speech.bin':b'model',
             **{'runtime/bin/'+k:engine for k in ('ffmpeg','ffprobe','whisper-cli')}}
        manifest={'name':'media-editor','version':'1.0.2','files':{k:hashlib.sha256(v).hexdigest() for k,v in data.items()},'executable_files':[]}
        archive=folder/'full.zip'
        with zipfile.ZipFile(archive,'w') as z:
            for k,v in data.items():z.writestr('media-editor/'+k,v)
            z.writestr('media-editor/PACKAGE-MANIFEST.json',json.dumps(manifest))
        out=folder/'parts';catalog=components.split(archive,out)
        return out,catalog,out/('components-'+runtime.target_platform()+'.json')

    def test_models_are_shared_across_program_updates_and_rule_upgrade(self):
        first,cat,path=self.bundle(self.area/'one');cache=self.area/'cache'
        with patch.object(manager.subprocess,'run'):
            a=manager.setup(self.skill,path,cache,first.as_uri())
        model=runtime.bundled_model(self.skill);inode=model.stat().st_ino
        second,cat2,path2=self.bundle(self.area/'two',b'updated engine')
        self.assertEqual(cat['models']['sha256'],cat2['models']['sha256'])
        self.assertNotEqual(cat['runtime']['sha256'],cat2['runtime']['sha256'])
        with patch.object(manager.subprocess,'run'):
            b=manager.setup(self.skill,path2,cache,second.as_uri())
        self.assertEqual(runtime.bundled_model(self.skill).stat().st_ino,inode)
        self.assertNotEqual(a['runtime'],b['runtime'])
        spec=importlib.util.spec_from_file_location('upgrade_installer',ROOT/'install.py');installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
        source=self.area/'source';source.mkdir();(source/'SKILL.md').write_text('new rules')
        files={'SKILL.md':hashlib.sha256(b'new rules').hexdigest()}
        (source/'PACKAGE-MANIFEST.json').write_text(json.dumps({'name':'media-editor','files':files}))
        installer.install(source,self.skill,upgrade=True)
        self.assertEqual(runtime.bundled_model(self.skill).stat().st_ino,inode)

    def test_corrupt_component_never_switches_existing_pointer(self):
        folder,cat,path=self.bundle(self.area/'one')
        (self.skill/'.runtime-path').write_text('/existing/working/runtime')
        archive=folder/cat['models']['name'];archive.write_bytes(b'corrupted download')
        with self.assertRaisesRegex(ValueError,'校验失败'):
            manager.setup(self.skill,path,self.area/'cache',folder.as_uri())
        self.assertEqual((self.skill/'.runtime-path').read_text(),'/existing/working/runtime')

    def test_archive_traversal_rejected(self):
        archive=self.area/'bad.zip'
        with zipfile.ZipFile(archive,'w') as z:z.writestr('media-editor/../../escape',b'no')
        item={'name':archive.name,'sha256':components.sha(archive),'bytes':archive.stat().st_size}
        with self.assertRaisesRegex(ValueError,'路径无效'):
            manager.component(item,'models',self.area/'cache',self.area.as_uri())
        self.assertFalse((self.area/'escape').exists())

    def test_legacy_full_runtime_survives_rules_only_upgrade(self):
        spec=importlib.util.spec_from_file_location('legacy_upgrade',ROOT/'install.py');i=importlib.util.module_from_spec(spec);spec.loader.exec_module(i)
        full=self.area/'full';base=self.area/'base';full.mkdir();base.mkdir()
        for p,data in [(full/'SKILL.md',b'old rules'),(full/'runtime/model',b'preserve model'),(base/'SKILL.md',b'new rules')]:
            p.parent.mkdir(exist_ok=True);p.write_bytes(data)
        for root in (full,base):
            files={p.relative_to(root).as_posix():components.sha(p) for p in root.rglob('*') if p.is_file()}
            (root/'PACKAGE-MANIFEST.json').write_text(json.dumps({'name':'media-editor','files':files}))
        target=self.area/'skills/media-editor';i.install(full,target)
        (target/'SKILL.md').write_text('manual edit')
        result=i.install(base,target,upgrade=True)
        self.assertEqual((target/'runtime/model').read_bytes(),b'preserve model')
        self.assertEqual((Path(result['backup'])/'SKILL.md').read_text(),'manual edit')

    def test_failure_summary_never_echoes_signed_url(self):
        import media_intake
        from subprocess import CompletedProcess
        r=CompletedProcess([],1,stderr='Postprocessing: muxer failed https://example.invalid/?token=secret')
        message=str(media_intake.failure('下载',r,'保留现场'))
        self.assertIn('合并失败',message);self.assertNotIn('secret',message)


if __name__=='__main__':unittest.main()
