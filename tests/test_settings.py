from pathlib import Path
import errno
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from myrecorder.settings import (SettingsStore, StoragePaths, StorageError, check_windows_path,
                                 storage_directory, prepare_storage, application_root, check_windows_drive)
from myrecorder.media import publish


class StorageTests(unittest.TestCase):
    def test_explicit_defaults_and_persistence(self):
        with tempfile.TemporaryDirectory(prefix='설정 공백 ') as d:
            store = SettingsStore(Path(d))
            self.assertEqual(store.load().recordings, r'F:\MyRecorder\Recordings')
            self.assertFalse((Path(d)/'F:').exists())
            custom=StoragePaths(r'G:\강의 영상',r'G:\변환 영상',r'G:\임시 영상')
            store.save(custom)
            self.assertEqual(SettingsStore(Path(d)).load(),custom)
            self.assertEqual(json.loads(store.path.read_text())['storage']['temp'],r'G:\임시 영상')

    def test_bad_config_does_not_reset(self):
        with tempfile.TemporaryDirectory() as d:
            store=SettingsStore(Path(d))
            for bad in ['{broken', '[]', '{"version":1,"storage":[]}']:
                store.path.write_text(bad)
                with self.assertRaises(StorageError): store.load()
                self.assertEqual(store.path.read_text(),bad)

    def test_create_three_folders_and_reject_development(self):
        with tempfile.TemporaryDirectory(prefix='저장 공백 ') as d:
            root=Path(d); dev=root/'개발 폴더'; dev.mkdir()
            paths=StoragePaths(str(root/'녹화'),str(root/'변환'),str(root/'임시'))
            result=prepare_storage(paths,dev)
            self.assertEqual(len(result),3)
            self.assertTrue(all(p.is_dir() for p in result.values()))
            self.assertFalse(any(root.rglob('.myrecorder-write-test-*')))
            with self.assertRaises(StorageError): storage_directory(dev/'videos',dev)
            with self.assertRaises(StorageError): storage_directory(root/'OneDrive - Org'/'임시',dev)
            self.assertFalse((dev/'videos').exists())

    def test_windows_absolute_policy(self):
        dev=r'C:\Users\ExampleUser\OneDrive\바탕 화면\allthetest\myrecorder'
        for allowed in [r'F:\MyRecorder\Recordings',r'G:\강의 영상',r'\\nas\share\녹화']:
            check_windows_path(allowed,dev)
        for denied in ['', 'Recordings',r'F:Recordings',dev+r'\videos',r'C:\Users\ExampleUser\OneDrive\녹화',r'\\?\F:\Temp']:
            with self.subTest(denied=denied), self.assertRaises(StorageError):
                check_windows_path(denied,dev)
        with self.assertRaises(StorageError):
            check_windows_path(r'D:\dev\sub\..\videos',r'D:\dev')

    def test_inaccessible_path_has_no_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); dev=root/'dev'; dev.mkdir()
            blocked=root/'file'; blocked.write_text('not a directory')
            with self.assertRaises(StorageError):
                prepare_storage(StoragePaths(str(blocked/'recordings'),str(blocked/'converted'),str(blocked/'temp')),dev)
            self.assertEqual(list(dev.iterdir()),[])
            with self.assertRaises(StorageError): storage_directory('relative',dev)

    def test_root_is_not_current_directory(self):
        with tempfile.TemporaryDirectory(prefix='한글 실행 ') as d:
            with patch.dict(os.environ,{'MYRECORDER_HOME':d}):
                self.assertEqual(application_root(),Path(d).resolve())

    def test_windows_missing_drive_no_substitute(self):
        checked=[]
        def missing(anchor):
            checked.append(anchor)
            return False
        with self.assertRaises(StorageError):
            check_windows_drive(r'F:\MyRecorder\Recordings',missing)
        self.assertEqual(checked, ['F:\\'])

    def test_cross_drive_publish(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); source=root/'source.mp4'; source.write_bytes(b'video')
            output=root/'출력 폴더'; output.mkdir()
            real_replace=os.replace
            def replace(src,dest):
                if Path(src)==source: raise OSError(errno.EXDEV,'different device')
                real_replace(src,dest)
            with patch('myrecorder.media.os.replace',side_effect=replace):
                final=publish(source,output,'강의 제목')
            self.assertEqual(final.read_bytes(),b'video')
            self.assertFalse(source.exists())
            self.assertFalse(list(output.glob('*.partial')))


if __name__=='__main__': unittest.main()
