import bootstrap
import json
from pathlib import Path
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))
import config
import gateway
import network_check
import stmanager

TASKLIST = (
    '"syncthing.exe","13952","Console","1","134,964 K"\r\n'
    '"syncthing.exe","7860","Console","1","7,900 K"\r\n'
    '"iKuuuVPNCore.exe","18648","Services","0","44,684 K"\r\n'
    '"LaoyuSync.exe","27300","Console","1","110,792 K"\r\n'
)
NETSTAT = (
    '  TCP    192.168.20.79:57812    27.152.72.251:22067    ESTABLISHED    13952\r\n'
    '  TCP    192.168.20.79:22000    192.168.20.112:22000    ESTABLISHED    13952\r\n'
    '  TCP    [::1]:8384    [::1]:49152    ESTABLISHED    27300\r\n'
    '  TCP    127.0.0.1:7890    0.0.0.0:0    LISTENING    18648\r\n'
)
ROUTE_OK = ('{"default":[{"alias":"以太网","desc":"Realtek PCIe GbE Family Controller",'
            '"hop":"192.168.20.1"}],"cover":[]}')
ROUTE_TUN = ('{"default":[{"alias":"Clash","desc":"Clash Virtual Adapter","hop":"198.18.0.1"}],'
             '"cover":["1.0.0.0/8","128.0.0.0/8"]}')
# 中文系统里虚拟网卡的接口名是本地化的「以太网 2」，TAP 字样只在描述里。
ROUTE_TAP = ('{"default":[{"alias":"以太网 2","desc":"TAP-Windows Adapter V9","hop":"10.8.0.1"}],'
             '"cover":[]}')
PREFERENCE_EXTERNAL = {'mode': 'direct', 'state': 'external_or_stopped',
                       'note': '', 'caveat': '', 'verified_direct': False}
PREFERENCE_APPLIED = {'mode': 'direct', 'state': 'applied',
                      'note': '', 'caveat': '', 'verified_direct': False}


def fake_run(tasklist=TASKLIST, netstat=NETSTAT, route=ROUTE_OK):
    def dispatch(command, timeout=8):
        if command[0] == 'tasklist':
            return tasklist
        if command[0] == 'netstat':
            return netstat
        if command[0].endswith('powershell.exe'):
            return route
        raise AssertionError('unexpected command: %r' % (command,))
    return dispatch


class NetworkCheckTests(unittest.TestCase):
    def test_parsers_split_quoted_csv_and_only_established_tcp(self):
        processes = network_check.parse_tasklist_csv(TASKLIST)
        self.assertEqual(processes[13952], 'syncthing.exe')
        self.assertEqual(processes[18648], 'ikuuuvpncore.exe')
        conns = network_check.parse_netstat(NETSTAT)
        self.assertEqual(len(conns), 3)  # LISTENING 行不算连接
        self.assertEqual(conns[0]['remote'], ('27.152.72.251', 22067))
        self.assertEqual(conns[2]['remote'], ('::1', 49152))

    def test_route_snapshot_accepts_scalar_json_and_flags_takeover(self):
        scalar = network_check.parse_route_snapshot(
            '{"default":{"alias":"以太网","desc":"Realtek PCIe GbE Family Controller","hop":"192.168.20.1"},'
            '"cover":"1.0.0.0/8"}')
        self.assertEqual(scalar['default'], ['以太网（Realtek PCIe GbE Family Controller）'])
        self.assertEqual(scalar['next_hop'], ['192.168.20.1'])
        self.assertEqual(network_check.parse_route_snapshot('not json')['default'], [])
        self.assertEqual(network_check.check_takeover(scalar)['level'], 'pass')
        tun = network_check.parse_route_snapshot(ROUTE_TUN)
        takeover = network_check.check_takeover(tun)
        self.assertEqual(takeover['level'], 'warn')
        self.assertIn('无法绕过', takeover['conclusion'])
        # 接口名本地化（以太网 2）但描述含 TAP，同样算接管迹象。
        self.assertEqual(network_check.check_takeover(
            network_check.parse_route_snapshot(ROUTE_TAP))['level'], 'warn')

    def test_engine_connection_to_local_proxy_port_is_fail(self):
        conns = [{'remote': ('127.0.0.1', 7890), 'local': ('192.168.20.79', 0), 'pid': 1},
                 {'remote': ('27.152.72.251', 22067), 'local': ('192.168.20.79', 0), 'pid': 1}]
        result = network_check.check_proxy_connections(conns, set())
        self.assertEqual(result['level'], 'fail')
        self.assertIn('7890', result['evidence'])
        # 环境变量指向的代理端口同样算显式代理（不限于常见端口表）。
        env_hit = network_check.check_proxy_connections(
            conns[:1], {('127.0.0.1', 7890)})
        self.assertEqual(env_hit['level'], 'fail')
        clean = network_check.check_proxy_connections(conns[1:], set())
        self.assertEqual(clean['level'], 'pass')

    def test_proxy_targets_from_env_covers_case_and_schemes(self):
        env = {'HTTP_PROXY': 'http://127.0.0.1:9999',
               'all_proxy': 'socks5://127.0.0.1:1080', 'KEEP': 'x'}
        self.assertEqual(network_check.proxy_targets_from_env(env),
                         {('127.0.0.1', 9999), ('127.0.0.1', 1080)})

    def test_relay_trace_levels_by_target_intersection(self):
        processes = {100: 'syncthing.exe', 200: 'clash.exe'}
        engine = [{'remote': ('27.152.72.251', 22067), 'local': ('192.168.20.79', 0), 'pid': 100}]
        self.assertEqual(network_check.check_relay_trace(engine, [], {100}, {})['level'], 'pass')
        disjoint = [{'remote': ('114.94.203.35', 19274), 'local': ('192.168.20.79', 0), 'pid': 200}]
        self.assertEqual(network_check.check_relay_trace(engine, disjoint, {100}, processes)['level'], 'pass')
        shared = disjoint + [{'remote': ('27.152.72.251', 22067), 'local': ('192.168.20.79', 0), 'pid': 200}]
        warn = network_check.check_relay_trace(engine, shared, {100}, processes)
        self.assertEqual(warn['level'], 'warn')
        self.assertIn('27.152.72.251', warn['evidence'])
        # 只有私网目标（局域网 / Tailscale 网段）时无从比对，不算通过也不算失败。
        private = [{'remote': ('fd7a:115c:a1e0::6133', 22000), 'local': ('192.168.20.79', 0), 'pid': 100}]
        self.assertEqual(network_check.check_relay_trace(private, shared, {100}, processes)['level'], 'info')

    def test_engine_check_states_carry_actions(self):
        external = network_check.check_engine(PREFERENCE_EXTERNAL)
        self.assertEqual(external['level'], 'warn')
        self.assertTrue(external['action'])
        applied = network_check.check_engine(PREFERENCE_APPLIED)
        self.assertEqual(applied['level'], 'pass')
        restart = network_check.check_engine({'mode': 'direct', 'state': 'restart_required'})
        self.assertIn('重新打开小助手', restart['action'])

    def run_report(self, preference, **outputs):
        with patch.object(stmanager, 'network_preference', return_value=preference), \
             patch.object(network_check, '_windows', return_value=True), \
             patch.object(network_check, '_system_proxy_text', return_value=None), \
             patch.object(network_check, '_run', side_effect=fake_run(**outputs)):
            return network_check.run()

    def test_run_aggregates_levels_and_never_claims_verified(self):
        report = self.run_report(PREFERENCE_APPLIED)
        # 引擎 applied + 连接干净 + 无共享目标 + 物理默认路由 → 整体 pass。
        self.assertEqual(report['summary']['level'], 'pass')
        self.assertIn('旁证', report['summary']['text'])
        self.assertIn('连接记录', report['summary']['text'])
        self.assertNotIn('已验证', json.dumps(report, ensure_ascii=False))

    def test_run_external_engine_and_proxy_traffic_drive_summary(self):
        report = self.run_report(PREFERENCE_EXTERNAL)
        self.assertEqual(report['summary']['level'], 'warn')
        self.assertTrue(report['engine_running'])  # 前端据此显示一键接管按钮
        ids = {c['id'] for c in report['checks']}
        self.assertEqual(ids, {'engine', 'proxy_conn', 'relay_trace', 'takeover', 'sysproxy'})
        proxied = ('  TCP    192.168.20.79:57812    127.0.0.1:7890    ESTABLISHED    13952\r\n')
        report = self.run_report(PREFERENCE_APPLIED, netstat=proxied)
        self.assertEqual(report['summary']['level'], 'fail')

    def test_run_snapshot_failure_degrades_to_info_not_error(self):
        def broken(command, timeout=8):
            raise OSError('tool unavailable')
        with patch.object(stmanager, 'network_preference', return_value=PREFERENCE_APPLIED), \
             patch.object(network_check, '_windows', return_value=True), \
             patch.object(network_check, '_run', side_effect=broken):
            report = network_check.run()
        conn = next(c for c in report['checks'] if c['id'] == 'proxy_conn')
        self.assertEqual(conn['level'], 'info')
        # 快照失败不把整体拖成 fail，也不假装检测通过。
        self.assertEqual(report['summary']['level'], 'pass')

    def test_run_non_windows_reports_unsupported_instead_of_guessing(self):
        with patch.object(stmanager, 'network_preference', return_value=PREFERENCE_APPLIED), \
             patch.object(network_check, '_windows', return_value=False), \
             patch.object(stmanager, 'process_running', return_value=False):
            report = network_check.run()
        ids = {c['id'] for c in report['checks']}
        self.assertEqual(ids, {'engine', 'proxy_conn', 'takeover', 'sysproxy'})
        for item in report['checks']:
            if item['id'] in ('proxy_conn', 'takeover', 'sysproxy'):
                self.assertEqual(item['level'], 'info')
        self.assertFalse(report['engine_running'])

    def test_http_check_requires_auth_and_returns_payload(self):
        with patch.object(config, 'CONFIG_PATH', config.DATA_DIR / 'config.json'), patch.object(config, '_cache', None):
            config._cache = None
            token = config.get('token')
            canned = {'mode': 'direct', 'state': 'applied', 'generated_at': 1,
                      'summary': {'level': 'pass', 'text': 'x'}, 'checks': [], 'note': 'n'}
            server = gateway.ThreadingHTTPServer(('127.0.0.1', 0), gateway.make_handler(Mock()))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

            def request(path, auth=True):
                req = urllib.request.Request(base + path,
                                             headers={'X-Token': token if auth else ''})
                return json.loads(opener.open(req, timeout=5).read())
            try:
                with self.assertRaises(urllib.error.HTTPError) as error:
                    request('/api/network-check', auth=False)
                self.assertEqual(error.exception.code, 401)
                with patch.object(gateway.network_check, 'run', return_value=canned):
                    self.assertEqual(request('/api/network-check'), canned)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(3)


class EngineTakeoverTests(unittest.TestCase):
    def test_shutdown_external_refuses_non_loopback_and_reports_delivery_failure(self):
        with patch.object(stmanager, 'read_gui_config', return_value=('http://192.168.1.5:8384', 'key')):
            stopped, reason = stmanager.shutdown_external()
            self.assertFalse(stopped)
            self.assertIn('本机', reason)
        with patch.object(stmanager, 'read_gui_config', return_value=('http://127.0.0.1:8384', 'key')), \
             patch.object(stmanager, 'api_open', side_effect=OSError('refused')):
            stopped, reason = stmanager.shutdown_external()
            self.assertFalse(stopped)
            self.assertIn('未能送达', reason)

    def test_shutdown_external_polls_until_engine_exits(self):
        with patch.object(stmanager, 'read_gui_config', return_value=('http://127.0.0.1:8384', 'key')), \
             patch.object(stmanager, 'api_open'), \
             patch.object(stmanager, 'process_running', side_effect=[True, True, False]):
            self.assertEqual(stmanager.shutdown_external(), (True, ''))

    def _server(self, mgr):
        server = gateway.ThreadingHTTPServer(('127.0.0.1', 0), gateway.make_handler(mgr))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def test_takeover_endpoint_requires_auth_and_only_starts_after_clean_stop(self):
        config._cache = None
        token = config.get('token')
        mgr = Mock()
        server, thread = self._server(mgr)
        base = f'http://127.0.0.1:{server.server_port}'
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def post(path, auth=True):
            req = urllib.request.Request(base + path, data=b'{}', method='POST',
                                         headers={'X-Token': token if auth else '',
                                                  'Content-Type': 'application/json'})
            try:
                return json.loads(opener.open(req, timeout=5).read())
            except urllib.error.HTTPError as exc:
                return {'http_error': exc.code}

        def wait_started(timeout=3.0):
            # 接管成功后由后台线程启动引擎；等它落地再断言（不 patch 全局
            # threading——那会连测试服务器自己的请求线程一起废掉）。
            deadline = time.time() + timeout
            while time.time() < deadline and not mgr.ensure_running.called:
                time.sleep(0.05)
            return mgr.ensure_running.called
        try:
            self.assertEqual(post('/api/engine/takeover', auth=False), {'http_error': 401})
            # 退出失败（被守护/送达失败）→ 409，且绝不启动第二个引擎造成端口冲突。
            with patch.object(gateway.stmanager, 'process_running', return_value=True), \
                 patch.object(gateway.stmanager, 'shutdown_external', return_value=(False, '被守护')):
                self.assertEqual(post('/api/engine/takeover'), {'http_error': 409})
                self.assertFalse(wait_started(0.5))
            # 优雅退出成功 → 启动小助手自己的引擎。
            with patch.object(gateway.stmanager, 'process_running', return_value=True), \
                 patch.object(gateway.stmanager, 'shutdown_external', return_value=(True, '')):
                self.assertEqual(post('/api/engine/takeover'),
                                 {'ok': True, 'stopped_external': True})
                self.assertTrue(wait_started())
            # 没有外部引擎在跑时不做退出动作，直接启动。
            with patch.object(gateway.stmanager, 'process_running', return_value=False), \
                 patch.object(gateway.stmanager, 'shutdown_external') as shutdown:
                self.assertEqual(post('/api/engine/takeover'),
                                 {'ok': True, 'stopped_external': False})
                shutdown.assert_not_called()
                self.assertTrue(wait_started())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)


if __name__ == '__main__':
    unittest.main()
