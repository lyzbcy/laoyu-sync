"""Per-engine proxy preference. Does not claim to bypass OS VPN/TUN routing."""
import json
import os

import config

MODES = ('system', 'direct')


def mode():
    value = config.get('sync_network_mode')
    return value if value in MODES else 'system'


def set_mode(value):
    if not isinstance(value, str) or value not in MODES:
        raise ValueError('请选择沿用环境代理或优先直连')
    previous = mode()
    try:
        config.set('sync_network_mode', value)
    except Exception:
        # config.set updates its cache before writing the file.
        config.set('sync_network_mode', previous)
        raise


def engine_environment(selected):
    if selected not in MODES:
        raise ValueError('无效的同步网络模式')
    env = dict(os.environ)
    if selected == 'direct':
        # Go / Syncthing and discovery clients accept different capitalizations.
        env = {k: v for k, v in env.items() if k.lower() not in
               ('http_proxy', 'https_proxy', 'all_proxy', 'no_proxy')}
        env.update(NO_PROXY='*', no_proxy='*')
    return env


def status(owned=False, applied=None):
    selected = mode()
    if not owned:
        state = 'external_or_stopped'
        note = '当前未管理运行中的引擎；已有引擎需由原工具退出，再由小助手启动后应用。'
    elif applied != selected:
        state = 'restart_required'
        note = '设置已保存，退出并重新打开小助手后应用到同步引擎。'
    else:
        state = 'applied'
        note = ('同步引擎已忽略环境变量代理。' if selected == 'direct'
                else '同步引擎沿用启动时的环境代理设置。')
    return dict(mode=selected, state=state, note=note, verified_direct=False,
                caveat='TUN／全局 VPN 仍可能接管流量；开启优先直连不代表已验证不耗代理流量。请在代理软件中添加同步进程直连规则，并检查其连接记录。',
                scope='只影响文件同步引擎；软件更新和反馈继续使用原有网络。')


def bypass_rules(kind):
    """Static snippets only: never export credentials or rewrite proxy profiles."""
    names = ['syncthing.exe', 'syncthing']
    if kind == 'clash':
        return dict(name='Clash / Mihomo', text='\n'.join(
            f'- PROCESS-NAME,{name},DIRECT' for name in names),
            help='添加到 rules 列表最前面，放在 MATCH 和其他宽泛规则之前；使用规则模式，启用进程识别（find-process-mode: strict）。订阅用户请通过客户端的覆写／扩展配置持久保存。')
    if kind == 'surge':
        return dict(name='Surge', text='\n'.join(
            f'PROCESS-NAME,{name},DIRECT' for name in names),
            help='添加到 [Rule] 最前面，放在 FINAL 之前；使用规则模式。')
    if kind == 'singbox':
        return dict(name='sing-box 1.11+', text=json.dumps(
            {'process_name': names, 'action': 'route', 'outbound': 'direct'},
            ensure_ascii=False, indent=2),
            help='添加到 route.rules 最前面；需要已有 tag 为 direct、type 为 direct 的出站，否则将 outbound 改为自己的直连出站标签。')
    raise ValueError('不支持的规则格式')
