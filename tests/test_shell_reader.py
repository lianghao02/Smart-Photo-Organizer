"""Windows Shell 輔助程序的回應期限與真實捷徑回歸。"""

import concurrent.futures
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main import DateParser, WinShellReader
from PIL import Image
from smart_photo_organizer.v3_pipeline import AnalysisOptions, V3Pipeline


@unittest.skipUnless(os.name == 'nt', '需要 Windows Shell')
class ShellReaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='Shell 測試 空白 ')
        self.root = Path(self.temporary.name)
        self.target = self.root / '來源 中文.txt'
        self.target.write_text('只供合成驗證', encoding='utf-8')
        self.original_hash = hashlib.sha256(self.target.read_bytes()).hexdigest()
        self.reader = WinShellReader()

    def tearDown(self):
        self.reader.stop()
        self.assertEqual(hashlib.sha256(self.target.read_bytes()).hexdigest(), self.original_hash)
        self.temporary.cleanup()

    def test_unresponsive_helper_returns_failure_and_is_reaped(self):
        original_popen = subprocess.Popen
        children = []

        def silent_helper(*args, **kwargs):
            proc = original_popen([sys.executable, '-c', 'import time; time.sleep(30)'], **kwargs)
            children.append(proc)
            return proc

        self.reader.response_timeout = 0.25
        results = []
        with patch('main.subprocess.Popen', side_effect=silent_helper):
            worker = threading.Thread(target=lambda: results.append(
                self.reader.create_shortcut(str(self.root / '故障.lnk'), str(self.target))), daemon=True)
            begin = time.monotonic()
            worker.start()
            worker.join(2)
            completed = not worker.is_alive()
            self.reader.stop()
            worker.join(2)
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=3)
        self.assertTrue(completed, '沒有回應時必須在期限內返回，不可無限阻塞')
        self.assertEqual(results, [False])
        self.assertLess(time.monotonic() - begin, 4)
        self.assertIsNone(self.reader.proc)

    def test_repeated_real_shortcuts_and_restart(self):
        for index in range(3):
            link = self.root / f'捷徑 {index}.lnk'
            self.assertTrue(self.reader.create_shortcut(str(link), str(self.target)))
            self.assertEqual(Path(self.reader.resolve_shortcut(str(link))), self.target)
        old_process = self.reader.proc
        self.reader.stop()
        self.assertIsNotNone(old_process.poll())
        self.assertTrue(self.reader.create_shortcut(str(self.root / '重啟.lnk'), str(self.target)))

    def test_concurrent_requests_remain_paired(self):
        def create_and_resolve(index):
            target = self.root / f'來源 {index}.txt'
            target.write_text(str(index), encoding='utf-8')
            link = self.root / f'並行 {index}.lnk'
            return self.reader.create_shortcut(str(link), str(target)), self.reader.resolve_shortcut(str(link)), str(target)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            for created, resolved, target in pool.map(create_and_resolve, range(6)):
                self.assertTrue(created)
                self.assertEqual(Path(resolved), Path(target))

    def test_metadata_and_missing_link(self):
        self.assertTrue(self.reader.get_properties(str(self.target))['success'])
        self.assertIsNone(self.reader.resolve_shortcut(str(self.root / '不存在.lnk')))

    def test_start_is_idempotent(self):
        self.reader.start()
        proc = self.reader.proc
        self.reader.start()
        self.assertIs(self.reader.proc, proc)

    def test_blocked_large_write_also_times_out(self):
        original_popen = subprocess.Popen
        def silent_helper(*args, **kwargs):
            return original_popen([sys.executable, '-c', 'import time; time.sleep(30)'], **kwargs)
        self.reader.response_timeout = 0.25
        begin = time.monotonic()
        with patch('main.subprocess.Popen', side_effect=silent_helper):
            self.assertFalse(self.reader.create_shortcut('x' * 30000, str(self.target)))
        self.assertLess(time.monotonic() - begin, 3)
        self.assertIsNone(self.reader.proc)

    def test_stderr_flood_cannot_block_response(self):
        original_popen = subprocess.Popen
        program = "import sys; sys.stdin.readline(); sys.stderr.write('x'*100000); sys.stderr.flush(); print('eyJzdWNjZXNzIjp0cnVlfQ==',flush=True)"
        def noisy_helper(*args, **kwargs):
            return original_popen([sys.executable, '-c', program], **kwargs)
        with patch('main.subprocess.Popen', side_effect=noisy_helper):
            self.assertTrue(self.reader.create_shortcut(str(self.root / '噪音.lnk'), str(self.target)))

    def test_pipeline_folder_and_zip_repeat_with_real_shell(self):
        source = self.root / '照片來源'
        source.mkdir()
        image = source / 'capture.png'
        Image.new('RGB', (1080, 2400), 'white').save(image)
        sidecar = source / 'capture.png.json'
        sidecar.write_text('{"photoTakenTime":{"timestamp":"1463711400"}}', encoding='utf-8')
        archive = self.root / 'Takeout 中文.zip'
        with zipfile.ZipFile(archive, 'w') as handle:
            handle.write(image, 'Takeout/相簿/capture.png')
            handle.write(sidecar, 'Takeout/相簿/capture.png.json')
        originals = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (image, sidecar, archive)}
        for mode, input_path in (('folder', source), ('takeout_zip', archive)):
            for round_number in range(2):
                destination = self.root / f'輸出 {mode} {round_number}'
                pipeline = V3Pipeline(str(input_path), str(destination), mode, self.reader, DateParser())
                summary = pipeline.analyze(AnalysisOptions(blur_enabled=False, short_video_enabled=False, similar_enabled=False))
                self.assertEqual(summary.errors, [])
                self.assertEqual(summary.media_group_count, 1)
                self.assertEqual(summary.category_counts.get('SCREENSHOT'), 1)
                links = list(destination.rglob('*.lnk'))
                self.assertTrue(links)
                for link in links:
                    self.assertTrue(Path(self.reader.resolve_shortcut(str(link))).is_file())
                self.reader.stop()
        for path, expected in originals.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected)


if __name__ == '__main__':
    unittest.main()
