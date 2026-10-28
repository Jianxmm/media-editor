import importlib.util
import re
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        archive = self.root / 'bundle.zip'
        load('packager', ROOT / 'build_package.py').build(archive)
        with zipfile.ZipFile(archive) as z:
            z.extractall(self.root / 'extracted')
        self.source = self.root / 'extracted/media-editor'
        self.installer = load('installer', self.source / 'install.py')

    def test_independent_install_includes_unchanged_core_and_preserves_existing(self):
        target = self.root / 'skills/media-editor'
        self.installer.install(self.source, target)
        self.assertEqual((target / '.livestream-core/SKILL.md').read_bytes(),
                         (ROOT / '.livestream-core/SKILL.md').read_bytes())
        marker = target / 'my-edits.txt'; marker.write_text('keep')
        with self.assertRaises(FileExistsError):
            self.installer.install(self.source, target)
        self.assertEqual(marker.read_text(), 'keep')

    def test_damaged_release_is_not_installed(self):
        (self.source / 'SKILL.md').write_text('modified')
        target = self.root / 'skills/media-editor'
        with self.assertRaises(ValueError):
            self.installer.install(self.source, target)
        self.assertFalse(target.exists())

    def test_installed_entry_and_references_are_self_contained(self):
        target = self.root / 'skills/media-editor'
        self.installer.install(self.source, target)
        for document in [target / 'SKILL.md', *sorted((target / 'references').glob('*.md'))]:
            for link in re.findall(r'\[[^\]\n]*\]\(([^\s)]+)\)', document.read_text()):
                if link.startswith(('https://', 'http://', '#')):
                    continue
                self.assertTrue((document.parent / link.split('#')[0]).is_file(),
                                f'{document.relative_to(target)} -> {link}')
        self.assertEqual((target / 'tests/test_review_records.py').read_bytes(),
                         (ROOT / 'tests/test_review_records.py').read_bytes())

    def test_repeat_upgrade_backup_and_restore_preserve_user_changes(self):
        target=self.root/'skills/media-editor'
        self.installer.install(self.source,target)
        (target/'scripts/__pycache__').mkdir()
        (target/'scripts/__pycache__/runtime.pyc').write_bytes(b'generated cache')
        self.assertEqual(self.installer.install(self.source,target)['status'],'unchanged')
        (target/'SKILL.md').write_text('user edited previous version')
        (target/'private-notes.md').write_text('private user data')
        result=self.installer.install(self.source,target,upgrade=True)
        backup=Path(result['backup'])
        self.assertEqual((backup/'SKILL.md').read_text(),'user edited previous version')
        self.assertEqual((backup/'private-notes.md').read_text(),'private user data')
        self.assertFalse((target/'private-notes.md').exists())
        restored=self.installer.restore(backup,target)
        self.assertEqual((target/'private-notes.md').read_text(),'private user data')
        self.assertEqual((target/'SKILL.md').read_text(),'user edited previous version')
        self.assertTrue(backup.is_dir())
        self.assertTrue(Path(restored['previous_backup']).is_dir())

    def test_damaged_upgrade_does_not_move_previous_installation(self):
        target=self.root/'skills/media-editor';self.installer.install(self.source,target)
        (target/'SKILL.md').write_text('keep user draft')
        (self.source/'SKILL.md').write_text('damaged package')
        with self.assertRaises(ValueError):self.installer.install(self.source,target,upgrade=True)
        self.assertEqual((target/'SKILL.md').read_text(),'keep user draft')


if __name__ == '__main__':
    unittest.main()
