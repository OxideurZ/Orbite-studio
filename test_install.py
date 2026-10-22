"""Update transactions: preserve data and the active environment on failure."""
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch,Mock
import zipfile

import install as manager
from runtime import ffmpeg_executable

META={'app_id':'orbite-studio','schema':1,'version':'0.8.0','repository':manager.REPOSITORY,'branch':'main','python_min':[3,10]}


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name).resolve();self.root=self.base/'managed';self.source=self.base/'source';self.source.mkdir()
        (self.source/'app_version.json').write_text(json.dumps(META))
        for name in ['studio.py','studio_model.py','runtime.py','install.py','requirements.txt']:(self.source/name).write_text('# fixture\n')
        self.data=self.root/'data/projects/session.json';self.data.parent.mkdir(parents=True);self.data.write_text('personal content')

    def prepare(self,app,release):
        file=manager.environment_python(release);file.parent.mkdir(parents=True);file.write_text('fake interpreter')

    def install(self,prepare=None):return manager.install_release(self.root,source=self.source,prepare=prepare or self.prepare)

    def test_successful_update_switches_last_and_retains_old_release_and_data(self):
        first=self.install();(self.source/'studio.py').write_text('# version two')
        def prepare(app,release):
            self.assertEqual(manager.read_json(self.root/'current.json'),first)
            self.prepare(app,release)
        second=self.install(prepare)
        self.assertNotEqual(first['commit'],second['commit'])
        self.assertEqual(manager.read_json(self.root/'previous.json'),first)
        self.assertTrue(manager.installed_release(self.root,first).is_dir())
        self.assertEqual(self.data.read_text(),'personal content')
        self.assertIn(str(self.root),(self.root/('ORBITE.command' if sys.platform=='darwin' else 'ORBITE.sh')).read_text() if os.name!='nt' else (self.root/'ORBITE.cmd').read_text().replace('%~dp0.',str(self.root)))

    def test_dependency_failure_cannot_change_active_version_or_personal_data(self):
        first=self.install();(self.source/'studio.py').write_text('# broken update')
        def fail(app,release):raise RuntimeError('pip failure')
        with self.assertRaisesRegex(RuntimeError,'pip failure'):self.install(fail)
        self.assertEqual(manager.read_json(self.root/'current.json'),first)
        self.assertEqual(self.data.read_text(),'personal content')
        self.assertEqual(len(list((self.root/'releases').iterdir())),1)

    def test_rollback_selects_retained_version_without_reinstalling(self):
        first=self.install();(self.source/'studio.py').write_text('# second');second=self.install()
        self.assertEqual(manager.rollback(self.root),first)
        self.assertEqual(manager.read_json(self.root/'current.json'),first)
        self.assertEqual(manager.read_json(self.root/'previous.json'),second)
        self.assertEqual(self.data.read_text(),'personal content')

    def test_installation_lock_rejects_concurrent_installers(self):
        with manager.installation_lock(self.root):
            with self.assertRaisesRegex(RuntimeError,'déjà'):self.install()

    def test_install_destination_cannot_be_nested_in_source(self):
        with self.assertRaises(ValueError):manager.install_release(self.source/'managed',source=self.source,prepare=self.prepare)

    def test_failed_manifest_never_reaches_dependency_install(self):
        bad=deepcopy(META);bad['app_id']='other-app';(self.source/'app_version.json').write_text(json.dumps(bad))
        with self.assertRaises(ValueError):self.install()
        self.assertFalse((self.root/'current.json').exists());self.assertEqual(self.data.read_text(),'personal content')

    def test_github_download_is_pinned_to_verified_commit_and_repository(self):
        sha='a'*40
        with patch.object(manager,'_request',side_effect=[json.dumps({'sha':sha}).encode(),json.dumps(META).encode()]) as request:
            info=manager.remote_release()
        self.assertEqual(info['commit'],sha)
        self.assertIn('/'+sha+'/app_version.json',request.call_args_list[1].args[0])
        with patch.object(manager,'_request',return_value=b'{"sha":"../bad"}'):
            with self.assertRaises(ValueError):manager.remote_release()

    def test_archive_rejects_traversal_links_and_case_collisions(self):
        for names,symlink in [(['repo/../outside.py'],False),(['repo/..\\outside.py'],False),(['repo/link'],True),(['repo/A.py','repo/a.py'],False)]:
            blob=io.BytesIO()
            with zipfile.ZipFile(blob,'w') as z:
                for name in names:
                    entry=zipfile.ZipInfo(name)
                    if symlink:entry.create_system=3;entry.external_attr=(stat.S_IFLNK|0o777)<<16
                    z.writestr(entry,b'content')
            with self.subTest(names=names),self.assertRaises(ValueError):manager.extract_archive(blob.getvalue(),self.base/'unpacked')
        self.assertFalse((self.base/'outside.py').exists())

    def test_normal_github_archive_extracts_without_modifying_data(self):
        blob=io.BytesIO()
        with zipfile.ZipFile(blob,'w') as z:z.writestr('repo-sha/studio.py','# app');z.writestr('repo-sha/themes/cosmos.json','{}')
        manager.extract_archive(blob.getvalue(),self.base/'unpacked')
        self.assertEqual((self.base/'unpacked/studio.py').read_text(),'# app')
        self.assertEqual(self.data.read_text(),'personal content')

    def test_launch_uses_selected_environment_and_shared_data_directory(self):
        installed=self.install();project=self.data
        with patch.object(manager.subprocess,'Popen') as process:manager.launch(self.root,project)
        args=process.call_args
        self.assertIn(str(manager.environment_python(self.root/'releases'/installed['commit'])),args.args[0][0])
        self.assertIn('--project',args.args[0]);self.assertEqual(args.kwargs['env']['ORBITE_DATA_DIR'],str(self.root/'data'))

    def test_ffmpeg_can_come_from_python_wheel_when_system_binary_is_missing(self):
        bundled=Mock();bundled.get_ffmpeg_exe.return_value='/bundled/ffmpeg'
        with patch('runtime.shutil.which',return_value=None),patch.dict('sys.modules',{'imageio_ffmpeg':bundled}):
            self.assertEqual(ffmpeg_executable(),'/bundled/ffmpeg')

if __name__=='__main__':unittest.main()
