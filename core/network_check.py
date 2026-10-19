"""core/network_check.py — 同步直连自检：收集本机旁证，不声称已验证直连。

数据来源只有三类：系统命令输出（tasklist / netstat / PowerShell CIM）、助手
自身记录的引擎归属状态、当前进程环境里的代理变量。结论只描述"发现的痕迹"：
本地查不到代理软件内部的规则命中（DIRECT 还是节点），最终仍以代理软件的
连接记录为准（docs/sync-network.md 第 13 行的验收口径）。
"""
import ipaddress
import json
import os
import platform
import subprocess
import time
import urllib.parse

import activity
import stmanager
import sync_network

# 常见代理内核进程名片段（小写子串匹配，宁可多报 warn 也不漏报）。
PROXY_PROCESS_HINTS = ('clash', 'mihomo', 'verge', 'sing-box', 'singbox', 'v2ray',
                       'xray', 'ikuuu', 'shadowsocks', 'trojan', 'hysteria', 'naico')
# 常见本地代理端口；命中即视为引擎在用显式代理（不区分内核品牌）。
COMMON_PROXY_PORTS = {7890, 7891, 7892, 7893, 1080, 1081, 2080, 8080, 8118,
                      8888, 10808, 10809}
# 虚拟适配器名称片段：默认路由落到这类接口说明系统层接管，删环境变量绕不过。
VIRTUAL_ADAPTER_HINTS = ('tun', 'tap', 'wintun', 'wireguard', 'openvpn', 'tailscale',
                         'zerotier', 'clash', 'mihomo', 'sing-box', 'v2ray', 'utun')

LEVEL_ORDER = {'pass': 0, 'info': 1, 'warn': 2, 'fail': 3}


def _windows():
    return platform.system() == 'Windows'


def _run(command, timeout=8):
    kwargs = {}
    if platform.system() == 'Windows':
        kwargs['creationflags'] = 0x08000000  # CREATE_NO_WINDOW
    result = subprocess.run(command, capture_output=True, timeout=timeout, **kwargs)
    return result.stdout.decode('utf-8-sig', errors='replace')


def _item(item_id, level, title, evidence, conclusion, action=''):
    return {'id': item_id, 'level': level, 'title': title, 'evidence': evidence,
            'conclusion': conclusion, 'action': action}


# ---------- 系统命令输出解析（纯函数，供单测直接构造输入） ----------

def parse_tasklist_csv(text):
    """tasklist /FO CSV /NH → {pid(int): 进程名小写}。"""
    processes = {}
    for line in text.splitlines():
        fields = [f.strip('"') for f in line.split('","')]
        if len(fields) >= 2 and fields[1].isdigit():
            processes[int(fields[1])] = fields[0].lower()
    return processes


def parse_netstat(text):
    """netstat -ano → ESTABLISHED 的 TCP 连接列表（IPv4/IPv6 的地址都去掉端口）。"""
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].lower() == 'tcp' and parts[3].lower() == 'established' \
                and parts[4].isdigit():
            rows.append({
                'local': _split_addr(parts[1]), 'remote': _split_addr(parts[2]),
                'pid': int(parts[4]),
            })
    return rows


def _split_addr(addr):
    """'[::1]:8384' / '127.0.0.1:8384' → (ip, port)；解析失败返回 (addr, 0)。"""
    host, _, port = addr.rpartition(':')
    host = host.strip('[]')
    if host and port.isdigit():
        return host, int(port)
    return addr, 0


def parse_route_snapshot(text):
    """PowerShell CIM JSON → {'default': [接口名（适配器描述）], 'next_hop': [网关], 'cover': [前缀]}。

    虚拟网卡在中文系统里接口名常是「以太网 2」这类本地化名字，TUN/TAP 字样
    只出现在适配器描述（InterfaceDescription）里，两处都要参与判定。
    解析失败返回空结构，调用方按"无法核实"降级。
    """
    try:
        data = json.loads(text)
    except ValueError:
        return {'default': [], 'next_hop': [], 'cover': []}
    wrap = lambda key: data.get(key) if isinstance(data.get(key), list) else ([] if data.get(key) is None else [data.get(key)])
    defaults, hops = [], []
    for item in wrap('default'):
        if isinstance(item, dict):
            alias, desc = str(item.get('alias') or ''), str(item.get('desc') or '')
            defaults.append(f'{alias}（{desc}）' if alias and desc else alias or desc)
            if item.get('hop'):
                hops.append(str(item['hop']))
        elif item:
            defaults.append(str(item))
    hops.extend(str(h) for h in wrap('next_hop'))
    return {'default': defaults, 'next_hop': hops,
            'cover': [str(c) for c in wrap('cover')]}


def route_snapshot_command():
    """一次 PowerShell 拿默认路由接口（名+描述）、网关与 1/8+128/8 覆盖路由。

    首行强制 UTF-8 输出：中文 Windows 的 PowerShell 默认跟控制台 GBK 编码，
    接口名（如「以太网」）会变乱码（同 stmanager.running_config_home 的处理）。
    """
    return ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
            "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding; "
            "$ErrorActionPreference='SilentlyContinue'; "
            "$adapters = @{}; Get-NetAdapter | ForEach-Object { $adapters[$_.InterfaceAlias] = $_.InterfaceDescription }; "
            "$d = Get-NetRoute -DestinationPrefix '0.0.0.0/0' | ForEach-Object { "
            "[PSCustomObject]@{ alias = $_.InterfaceAlias; desc = $adapters[$_.InterfaceAlias]; hop = $_.NextHop } }; "
            "$c = Get-NetRoute | Where-Object { $_.DestinationPrefix -in @('1.0.0.0/8','128.0.0.0/8') } "
            "| Select-Object -ExpandProperty DestinationPrefix; "
            "@{ default = @($d); cover = @($c) } | ConvertTo-Json -Compress"]


def proxy_targets_from_env(env):
    """HTTP(S)_PROXY / ALL_PROXY（大小写）→ {(host, port)}，供端口比对。"""
    targets = set()
    for key, value in env.items():
        if key.lower() not in ('http_proxy', 'https_proxy', 'all_proxy'):
            continue
        parsed = urllib.parse.urlparse(value if '//' in value else '//' + value)
        if parsed.hostname and parsed.port:
            targets.add((parsed.hostname, parsed.port))
    return targets


def _is_public(ip):
    try:
        addr = ipaddress.ip_address(ip.split('%')[0])
    except ValueError:
        return False
    return addr.is_global


def _fmt_addr(host, port):
    return f'{host}:{port}'


# ---------- 各项检测 ----------

def check_engine(preference):
    state, mode = preference['state'], preference['mode']
    if state == 'applied':
        if mode == 'direct':
            return _item('engine', 'pass', '引擎归属', '同步引擎由小助手启动，进程存活',
                         '优先直连环境已应用到当前引擎（按启动时创建记录）')
        return _item('engine', 'info', '引擎归属', '同步引擎由小助手启动，进程存活',
                     '当前选择沿用环境代理，引擎不在直连环境下运行',
                     '想绕过代理请切换为「优先直连」并重启小助手')
    if state == 'restart_required':
        return _item('engine', 'warn', '引擎归属', '设置已保存，但引擎启动时应用的是另一种模式',
                     '当前运行的引擎尚未应用「优先直连」',
                     '退出并重新打开小助手，由小助手重新创建引擎')
    return _item('engine', 'warn', '引擎归属', '正在运行的引擎不是小助手启动的（独立 Syncthing）',
                 '「优先直连」只对小助手自己启动的引擎生效，当前引擎的启动环境无法由本助手控制',
                 '退出该独立引擎再由小助手启动（自检报告里有一键接管按钮）；也可从原工具的开机自启 / 计划任务自行退出')


def check_proxy_connections(engine_conns, env_targets):
    hits = []
    for conn in engine_conns:
        host, port = conn['remote']
        if host in ('127.0.0.1', '::1', 'localhost') and \
                (port in COMMON_PROXY_PORTS or (host, port) in env_targets):
            hits.append(_fmt_addr(host, port))
    if hits:
        return _item('proxy_conn', 'fail', '本地代理端口',
                     f'引擎存在到本地代理端口的连接：{ "、".join(dict.fromkeys(hits)) }',
                     '同步引擎正在通过显式代理转发流量',
                     '切换为「优先直连」并重启引擎；仍复现请在代理软件核查该端口')
    return _item('proxy_conn', 'pass', '本地代理端口',
                 f'引擎现有 {len(engine_conns)} 条连接均未指向常见本地代理端口',
                 '未发现引擎使用显式代理的连接')


def check_takeover(route):
    defaults = '、'.join(dict.fromkeys(route['default'])) or '未查询到'
    suspicious = [name for name in route['default']
                  if any(hint in name.lower() for hint in VIRTUAL_ADAPTER_HINTS)]
    suspicious += [hop for hop in route['next_hop'] if hop.startswith('198.18.')]
    covered = {'1.0.0.0/8', '128.0.0.0/8'} <= set(route['cover'])
    if suspicious or covered:
        signs = []
        if suspicious:
            signs.append(f'默认路由接口疑似虚拟网卡（{"、".join(dict.fromkeys(suspicious))}）')
        if covered:
            signs.append('存在 1.0.0.0/8 + 128.0.0.0/8 覆盖路由')
        return _item('takeover', 'warn', '系统层接管', f'默认路由接口：{defaults}；{"；".join(signs)}',
                     '检测到系统层接管迹象，删除环境变量无法绕过这类接管',
                     '在代理软件里为 syncthing 进程添加直连规则（见下方规则片段），再查其连接记录确认命中 DIRECT')
    return _item('takeover', 'pass', '系统层接管', f'默认路由接口：{defaults}；未发现覆盖路由',
                 '未发现默认路由被虚拟网卡接管的迹象')


def check_relay_trace(engine_conns, all_conns, engine_pids, processes):
    proxy_pids = {pid for pid, name in processes.items()
                  if pid not in engine_pids and any(h in name for h in PROXY_PROCESS_HINTS)}
    if not proxy_pids:
        return _item('relay_trace', 'pass', '转发痕迹比对', '未发现常见代理内核进程（Clash / sing-box / v2ray 等）',
                     '未发现可能转发同步流量的本地代理进程')
    names = '、'.join(sorted({processes[pid] for pid in proxy_pids})[:4])
    engine_targets = {conn['remote'][0] for conn in engine_conns if _is_public(conn['remote'][0])}
    if not engine_targets:
        return _item('relay_trace', 'info', '转发痕迹比对',
                     f'发现代理内核进程：{names}；引擎当前没有公网目标连接，无从比对',
                     '引擎空闲或仅局域网同步时本项不构成证据')
    proxy_targets = {conn['remote'][0] for conn in all_conns if conn['pid'] in proxy_pids}
    matched = sorted(engine_targets & proxy_targets)
    if matched:
        return _item('relay_trace', 'warn', '转发痕迹比对',
                     f'发现代理内核进程：{names}；其中存在与引擎相同远端的连接：{"、".join(matched[:5])}',
                     '代理内核与引擎连着同一远端，同步流量疑似经它转发（也可能是 TUN 规则命中直连后由内核代发）',
                     '以代理软件连接记录为准：确认 syncthing 相关连接命中 DIRECT／直连')
    return _item('relay_trace', 'pass', '转发痕迹比对',
                 f'发现代理内核进程：{names}；其连接目标与引擎的 {len(engine_targets)} 个公网目标无交集',
                 '未发现代理内核转发同步流量的痕迹（本地旁证）')


def _system_proxy_text():
    if platform.system() != 'Windows':
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Internet Settings') as key:
            enabled, _ = winreg.QueryValueEx(key, 'ProxyEnable')
            server, _ = winreg.QueryValueEx(key, 'ProxyServer')
    except OSError:
        return None
    return str(server).split(';')[0] if enabled else None


def check_system_proxy():
    if not _windows():
        return _item('sysproxy', 'info', '系统代理', '当前平台无 Windows 系统代理概念',
                     '此项不影响同步流量')
    server = _system_proxy_text()
    if server:
        return _item('sysproxy', 'info', '系统代理', f'Windows 系统代理已开启（{server}）',
                     'Syncthing 不读取系统代理设置，浏览器等应用会经过它；此项不影响同步流量')
    return _item('sysproxy', 'info', '系统代理', 'Windows 系统代理未开启',
                 '此项不影响同步流量，仅说明当前浏览器类应用的上网方式')


# ---------- 编排 ----------

def run():
    preference = stmanager.network_preference()
    checks = [check_engine(preference)]
    engine_running = False
    if _windows():
        try:
            processes = parse_tasklist_csv(_run(['tasklist', '/FO', 'CSV', '/NH']))
            conns = parse_netstat(_run(['netstat', '-ano']))
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            activity.dev('network_check process/conn snapshot failed: %s', exc)
            checks.append(_item('proxy_conn', 'info', '本地代理端口', f'连接快照获取失败：{exc}',
                                '本次无法核实引擎连接，请稍后重试'))
        else:
            engine_pids = {pid for pid, name in processes.items() if name.startswith('syncthing')}
            engine_conns = [c for c in conns if c['pid'] in engine_pids]
            engine_running = bool(engine_pids)
            if engine_pids:
                checks.append(check_proxy_connections(engine_conns, proxy_targets_from_env(os.environ)))
                checks.append(check_relay_trace(engine_conns, conns, engine_pids, processes))
            else:
                checks.append(_item('proxy_conn', 'info', '本地代理端口', '未发现正在运行的 syncthing 进程',
                                    '引擎未运行时无连接可查；请先启动引擎再检测'))
    else:
        # tasklist/netstat 是 Windows 命令；Mac 缺少可靠的进程-连接映射，不猜结果。
        engine_running = stmanager.process_running()
        checks.append(_item('proxy_conn', 'info', '本地代理端口', '当前平台暂不支持连接级自检',
                            '请按代理软件内的连接记录确认'))
    if _windows():
        try:
            checks.append(check_takeover(parse_route_snapshot(_run(route_snapshot_command()))))
        except (OSError, subprocess.SubprocessError) as exc:
            activity.dev('network_check route snapshot failed: %s', exc)
            checks.append(_item('takeover', 'info', '系统层接管', f'路由快照获取失败：{exc}',
                                '本次无法核实系统层接管，请稍后重试'))
    else:
        checks.append(_item('takeover', 'info', '系统层接管', '当前平台暂不支持路由级自检',
                            '请按代理软件内的连接记录确认'))
    checks.append(check_system_proxy())

    # info 是说明项，不参与定级；全部为 info 时整体才显示 info。
    graded = [c['level'] for c in checks if c['level'] != 'info']
    worst = max(graded, key=lambda l: LEVEL_ORDER[l]) if graded else 'info'
    if worst == 'fail':
        text = '发现同步流量疑似正在走代理，请处理标红项后在代理软件复核'
    elif worst == 'warn':
        text = '未发现明确的代理转发，但存在需处理或无法排除的项目；最终以代理软件连接记录为准'
    elif preference['mode'] != 'direct':
        text = '未发现走代理的痕迹；当前模式为「沿用环境代理」，如需绕过请切换为优先直连'
    else:
        text = '未发现同步流量走代理的痕迹（本地旁证；最终以代理软件连接记录为准）'
    return {'mode': preference['mode'], 'state': preference['state'],
            'engine_running': engine_running,
            'generated_at': int(time.time()), 'summary': {'level': worst, 'text': text},
            'checks': checks,
            'note': '自检只收集本机旁证，不读取代理软件凭据；代理软件内部的 DIRECT／节点命中只能在它的连接记录里确认。'}
