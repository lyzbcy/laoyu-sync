"""Shared first-use state for the dashboard and desktop companion."""


def setup_summary(snap):
    if not snap['syncthing'].get('api_ok'):
        return {'key': 'checking', 'title': '正在读取同步项目',
                'detail': snap['syncthing'].get('note') or '正在连接本机同步引擎，请稍候', 'route': '#/dash'}
    if snap.get('folders'):
        return {'key': 'ready', 'title': f"已识别 {len(snap['folders'])} 个同步项目",
                'detail': '项目与设备配置已沿用', 'route': '#/folders'}
    pending = snap.get('pending_folders') or []
    if pending:
        return {'key': 'receive', 'title': f'有 {len(pending)} 个项目等你接收',
                'detail': '选择本机保存位置，继续已有项目，无需重新创建', 'route': '#/folders'}
    if snap.get('discovery', {}).get('other_projects'):
        return {'key': 'other_config', 'title': '发现另一份已有项目配置',
                'detail': '当前引擎没有项目。请退出助手并打开原来的同步工具，再启动助手接入原有项目。', 'route': '#/devices'}
    if snap.get('network', {}).get('connected'):
        return {'key': 'network_ready', 'title': '网络已就绪，等待同步项目',
                'detail': '本机暂未读到已有项目。已有项目请让原电脑共享给本机；Tailscale 共享目录不会自动成为同步项目。', 'route': '#/devices'}
    return {'key': 'empty', 'title': '等待接入同步项目',
            'detail': '已有项目可从原电脑共享过来；首次同步也可以选择文件夹创建。', 'route': '#/folders'}
