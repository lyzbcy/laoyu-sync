import bootstrap
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))
import config
import pet
import pet_control


class FakeProcess:
    def __init__(self):
        self.returncode = None
        self.terminated = False
    def poll(self):
        return self.returncode
    def terminate(self):
        self.terminated = True
        self.returncode = 0
    def wait(self, timeout=None):
        return self.returncode
    def kill(self):
        self.returncode = -9


class PetLifecycleTests(unittest.TestCase):
    def create(self, system='Darwin', ready=True, headless=False):
        processes, calls = [], []
        def spawn(command, **kwargs):
            process = FakeProcess()
            processes.append(process)
            calls.append((command, kwargs))
            if ready:
                Path(kwargs['env']['LAOYU_PET_READY']).write_text('ready')
            else:
                process.returncode = 1
            return process
        controller = pet_control.PetController(8390, system=system, headless=headless, popen=spawn)
        return controller, processes, calls

    def test_mac_starts_once_and_stops_owned_child(self):
        control, processes, calls = self.create()
        control.set_enabled(True)
        control.set_enabled(True)
        self.assertEqual(len(calls), 1)
        self.assertIn('--pet', calls[0][0])
        self.assertNotIn('creationflags', calls[0][1])
        self.assertEqual(calls[0][1]['env']['LAOYU_SYNC_PORT'], '8390')
        self.assertTrue(control.running)
        control.set_enabled(False)
        self.assertTrue(processes[0].terminated)
        self.assertFalse(control.running)
        control.set_enabled(True)
        self.assertEqual(len(processes), 2)
        control.close()

    def test_windows_keeps_no_console_flag(self):
        control, _, calls = self.create('Windows')
        control.set_enabled(True)
        self.assertEqual(calls[0][1]['creationflags'], 0x08000000)
        control.close()

    def test_headless_and_unsupported_platform_do_not_spawn(self):
        for system, headless in [('Darwin', True), ('Linux', False)]:
            control, _, calls = self.create(system, headless=headless)
            control.set_enabled(True)
            self.assertEqual(calls, [])

    def test_failed_start_is_reported_and_can_retry(self):
        control, _, calls = self.create(ready=False)
        with self.assertRaisesRegex(RuntimeError, '小精灵'):
            control.set_enabled(True)
        self.assertFalse(control.running)
        with self.assertRaises(RuntimeError):
            control.set_enabled(True)
        self.assertEqual(len(calls), 2)

    def test_mac_transparency_uses_native_attributes(self):
        root = Mock()
        color = pet.configure_window(root, 'Darwin')
        self.assertEqual(color, 'systemTransparent')
        root.attributes.assert_any_call('-transparent', True)
        self.assertFalse(any(c.args and c.args[0] == '-transparentcolor' for c in root.attributes.call_args_list))

    def test_windows_transparency_is_unchanged(self):
        root = Mock()
        self.assertEqual(pet.configure_window(root, 'Windows'), pet.TRANS)
        root.attributes.assert_any_call('-transparentcolor', pet.TRANS)

    def test_mac_setting_is_not_hidden(self):
        ui = (Path(__file__).resolve().parents[1] / 'ui/app.js').read_text(encoding='utf-8')
        self.assertNotIn('meta.platform !== "Windows"', ui)
        self.assertIn('pet_supported', ui)

    def test_packaged_version_tracks_source(self):
        spec = (Path(__file__).resolve().parents[1] / 'LaoyuSync.spec').read_text(encoding='utf-8')
        self.assertNotIn("'CFBundleShortVersionString':'0.3.6'", spec)
        self.assertIn('__version__', spec)

class PetSettingsTests(unittest.TestCase):
    def test_failed_launch_keeps_preference(self):
        import gateway
        config.set('pet_enabled', False)
        with patch.object(gateway, 'PET_CALLBACK', side_effect=RuntimeError('launch failed')):
            with self.assertRaises(RuntimeError):
                gateway.set_pet_enabled(True)
        self.assertFalse(config.get('pet_enabled'))

    def test_save_failure_restores_cache_and_process(self):
        import gateway
        config.set('pet_enabled', False)
        callback = Mock()
        with patch.object(gateway, 'PET_CALLBACK', callback), patch.object(config, '_save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                gateway.set_pet_enabled(True)
        self.assertFalse(config.get('pet_enabled'))
        self.assertEqual([c.args for c in callback.call_args_list], [(True,), (False,)])

    def test_invalid_setting_rejected(self):
        import gateway
        with patch.object(gateway, 'PET_CALLBACK') as callback:
            for invalid in ['false', 0, None]:
                with self.assertRaises(gateway.WizardError):
                    gateway.set_pet_enabled(invalid)
            callback.assert_not_called()

    def test_close_prevents_late_start(self):
        control, _, calls = PetLifecycleTests().create()
        control.close()
        control.set_enabled(True)
        self.assertEqual(calls, [])

class MacWindowTests(unittest.TestCase):
    def test_mac_position_correction_does_not_call_windows(self):
        app = object.__new__(pet.PetApp)
        app.root = Mock()
        app.root.winfo_rootx.return_value = 0
        app.root.winfo_rooty.return_value = 0
        app.x, app.y = 120, 160
        app._move_mac_window = Mock()
        with patch.object(pet.platform, 'system', return_value='Darwin'):
            app._ensure_position()
        app._move_mac_window.assert_called_once()

    def test_mac_panel_hides_without_moving_offscreen(self):
        app = object.__new__(pet.PetApp)
        app.panel = Mock()
        app.panel_visible = True
        with patch.object(pet.platform, 'system', return_value='Darwin'):
            app._toggle_panel()
        app.panel.withdraw.assert_called_once()
        app.panel.geometry.assert_not_called()

    def test_right_click_close_uses_settings_api(self):
        response = Mock(status=200)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch.object(pet.urllib.request, 'urlopen', return_value=response) as request:
            pet.close_pet()
        import json
        self.assertEqual(json.loads(request.call_args.args[0].data), {'pet_enabled': False})
        self.assertTrue(request.call_args.args[0].full_url.endswith('/api/settings'))
