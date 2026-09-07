"""core/wizard.py — 添加设备/文件夹业务（本项目核心卖点）

流程设计（对应 docs/reference/core-api.md）：
添加设备 = 校验 ID → 查重 → 添加（POST /rest/config/devices）→ 勾选共享文件夹
（PUT /rest/config/folders/<id>）→ 视 requiresRestart 自动重启引擎。
若该 ID 出现在待确认列表（对方先主动连过我们），标记 pending_accepted。
"""
import os
import secrets

import activity
from stmanager import normalize_device_id


class WizardError(Exception):
    """带中文可读信息的业务错误，网关原样透传给前端。"""


def add_device_flow(mgr, raw_id, name, folder_ids, auto_accept=False):
    device_id = normalize_device_id(raw_id or "")
    if not device_id:
        raise WizardError("设备 ID 格式不对：应为 8 组 7 位的字符串（横线可省略），粘贴时带空格没关系")
    name = (name or "").strip() or device_id[:7]
    folder_ids = folder_ids or []

    cfg = mgr.client.get("/rest/config")
    existing = {d.get("deviceID") for d in cfg.get("devices", [])}
    if device_id in existing:
        raise WizardError("这个设备已经添加过了，不需要重复添加")

    pending_ids = {p["deviceID"] for p in mgr.pending_devices()}
    pending_accepted = device_id in pending_ids

    activity.user(f"正在添加设备「{name}」…")
    try:
        resp = mgr.client.post("/rest/config/devices", {
            "deviceID": device_id,
            "name": name,
            "addresses": ["dynamic"],
            "compression": "metadata",
            "introducer": False,
            "autoAcceptFolders": bool(auto_accept),
        })
    except RuntimeError as exc:
        raise WizardError(f"同步引擎拒绝了这次添加：{exc}。多半是 ID 复制不全或输错，麻烦整段重新粘贴一次")
    restarted = mgr._maybe_restart(resp)

    shared = []
    for fid in folder_ids:
        restarted = _share_folder(mgr, device_id, fid) or restarted
        shared.append(fid)
    if shared:
        activity.user(f"已把 {len(shared)} 个文件夹共享给「{name}」")

    tip = "对方设备上会弹出接受提示，接受后即可开始同步"
    if pending_accepted:
        tip = "对方之前主动连接过本机，添加后无需对方再确认"
    activity.user(f"设备「{name}」添加成功")
    return {"ok": True, "device_id": device_id, "shared": shared,
            "restarted": restarted, "pending_accepted": pending_accepted, "tip": tip}


def _share_folder(mgr, device_id, folder_id):
    folders = mgr.client.get("/rest/config").get("folders", [])
    target = next((f for f in folders if f.get("id") == folder_id), None)
    if target is None:
        raise WizardError(f"找不到要共享的文件夹：{folder_id}")
    devs = target.setdefault("devices", [])
    if not any(d.get("deviceID") == device_id for d in devs):
        devs.append({"deviceID": device_id})
        resp = mgr.client.put(f"/rest/config/folders/{folder_id}", target)
        return mgr._maybe_restart(resp)
    return False


def remove_device_flow(mgr, device_id):
    cfg = mgr.client.get("/rest/config")
    if not any(d.get("deviceID") == device_id for d in cfg.get("devices", [])):
        raise WizardError("设备不存在，可能已被移除")
    name = next((d.get("name", "") for d in cfg["devices"] if d["deviceID"] == device_id), "")
    resp = mgr.client.delete(f"/rest/config/devices/{device_id}")
    restarted = mgr._maybe_restart(resp)
    activity.user(f"已移除设备「{name or device_id[:7]}」")
    return {"ok": True, "restarted": restarted}


def add_folder_flow(mgr, raw_path, label, share_with=None):
    """新建本机同步项目，可顺手共享给指定设备。"""
    path = os.path.abspath(os.path.expanduser(str(raw_path or "").strip()))
    if not os.path.isdir(path):
        raise WizardError("路径不存在或不是文件夹，请填一个本机上真实存在的文件夹路径")
    label = (label or "").strip() or os.path.basename(path) or path
    share_with = [d for d in (share_with or []) if d]
    cfg = mgr.client.get("/rest/config")
    my_id = mgr.client.get("/rest/system/status").get("myID", "")
    known = {d.get("deviceID") for d in cfg.get("devices", [])}
    for did in share_with:
        if did not in known:
            raise WizardError("要共享的设备不存在，请刷新页面重试")
    fid = "sync-" + secrets.token_hex(4)
    activity.user(f"正在创建同步项目「{label}」…")
    resp = mgr.client.post("/rest/config/folders", {
        "id": fid, "label": label, "path": path,
        "type": "sendreceive", "rescanIntervalS": 3600,
        "fsWatcherEnabled": True, "fsWatcherDelayS": 10,
        "devices": [{"deviceID": my_id}] + [{"deviceID": d} for d in share_with],
    })
    restarted = mgr._maybe_restart(resp)
    if share_with:
        names = {d.get("deviceID"): d.get("name", "") for d in cfg.get("devices", [])}
        pretty = "、".join(names.get(d, d[:7]) for d in share_with)
        activity.user(f"「{label}」已共享给 {pretty}，等对方接收")
    activity.user(f"同步项目「{label}」创建成功，首次扫描可能需要一点时间")
    return {"ok": True, "folder_id": fid, "restarted": restarted, "shared": share_with}


def accept_folder_flow(mgr, folder_id, label, raw_path, device_id, auto_accept=False):
    """接收对端分享来的项目：用对方给的 folder id 在本机落一个位置。"""
    folder_id = str(folder_id or "").strip()
    if not folder_id:
        raise WizardError("缺少项目标识，请刷新页面重试")
    pending = {p["folderID"]: p for p in mgr.pending_folders()}
    if folder_id not in pending:
        raise WizardError("这个邀请已经失效（对方可能撤回了），刷新看看最新的")
    path = os.path.abspath(os.path.expanduser(str(raw_path or "").strip()))
    if not os.path.isdir(path):
        raise WizardError("保存位置不存在或不是文件夹，请选一个本机真实存在的文件夹")
    label = (label or "").strip() or pending[folder_id]["folderLabel"]
    my_id = mgr.client.get("/rest/system/status").get("myID", "")
    activity.user(f"正在接收项目「{label}」（来自 {pending[folder_id]['deviceName']}）…")
    resp = mgr.client.post("/rest/config/folders", {
        "id": folder_id, "label": label, "path": path,
        "type": "sendreceive", "rescanIntervalS": 3600,
        "fsWatcherEnabled": True, "fsWatcherDelayS": 10,
        "devices": [{"deviceID": device_id}, {"deviceID": my_id}],
    })
    restarted = mgr._maybe_restart(resp)
    if auto_accept:
        try:
            dev = next(d for d in mgr.client.get("/rest/config").get("devices", [])
                       if d.get("deviceID") == device_id)
            dev["autoAcceptFolders"] = True
            mgr._maybe_restart(mgr.client.put(f"/rest/config/devices/{device_id}", dev))
            activity.user(f"以后「{pending[folder_id]['deviceName']}」分享的项目会自动接收")
        except StopIteration:
            pass
    activity.user(f"项目「{label}」接收成功，正在拉取文件")
    return {"ok": True, "folder_id": folder_id, "restarted": restarted}


def remove_folder_flow(mgr, folder_id):
    """移除同步项目：只解除同步，本机已收到的文件保留在原地。"""
    cfg = mgr.client.get("/rest/config")
    target = next((f for f in cfg.get("folders", []) if f.get("id") == folder_id), None)
    if target is None:
        raise WizardError("项目不存在，可能已被移除")
    label = target.get("label") or folder_id
    resp = mgr.client.delete(f"/rest/config/folders/{folder_id}")
    mgr._maybe_restart(resp)
    activity.user(f"已移除同步项目「{label}」（本机文件保留在原位置）")
    return {"ok": True}


def set_auto_accept_flow(mgr, device_id, enabled):
    cfg = mgr.client.get("/rest/config")
    dev = next((d for d in cfg.get("devices", []) if d.get("deviceID") == device_id), None)
    if dev is None:
        raise WizardError("设备不存在，请刷新页面重试")
    dev["autoAcceptFolders"] = bool(enabled)
    resp = mgr.client.put(f"/rest/config/devices/{device_id}", dev)
    mgr._maybe_restart(resp)
    activity.user("已开启自动接收" if enabled else "已关闭自动接收")
    return {"ok": True}
