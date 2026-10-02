"""core/version.py — 版本号与自适应更新检测（用户规范《自适应更新检测》/《skill 静默更新》）

规则（SKILL.md 铁律 1）：每次开发完成必须更新 __version__ 和 CHANGELOG。

检查机制：
- 更新源 config.update_manifest_url 未配置 → 整体静默（enabled=false）。
- 已配置 → 每天首次使用时拉取 manifest：{"version", "notes", "download_url"}。
- 落后远端 → UI 顶部横幅：一键更新（进度 + 国内代理提醒）与失败兜底（重试 / 跳转发布页）。
- 检查失败不打断使用，静默用旧版，下次再试。
"""
import datetime
import json
import re
import urllib.request

import activity
import config

__version__ = "0.3.4"

CHANGELOG = [
    {"ver":"0.3.4","date":"2026-10-02","items":["核对当前版本后归档过时更新失败，不再把历史错误显示为当前故障", "更新暂存目录在确认事务结束且相关进程退出后清理，保留历史凭据和同步身份"]},
    {"ver":"0.3.3","date":"2026-10-01","items":["反馈改为一级入口，支持分类与日志预览，直接发至企业微信", "企业微信确认留言与ZIP日志附件，失败保留内容并可续发", "补齐后台版本检查完成后的界面提醒"]},
    {"ver": "0.3.2", "date": "2026-09-30", "items": ["补齐 SyncTrayzor 等旧配置位置与含空格的运行参数识别", "已有项目、待接收项目和网络就绪使用统一状态，不再催促已有用户新建", "桌面小鱼增加清晰状态卡片、中文详情与直接接入入口"]},
    {"ver": "0.3.1", "date": "2026-09-30", "items": ["Windows 无边框标题栏与更简洁的同步概览", "自动识别现有 Tailscale 网络与在线节点", "沿用原有 Syncthing 项目、设备和自定义配置位置，区分网络与文件同步状态"]},
    {"ver": "0.3.0", "date": "2026-09-30", "items": ["内置同步引擎，Windows 安装与便携包", "首次使用引导、可靠状态、共享设置和暂停", "桌面小鱼统一管理、诊断日志复制", "每日版本检查、校验下载、升级重启与失败恢复"]},
    {
        "ver": "0.2.0",
        "date": "2026-09-07",
        "items": [
            "改名「捞鱼同步小助手」，品牌全面焕新",
            "同步改用『项目』制：本机建项目并共享，另一台电脑直接看到、选个位置就接收",
            "添加设备支持『自动接收 TA 分享的项目』",
            "界面全面翻新：浏览文件夹按钮、进度环动画、空状态小鱼贴纸",
            "失败文件直接列出并附人话说明，不再丢给英文页面",
            "桌面小精灵换新形象：一条会摆尾吐泡的小蓝鱼",
        ],
    },
    {
        "ver": "0.1.0",
        "date": "2026-09-07",
        "items": [
            "首个版本：本地核心服务 + 网页管理界面",
            "添加设备向导：二维码 / 待确认设备一键接受 / 按 ID 添加并共享文件夹",
            "仪表盘实时同步进度、添加同步文件夹、动态事件流",
            "桌面小精灵插件接入管理界面",
        ],
    },
]


def semver_tuple(v):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', str(v))
    return tuple(map(int, match.groups())) if match else (0, 0, 0)


def _today():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()


def check(force=False):
    """返回 update 信息体。每天首次使用检查一次；失败静默。"""
    url = config.get("update_manifest_url")
    if not url:
        return {"enabled": False, "note": "更新源未配置（等 GitHub 仓库建立后在 core/config.json 填 update_manifest_url）"}
    today = _today()
    if not force and config.get("last_update_attempt") == today:
        return _cached()
    config.set('last_update_attempt', today)
    try:
        from updater import trusted_url
        if not trusted_url(url, manifest=True):
            raise ValueError('更新源不在可信仓库范围内')
        req = urllib.request.Request(url, headers={"User-Agent": "SyncSprite/" + __version__})
        with urllib.request.urlopen(req, timeout=8) as resp:
            manifest = json.loads(resp.read().decode("utf-8"))
        config.set("last_update_check", today)
        result = {
            "enabled": True,
            "remote_version": str(manifest.get("version", "")),
            "notes": str(manifest.get("notes", "")),
            "download_url": str(manifest.get("download_url", "")),
            "has_update": semver_tuple(str(manifest.get("version", ""))) > semver_tuple(__version__),
            "sha256": str(manifest.get('sha256', '')),
            "error": "",
        }
        if result["has_update"]:
            activity.user(f"发现新版本 v{result['remote_version']}，可前往“关于”页更新")
        config.set("_update_cache", result)
        return result
    except Exception as exc:
        # 规范要求：更新检查失败静默用旧版，不打断本次使用
        activity.error("update check failed: %s", exc)
        cached = _cached()
        cached['error'] = '检查失败，请检查网络或代理后重试'
        config.set('_update_cache', cached)
        return cached


def _cached():
    cached = config.get("_update_cache") or {}
    return dict(cached, **{
        "enabled": True,
        "remote_version": cached.get("remote_version", ""),
        "notes": cached.get("notes", ""),
        "download_url": cached.get("download_url", ""),
        "has_update": semver_tuple(cached.get('remote_version', '')) > semver_tuple(__version__),
    })


def local_info():
    return {"version": __version__, "changelog": CHANGELOG, "update": _cached()}
