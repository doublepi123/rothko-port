# SPDX-FileCopyrightText: The LineageOS Project
# SPDX-License-Identifier: Apache-2.0
"""Exercise real local Git LFS objects and source-preparation failure boundaries."""
from pathlib import Path
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('source_preparation', ROOT / 'tools/prepare-source.py')
PREPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREPARE)


class LocalLfsInputs(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='rothko-source-lfs-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.reference = self.root / 'reference'
        self.project = self.reference / 'prebuilt'
        self.project.mkdir(parents=True)
        self.environment = dict(os.environ, GIT_ALLOW_PROTOCOL='file', GIT_NO_LAZY_FETCH='1',
                                GIT_LFS_SKIP_SMUDGE='1', GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0')
        self.git('init', '-q')
        self.git('lfs', 'install', '--local', '--skip-smudge')
        (self.project / '.gitattributes').write_text('*.apk filter=lfs diff=lfs merge=lfs -text\n')
        with io.BytesIO() as stream:
            with zipfile.ZipFile(stream, 'w') as archive:
                archive.writestr('AndroidManifest.xml', b'local test fixture only')
            self.apk = stream.getvalue()
        self.oid = hashlib.sha256(self.apk).hexdigest()
        (self.project / 'sample.apk').write_bytes(self.apk)
        self.git('add', '.gitattributes', 'sample.apk')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@localhost',
                 'commit', '-q', '-m', 'Pinned LFS fixture')
        self.revision = self.git('rev-parse', 'HEAD').strip()
        self.pointer = self.git('show', 'HEAD:sample.apk').encode()
        self.assertTrue(self.pointer.startswith(b'version https://git-lfs.github.com/spec/v1\n'))
        self.cache = self.project / '.git/lfs/objects' / self.oid[:2] / self.oid[2:4] / self.oid
        self.assertEqual(self.cache.read_bytes(), self.apk)
        self.manifest = ET.Element('manifest')
        self.entry = ET.SubElement(self.manifest, 'project', path='prebuilt', name='fixture', revision=self.revision)
        self.entries = [self.entry]
        self.gitdirs = {'prebuilt': self.project / '.git'}

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.project), *args],
                                       env=self.environment, text=True, stderr=subprocess.PIPE)

    def inspect(self):
        return PREPARE.local_lfs_files(self.reference, self.entries, self.gitdirs, self.environment, 1)

    def checkout(self):
        destination = self.root / 'destination'
        target = destination / 'prebuilt/sample.apk'
        target.parent.mkdir(parents=True)
        target.write_bytes(self.pointer)
        return destination, target

    def test_cache_hydrates_independent_file_despite_dirty_reference(self):
        (self.project / 'sample.apk').write_bytes(b'dirty reference worktree')
        inputs = self.inspect()
        self.assertEqual(inputs[0]['local_source'], str(self.cache))
        destination, target = self.checkout()
        receipt = PREPARE.hydrate_local_lfs(destination, inputs)
        self.assertEqual(target.read_bytes(), self.apk)
        self.assertNotEqual(target.stat().st_ino, self.cache.stat().st_ino)
        self.assertFalse(receipt[0]['already_present'])
        self.assertEqual((self.project / 'sample.apk').read_bytes(), b'dirty reference worktree')

    def test_matching_reference_is_fallback_when_local_object_is_absent(self):
        self.cache.unlink()
        inputs = self.inspect()
        self.assertEqual(inputs[0]['local_source'], str(self.project / 'sample.apk'))
        destination, target = self.checkout()
        PREPARE.hydrate_local_lfs(destination, inputs)
        self.assertEqual(target.read_bytes(), self.apk)

    def test_missing_lfs_rejected_before_source_destination_creation(self):
        self.cache.unlink()
        (self.project / 'sample.apk').write_bytes(self.pointer)
        manifest = self.root / 'manifest.xml'
        ET.ElementTree(self.manifest).write(manifest)
        destination = self.root / 'must-not-exist'
        with self.assertRaisesRegex(ValueError, 'Missing verified local LFS object'):
            PREPARE.prepare(self.reference, manifest, destination, 1)
        self.assertFalse(destination.exists())

    def test_same_size_corruption_is_rejected(self):
        self.cache.write_bytes(b'X' * len(self.apk))
        (self.project / 'sample.apk').write_bytes(b'Y' * len(self.apk))
        with self.assertRaisesRegex(ValueError, 'Missing verified local LFS object'):
            self.inspect()

    def test_different_pointer_is_not_overwritten(self):
        inputs = self.inspect()
        destination, target = self.checkout()
        wrong = self.pointer.replace(self.oid.encode(), b'0' * 64)
        target.write_bytes(wrong)
        with self.assertRaisesRegex(ValueError, 'pointer differs'):
            PREPARE.hydrate_local_lfs(destination, inputs)
        self.assertEqual(target.read_bytes(), wrong)

    def test_cache_change_between_preflight_and_copy_is_rejected(self):
        inputs = self.inspect()
        self.cache.write_bytes(b'Z' * len(self.apk))
        destination, target = self.checkout()
        with self.assertRaisesRegex(ValueError, 'changed while copying'):
            PREPARE.hydrate_local_lfs(destination, inputs)
        self.assertEqual(target.read_bytes(), self.pointer)
        self.assertEqual(list(target.parent.glob('.rothko-lfs-*')), [])

    def test_existing_valid_material_is_unchanged(self):
        inputs = self.inspect()
        destination, target = self.checkout()
        target.write_bytes(self.apk)
        inode = target.stat().st_ino
        receipt = PREPARE.hydrate_local_lfs(destination, inputs)
        self.assertTrue(receipt[0]['already_present'])
        self.assertEqual(target.stat().st_ino, inode)

    def test_symlink_destination_is_rejected(self):
        inputs = self.inspect()
        destination, target = self.checkout()
        target.unlink()
        target.symlink_to(self.project / 'sample.apk')
        with self.assertRaisesRegex(ValueError, 'regular checkout file'):
            PREPARE.hydrate_local_lfs(destination, inputs)
        self.assertEqual((self.project / 'sample.apk').read_bytes(), self.apk)

    def test_literal_pointer_without_lfs_attribute_is_normal_source(self):
        (self.project / '.gitattributes').write_text('')
        (self.project / 'sample.apk').write_bytes(self.pointer)
        self.git('add', '.gitattributes', 'sample.apk')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@localhost',
                 'commit', '-q', '-m', 'Vendored pointer fixture without LFS filtering')
        self.entry.set('revision', self.git('rev-parse', 'HEAD').strip())
        self.cache.unlink()
        self.assertEqual(self.inspect(), [])

    def test_symlink_parent_cannot_write_outside_destination(self):
        inputs = self.inspect()
        destination = self.root / 'destination'
        destination.mkdir()
        (destination / 'prebuilt').symlink_to(self.project, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'regular checkout file'):
            PREPARE.hydrate_local_lfs(destination, inputs)
        self.assertEqual((self.project / 'sample.apk').read_bytes(), self.apk)


if __name__ == '__main__':
    unittest.main()
