from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from myrecorder.titles import normalize_title, TitleError, ocr_title, window_title, LectureWindow


class TitleTests(unittest.TestCase):
    def test_filename_cleanup_and_korean(self):
        self.assertEqual(normalize_title('  예시 강의: 1/2?*\n 복습  '),'예시 강의 12 복습')
        self.assertEqual(normalize_title('CON.txt'),'_CON.txt')
    def test_empty_recognition_is_failure_not_replacement(self):
        for text in ('','  \n','<>:"/\\|?*...'):
            with self.subTest(text=text),self.assertRaises(TitleError): normalize_title(text)
    def test_long_title_limit(self): self.assertEqual(len(normalize_title('가'*200)),100)
    def test_window_title_is_read_fresh_and_sanitized(self):
        item=LectureWindow(123,'Example: Lesson / Review',456)
        with patch('myrecorder.titles._api',return_value=object()),patch('myrecorder.titles._read_window',return_value=item):
            self.assertEqual(window_title(123),'Example Lesson  Review')
    def test_closed_window_is_explained(self):
        with patch('myrecorder.titles._api',return_value=object()),patch('myrecorder.titles._read_window',return_value=None):
            with self.assertRaises(TitleError): window_title(123)
    def test_ocr_png_uses_stdin_and_normalizes_text(self):
        calls=[SimpleNamespace(returncode=0,stdout=b'List\neng\nkor\n'),
               SimpleNamespace(returncode=0,stdout='예시: 강의\n첫 시간'.encode())]
        with patch('myrecorder.titles.tesseract_path',return_value='tesseract'),patch('myrecorder.titles.subprocess.run',side_effect=calls) as run:
            self.assertEqual(ocr_title(b'PNG'),'예시 강의 첫 시간')
        self.assertEqual(run.call_args.kwargs['input'],b'PNG')
        self.assertEqual(run.call_args.args[0][1:3],['stdin','stdout'])
    def test_missing_ocr_language_is_actionable(self):
        with patch('myrecorder.titles.tesseract_path',return_value='tesseract'),patch('myrecorder.titles.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=b'eng\n')):
            with self.assertRaisesRegex(TitleError,'언어 데이터'): ocr_title(b'PNG','kor')
    def test_ocr_timeout(self):
        with patch('myrecorder.titles.tesseract_path',return_value='tesseract'),patch('myrecorder.titles.subprocess.run',side_effect=subprocess.TimeoutExpired('tesseract',10)):
            with self.assertRaisesRegex(TitleError,'시간이 초과'): ocr_title(b'PNG')
    def test_ocr_failure_does_not_become_a_title(self):
        with patch('myrecorder.titles.tesseract_path',return_value='tesseract'),patch('myrecorder.titles.subprocess.run',side_effect=[SimpleNamespace(returncode=0,stdout=b'eng\n'),SimpleNamespace(returncode=1,stdout=b'bad title')]):
            with self.assertRaises(TitleError): ocr_title(b'PNG','eng')
    def test_missing_ocr_executable(self):
        from myrecorder.titles import tesseract_path
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(TitleError): tesseract_path(Path(d)/'missing.exe')


if __name__=='__main__': unittest.main()
