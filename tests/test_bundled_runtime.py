import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import bundled_runtime as runtime


def installer():
    spec=importlib.util.spec_from_file_location('offline_install_test',ROOT/'install.py')
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


class BundledRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'source';self.root.mkdir()

    def config(self,**changes):
        info={'schema_version':1,'target':runtime.target_platform(),
              'model':'runtime/models/test.bin','tools':{'whisper-cli':'runtime/bin/whisper-cli'}}
        info.update(changes);(self.root/'runtime').mkdir(exist_ok=True)
        (self.root/'runtime/runtime.json').write_text(json.dumps(info));return info

    def test_source_skill_has_no_implicit_dependency_on_developer_model(self):
        self.assertIsNone(runtime.runtime_info(self.root))
        self.assertIsNone(runtime.bundled_model(self.root))

    def test_programs_without_model_are_not_reported_as_transcription_ready(self):
        import media_intake
        model=Path(self.temp.name)/'model.bin';model.write_bytes(b'fixture')
        with patch('shutil.which',return_value='/existing/tool'):
            self.assertFalse(media_intake.check_task('local-asr')['ready'])
            self.assertTrue(media_intake.check_task('local-asr',model)['ready'])

    def test_full_bundle_missing_engine_never_borrows_global_engine(self):
        self.config()
        with patch('shutil.which',return_value='/developer/bin/whisper-cli'):
            with self.assertRaisesRegex(ValueError,'缺少文件'):runtime.bundled_tool('whisper-cli',self.root)

    def test_bundle_for_another_platform_is_rejected(self):
        self.config(target='other-platform')
        with self.assertRaisesRegex(ValueError,'不匹配'):runtime.bundled_model(self.root)

    def test_model_path_must_remain_inside_runtime(self):
        self.config(model='../outside.bin')
        with self.assertRaisesRegex(ValueError,'路径无效'):runtime.bundled_model(self.root)

    @unittest.skipIf(os.name=='nt','Windows does not provide POSIX executable bits')
    def test_symlinked_runtime_is_rejected(self):
        self.config();(self.root/'runtime/models').mkdir()
        external=Path(self.temp.name)/'outside.bin';external.write_bytes(b'model')
        (self.root/'runtime/models/test.bin').symlink_to(external)
        with self.assertRaisesRegex(ValueError,'符号链接'):runtime.bundled_model(self.root)

    def install_fixture(self,executables):
        files={'SKILL.md':b'name: fixture','bin/program':b'program bytes'}
        for name,data in files.items():
            p=self.root/name;p.parent.mkdir(exist_ok=True);p.write_bytes(data);p.chmod(0o644)
        meta={'name':'media-editor','files':{n:hashlib.sha256(b).hexdigest() for n,b in files.items()},
              'executable_files':executables}
        (self.root/'PACKAGE-MANIFEST.json').write_text(json.dumps(meta))

    @unittest.skipIf(os.name=='nt','Windows does not provide POSIX executable bits')
    def test_install_restores_execution_mode_and_repeat_repairs_it(self):
        self.install_fixture(['bin/program']);tool=installer();target=Path(self.temp.name)/'skills/media-editor'
        tool.install(self.root,target)
        self.assertTrue((target/'bin/program').stat().st_mode&stat.S_IXUSR)
        (target/'bin/program').chmod(0o644)
        self.assertEqual(tool.install(self.root,target)['status'],'unchanged')
        self.assertTrue((target/'bin/program').stat().st_mode&stat.S_IXUSR)

    def test_invalid_executable_manifest_leaves_old_installation_untouched(self):
        self.install_fixture(['../outside']);target=Path(self.temp.name)/'skills/media-editor';target.mkdir(parents=True)
        marker=target/'my-notes.md';marker.write_text('keep')
        with self.assertRaisesRegex(ValueError,'执行权限'):installer().install(self.root,target,upgrade=True)
        self.assertEqual(marker.read_text(),'keep')


if __name__=='__main__':unittest.main()
