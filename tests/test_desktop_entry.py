"""Check the local gateway and the pet's double-click dispatch."""

import bootstrap
import http.client
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))
import app
import gateway
import pet


class DesktopEntry(unittest.TestCase):
    def setUp(self):
        self.server = gateway.start(Mock(), 0)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, token=None, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        headers = {'Content-Type': 'application/json'}
        if token is not None:
            headers['X-Token'] = token
        try:
            conn.request(method, path, json.dumps(body) if body is not None else None, headers)
            response = conn.getresponse()
            return response.status, response.read().decode('utf-8')
        finally:
            conn.close()

    def test_activation_requires_auth_and_a_known_route(self):
        callback = Mock()
        with patch.object(gateway, 'WINDOW_CALLBACK', callback):
            self.assertEqual(401, self.request('POST', '/api/window/show', body={})[0])
            token = gateway.config.get('token')
            self.assertEqual(400, self.request('POST', '/api/window/show', token, {'route': 'https://example.com'})[0])
            callback.assert_not_called()
            self.assertEqual(200, self.request('POST', '/api/window/show', token, {})[0])
            self.assertEqual(200, self.request('POST', '/api/window/show', token, {'route': '#/folders'})[0])
            self.assertEqual([('',), ('#/folders',)], [call.args for call in callback.call_args_list])
        with patch.object(gateway, 'WINDOW_CALLBACK', None):
            self.assertEqual(409, self.request('POST', '/api/window/show', token, {})[0])

    def test_double_click_cancels_panel_and_opens_desktop(self):
        pet_app = pet.PetApp.__new__(pet.PetApp)
        pet_app.root = Mock()
        pet_app._drag = (0, 0)
        pet_app._click_job = 'panel-job'
        with patch.object(pet, 'open_desktop') as activate:
            pet_app._on_dbl(None)
            pet_app._on_release(None)
        activate.assert_called_once_with()
        pet_app.root.after_cancel.assert_called_once_with('panel-job')
        pet_app.root.after.assert_not_called()

    def test_windows_restores_only_minimized_window(self):
        window = Mock()
        with patch.object(app.platform, 'system', return_value='Windows'):
            window.native.WindowState.ToString.return_value = 'Maximized'
            app.show_desktop_window(window, '')
            window.restore.assert_not_called()
            window.run_js.assert_not_called()
            window.native.WindowState.ToString.return_value = 'Minimized'
            app.show_desktop_window(window, '#/devices')
        window.restore.assert_called_once_with()
        self.assertEqual(2, window.show.call_count)
        window.run_js.assert_called_once_with('location.hash = "#/devices"')

    def test_agent_guide_is_served_without_exposing_authenticated_api(self):
        status, guide = self.request('GET', '/agent/SKILL.md')
        self.assertEqual(200, status)
        self.assertIn('GET /api/sync-diagnose', guide)
        self.assertIn('POST /api/sync-repair', guide)
        self.assertNotIn(gateway.config.get('token'), guide)
        self.assertEqual(401, self.request('GET', '/api/status')[0])
