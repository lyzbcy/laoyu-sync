"""发布阻断回归：纯隔离假引擎，不读取/写入真实 Syncthing 配置。"""
import copy
import bootstrap
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import wizard
from stmanager import STManager


class FakeClient:
    def __init__(self, folder_status=None, fail_config=False):
        self.last_headers = {}
        self.folder_status = folder_status
        self.fail_config = fail_config
        self.writes = []

    def ready(self):
        return True

    def get(self, path, **kwargs):
        if path == "/rest/system/status":
            return {"myID": "SELF", "uptime": 5}
        if path == "/rest/config":
            if self.fail_config:
                raise RuntimeError("隔离模拟配置读取失败")
            return {"folders": [{"id": "test", "label": "测试", "devices": []}], "devices": [{"deviceID": "SELF"}]}
        if path == "/rest/system/connections":
            return {"total": {}, "connections": {}}
        if path.startswith("/rest/db/status"):
            if self.folder_status is None:
                raise RuntimeError("隔离模拟单项目状态读取失败")
            return copy.deepcopy(self.folder_status)
        raise AssertionError(path)

    def post(self, path, body=None):
        self.writes.append((path, copy.deepcopy(body)))
        return {}


class FakeManager:
    def __init__(self):
        self.client = FakeClient()

    def _maybe_restart(self, response):
        return False

    def pending_folders(self):
        return [{"folderID": "test", "folderLabel": "邀请项目", "deviceID": "REAL", "deviceName": "真来源"}]


class ReleaseContracts(unittest.TestCase):
    def test_empty_project_path_rejected_without_mutation(self):
        manager = FakeManager()
        with self.assertRaises(wizard.WizardError):
            wizard.add_folder_flow(manager, "", "空位置")
        self.assertEqual(manager.client.writes, [])

    def test_wrong_invitation_sender_rejected_without_mutation(self):
        manager = FakeManager()
        with self.assertRaises(wizard.WizardError):
            wizard.accept_folder_flow(manager, "test", "邀请项目", str(Path(__file__).parent), "WRONG")
        self.assertEqual(manager.client.writes, [])

    def test_unreadable_folder_cannot_claim_complete(self):
        manager = STManager.__new__(STManager)
        manager.client = FakeClient()
        manager._rates = {"in": 0, "out": 0}
        manager._sample_speed = lambda value: None
        state = manager.status()
        folder = state["folders"][0]
        self.assertTrue(folder.get("state") in ("error", "unknown", "unavailable") or folder.get("status_ok") is False)
        self.assertTrue(state["total"].get("pct") != 100 or state["total"].get("verified") is False or state["total"].get("complete") is False)

    def test_unreadable_configuration_marks_status_unverified(self):
        manager = STManager.__new__(STManager)
        manager.client = FakeClient(fail_config=True)
        state = manager.status()
        self.assertTrue(state["syncthing"].get("api_ok") is False or state.get("status_ok") is False or state["total"].get("verified") is False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
