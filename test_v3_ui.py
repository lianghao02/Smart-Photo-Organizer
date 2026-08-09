# -*- coding: utf-8 -*-
"""v3.0 非技術 UI 與 WebBridge 安全契約測試。"""

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.modules.setdefault("webview", types.ModuleType("webview"))

import main as app_main


PROJECT_ROOT = Path(__file__).resolve().parent


class _FakePipeline:
    instances = []

    def __init__(self, source_path, destination_root, source_mode, *args, **kwargs):
        self.source_path = os.path.abspath(source_path)
        self.destination_root = os.path.abspath(destination_root)
        self.source_mode = source_mode
        self.closed = False
        self.__class__.instances.append(self)

    def close(self):
        self.closed = True


class TestV3UI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (PROJECT_ROOT / "index.html").read_text(encoding="utf-8")

    def test_ui_exposes_only_v3_safe_workflow(self):
        for test_id in (
            "source-path",
            "destination-path",
            "browse-source",
            "browse-zip",
            "start-analysis",
            "process-pending",
            "archive-by-date",
        ):
            self.assertIn(f'data-testid="{test_id}"', self.html)
        for api_name in (
            "start_v3_analysis",
            "preview_quarantine",
            "execute_quarantine",
            "preview_archive",
            "execute_archive",
        ):
            self.assertIn(f"pywebview.api.{api_name}", self.html)

    def test_ui_states_product_safety_contract(self):
        self.assertIn("開始分析不會搬移原始檔", self.html)
        self.assertIn("程式不提供永久刪除", self.html)
        self.assertIn("Google Takeout ZIP 永遠唯讀", self.html)
        self.assertIn("99_待刪除", self.html)
        self.assertIn("Quarantine", self.html)
        self.assertNotIn("OneDrive", self.html)
        self.assertNotIn("Google Drive 防下載", self.html)

    def test_bridge_rejects_mutating_actions_while_analysis_is_busy(self):
        bridge = app_main.WebBridge()
        bridge._v3_busy = True
        config = {"source_dir": "x", "dest_dir": "y", "source_mode": "folder"}
        for method_name in (
            "preview_quarantine",
            "execute_quarantine",
            "preview_archive",
            "execute_archive",
        ):
            result = getattr(bridge, method_name)(config)
            self.assertIn("分析仍在執行", result["error"])

    def test_exclusive_action_releases_busy_state_after_failure(self):
        bridge = app_main.WebBridge()

        def fail():
            raise OSError("測試失敗")

        with self.assertRaisesRegex(OSError, "測試失敗"):
            bridge._run_v3_exclusive(fail)
        self.assertFalse(bridge._v3_busy)

    def test_bridge_closes_previous_pipeline_when_paths_change(self):
        _FakePipeline.instances.clear()
        with tempfile.TemporaryDirectory() as root:
            source_a = os.path.join(root, "來源甲")
            source_b = os.path.join(root, "來源乙")
            destination = os.path.join(root, "目標")
            wrong_file = os.path.join(root, "不是壓縮檔.txt")
            os.makedirs(source_a)
            os.makedirs(source_b)
            os.makedirs(destination)
            Path(wrong_file).write_text("x", encoding="utf-8")
            bridge = app_main.WebBridge()
            with self.assertRaisesRegex(ValueError, "一般資料夾模式"):
                bridge._v3_config_paths({
                    "source_dir": wrong_file,
                    "dest_dir": destination,
                    "source_mode": "folder",
                })
            with self.assertRaisesRegex(ValueError, "Takeout 模式"):
                bridge._v3_config_paths({
                    "source_dir": wrong_file,
                    "dest_dir": destination,
                    "source_mode": "takeout_zip",
                })
            with patch.object(app_main, "V3Pipeline", _FakePipeline):
                first = bridge._get_v3_pipeline({
                    "source_dir": source_a,
                    "dest_dir": destination,
                    "source_mode": "folder",
                })
                second = bridge._get_v3_pipeline({
                    "source_dir": source_b,
                    "dest_dir": destination,
                    "source_mode": "folder",
                })
        self.assertIsNot(first, second)
        self.assertTrue(first.closed)


if __name__ == "__main__":
    unittest.main()
