"""Windows 更新占用回归：应用与其探测子进程不得以安装目录为 CWD。

实机取证（verification/win-037，2026-10-15）：0.3.6 的引擎探测 powershell
每约 2 秒被孵化一次、继承安装目录为 CWD 并存活约 2 秒，安装目录被近乎连续
占用；更新 helper 只等待旧主进程 PID，备份改名 5/5 必现 WinError 32 后回滚。
根因修复分三层：启动即迁离 CWD、探测子进程显式 cwd、更新 helper 显式 cwd
（后者见 test_update_transaction.py）。
"""
import os
import sys
import tempfile
import unittest
import bootstrap
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))
import config


class CwdRelocation(unittest.TestCase):
    def setUp(self):
        self._previous_cwd = Path.cwd()

    def tearDown(self):
        os.chdir(self._previous_cwd)

    def test_relocate_cwd_moves_process_out_of_install_dir(self):
        with tempfile.TemporaryDirectory() as fake_install:
            try:
                os.chdir(fake_install)
                config.relocate_cwd()
                self.assertEqual(Path.cwd(), config.DATA_DIR)
                self.assertNotEqual(Path.cwd(), Path(fake_install).resolve())
            finally:
                os.chdir(self._previous_cwd)

    def test_relocate_cwd_creates_missing_data_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / 'not-created-yet'
            with patch.object(config, 'DATA_DIR', missing):
                config.relocate_cwd()
            self.assertTrue(missing.is_dir())
            self.assertEqual(Path.cwd().resolve(), missing.resolve())
            os.chdir(self._previous_cwd)

    @unittest.skipUnless(sys.platform == 'win32', 'powershell 探针仅在 Windows 存在')
    def test_engine_probes_spawn_with_data_dir_cwd(self):
        import stmanager
        captured = []

        class ProbeResult:
            stdout = b'[]'
            returncode = 0

        def fake_run(args, **kwargs):
            captured.append(kwargs)
            return ProbeResult()

        with patch.object(stmanager.subprocess, 'run', side_effect=fake_run):
            stmanager.running_config_home()
            stmanager.selected_engine_running(Path(config.DATA_DIR))
        for kwargs in captured:
            self.assertEqual(kwargs.get('cwd'), str(config.DATA_DIR))


if __name__ == '__main__':
    unittest.main(verbosity=2)
