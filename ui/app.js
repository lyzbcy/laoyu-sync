/* 捞鱼同步小助手前端逻辑（原生 JS，无构建链） */
"use strict";

const $ = (id) => document.getElementById(id);

let TOKEN = "";
try { TOKEN = sessionStorage.getItem("t") || ""; } catch (e) { /* 内嵌浏览器可能禁用存储 */ }
TOKEN = TOKEN || new URLSearchParams(location.search).get("t") || "";
try { if (TOKEN) sessionStorage.setItem("t", TOKEN); } catch (e) { /* ignore */ }

if (!TOKEN) {
  document.getElementById("noauth").classList.remove("hidden");
} else {
  document.getElementById("app").classList.remove("hidden");
}

/* ---------------- 基础工具 ---------------- */

async function api(method, path, body) {
  const resp = await fetch(path, {
    method,
    headers: { "X-Token": TOKEN, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = {};
  try { data = await resp.json(); } catch (e) { /* 空响应 */ }
  if (!resp.ok || data.ok === false) throw new Error(data.error || `请求失败（${resp.status}）`);
  return data;
}

function friendly(e) {
  const msg = String(e && e.message || e);
  if (msg.includes("401")) return "本机令牌不对，请关掉窗口，从启动器重新打开";
  if (/\b5\d\d\b|Failed to fetch|NetworkError/i.test(msg)) return "程序开小差了，稍等几秒会自动重试；一直不行就关掉重开，再到「关于」页找作者聊聊";
  return msg;
}

function fmtBytes(n) {
  n = Number(n) || 0;
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return (i === 0 ? n.toFixed(0) : n.toFixed(1)) + units[i];
}

function fmtSpeed(bps) {
  return bps >= 1 ? fmtBytes(bps) + "/s" : "";
}

function fmtPct(p) {
  return p >= 99.995 ? "100%" : (p >= 99.9 || p < 1 ? p.toFixed(2) : p.toFixed(1)) + "%";
}

function fmtUptime(s) {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h}小时${m}分` : `${m}分钟`;
}

function ts(t) {
  const d = new Date(t * 1000);
  const pad = (x) => String(x).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function toast(msg, ms = 2800) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  clearTimeout(el._job);
  el._job = setTimeout(() => el.classList.add("hidden"), ms);
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (e) {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  }
}

/* 提交期间禁用按钮，防手抖双击重复提交 */
async function withLoading(btn, fn, loadingText) {
  if (btn.disabled) return;
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = loadingText || "处理中…";
  try {
    return await fn();
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

/* pywebview 里 window.open/confirm 都不可用，统一走桥或降级 */
function openExternal(url) {
  try {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.open_external) {
      window.pywebview.api.open_external(url);
      return;
    }
  } catch (e) { /* 降级 */ }
  window.open(url, "_blank");
}

function hasPicker() {
  return !!(window.pywebview && window.pywebview.api && window.pywebview.api.choose_folder);
}

async function chooseFolder(input) {
  if (!hasPicker()) return;
  try {
    const p = await window.pywebview.api.choose_folder();
    if (p) input.value = p;
  } catch (e) { /* 用户取消 */ }
}

/* 通用确认弹窗（代替 window.confirm），resolve(true/false) */
function confirmBox(title, html, okText) {
  return new Promise((resolve) => {
    $("modalTitle").textContent = title;
    $("modalBody").innerHTML = html;
    const ok = $("modalOk"), cancel = $("modalCancel"), close = $("modalClose");
    ok.textContent = okText || "确定";
    ok.classList.remove("hidden");
    cancel.classList.remove("hidden");
    $("modal").classList.remove("hidden");
    const done = (val) => {
      $("modal").classList.add("hidden");
      ok.classList.add("hidden");
      cancel.classList.add("hidden");
      ok.onclick = cancel.onclick = close.onclick = $("modal").onclick = null;
      document.removeEventListener("keydown", onKey);
      resolve(val);
    };
    const onKey = (e) => { if (e.key === "Escape") done(false); };
    document.addEventListener("keydown", onKey);
    ok.onclick = () => done(true);
    cancel.onclick = () => done(false);
    close.onclick = () => done(false);
  });
}

function infoModal(title, html) {
  $("modalTitle").textContent = title;
  $("modalBody").innerHTML = html;
  $("modalOk").classList.add("hidden");
  $("modalCancel").classList.add("hidden");
  $("modal").classList.remove("hidden");
  $("modalClose").onclick = () => $("modal").classList.add("hidden");
  $("modal").onclick = (e) => { if (e.target === $("modal")) $("modal").classList.add("hidden"); };
  const escOnce = (e) => {
    if (e.key === "Escape") {
      $("modal").classList.add("hidden");
      document.removeEventListener("keydown", escOnce);
    }
  };
  document.addEventListener("keydown", escOnce);
}

/* ---------------- 路由 ---------------- */

const PAGES = ["dash", "devices", "folders", "events", "about"];
function route() {
  const name = (location.hash.replace(/^#\//, "") || "dash").split("?")[0];
  const page = PAGES.includes(name) ? name : "dash";
  PAGES.forEach((p) => $("page-" + p).classList.toggle("hidden", p !== page));
  document.querySelectorAll("nav a").forEach((a) =>
    a.classList.toggle("active", a.dataset.page === page));
  if (page === "devices") refreshDevicesPage();
  if (page === "folders") refreshFoldersPage();
}
window.addEventListener("hashchange", route);

/* 关于页等外链统一走系统浏览器 */
document.addEventListener("click", (e) => {
  const a = e.target.closest("a[data-external]");
  if (a) { e.preventDefault(); openExternal(a.dataset.external); }
});

/* ---------------- 状态轮询 ---------------- */

let LAST_EVENT = 0;
let LAST_STATUS = null;
let HAS_PICKER = false;
let FAILS = 0;

async function pollStatus() {
  try {
    LAST_STATUS = await api("GET", "/api/status");
    FAILS = 0;
    renderCapsule();
    renderPendingAlert();
    if (!$("page-dash").classList.contains("hidden")) { renderDash(); renderDashErrors(); }
    if (!$("page-devices").classList.contains("hidden")) { renderDeviceList(); renderShareFolders(); }
    if (!$("page-folders").classList.contains("hidden")) { renderFolderList(); }
  } catch (e) {
    if (++FAILS >= 3) {
      $("statusText").textContent = friendly(e);
      $("statusCapsule").querySelector(".dot").className = "dot red";
    }
  }
  setTimeout(pollStatus, 2000);
}

async function pollEvents() {
  try {
    const data = await api("GET", "/api/events?since=" + LAST_EVENT);
    if (data.events.length) {
      LAST_EVENT = data.last;
      renderEvents(data.events);
    }
  } catch (e) { /* 忽略，下一轮再试 */ }
  setTimeout(pollEvents, 3000);
}

async function pollPending() {
  try {
    const data = await api("GET", "/api/pending");
    PENDING_DEVICES = data.devices || [];
    PENDING_FOLDERS = data.folders || [];
    $("dot-devices").classList.toggle("hidden", !PENDING_DEVICES.length);
    $("dot-folders").classList.toggle("hidden", !PENDING_FOLDERS.length);
    renderPendingDevices();
    renderPendingProjects();
  } catch (e) { /* 忽略 */ }
  setTimeout(pollPending, 3000);
}

/* ---------------- 顶部状态胶囊 ---------------- */

function stateOf(s) {
  if (!s.syncthing.running && !s.syncthing.api_ok)
    return { key: "grey", text: "小助手正在热身，几秒后自动开始", color: "var(--grey)" };
  if (!s.syncthing.api_ok)
    return { key: "grey", text: "小助手正在热身，几秒后自动开始", color: "var(--grey)" };
  const fs = s.folders || [];
  const badFolders = fs.filter((f) => f.state === "error");
  if (fs.some((f) => f.pullErrors > 0))
    return { key: "red", text: `有 ${fs.reduce((a, f) => a + f.pullErrors, 0)} 个文件没同步成功`, color: "var(--red)" };
  if (badFolders.length)
    return { key: "red", text: `「${badFolders[0].label}」项目出错了`, color: "var(--red)" };
  if (fs.some((f) => f.state === "syncing" || f.state === "sync-preparing"))
    return { key: "blue", text: "正在同步 " + fmtPct(s.total.pct), color: "var(--blue)" };
  if (fs.some((f) => f.state === "scanning"))
    return { key: "teal", text: "正在检查文件变化", color: "var(--teal)" };
  if (s.total.needFiles > 0)
    return { key: "orange", text: `${s.total.needFiles} 个文件排队同步中`, color: "var(--orange)" };
  return { key: "green", text: "两台电脑内容一致 " + fmtPct(s.total.pct), color: "var(--green)" };
}

function renderCapsule() {
  const s = LAST_STATUS;
  const st = stateOf(s);
  $("statusCapsule").querySelector(".dot").className = "dot " + st.key;
  $("statusText").textContent = st.text;
  const speed = fmtSpeed(s.total.speed);
  $("speedInfo").textContent = speed ? `↑↓ ${speed}` : "";
}

/* ---------------- 待处理提醒（横幅 + 导航红点） ---------------- */

function renderPendingAlert() {
  const n = PENDING_FOLDERS.length;
  $("pendingAlert").classList.toggle("hidden", !n);
  if (n) {
    $("pendingAlertText").textContent =
      `有 ${n} 个项目从别的电脑分享过来了，选个保存位置就能用`;
  }
}

$("btnGoPending").onclick = () => { location.hash = "#/folders"; };

/* ---------------- 仪表盘 ---------------- */

function stateLabel(f) {
  if (f.state === "error") return "出错了，检查保存位置";
  if (f.pullErrors > 0) return `${f.pullErrors} 个文件待重传`;
  if (f.state === "syncing") return "同步中";
  if (f.state === "scanning") return "检查变化中";
  if (f.needFiles > 0) return "排队同步中";
  if (f.state === "idle") return "已是最新";
  return f.state;
}

function folderCard(f) {
  const color = { syncing: "var(--blue)", scanning: "var(--teal)" }[f.state] ||
    (f.pullErrors > 0 || f.state === "error" ? "var(--red)" :
     f.needFiles > 0 ? "var(--orange)" : "var(--green)");
  const extra = [];
  if (f.needFiles > 0) extra.push(`待同步 ${f.needFiles} 个 / ${fmtBytes(f.needBytes)}`);
  if (f.pullErrors > 0) extra.push(`失败 ${f.pullErrors} 项`);
  if (f.state === "error") extra.push("可能是保存位置被移动或删除了");
  const rm = `<button class="btn small danger-ghost" data-remove-folder="${esc(f.id)}" data-folder-name="${esc(f.label)}">移除</button>`;
  return `<div class="folder-card">
    <div class="folder-head">
      <span class="dot" style="background:${color}"></span>
      <span class="folder-label">${esc(f.label)}</span>
      <span class="badge" style="background:${color}">${stateLabel(f)}</span>
      ${rm}
    </div>
    <div class="bar"><div style="width:${Math.min(100, f.pct)}%;background:${color}"></div></div>
    <div class="folder-sub"><span>${fmtPct(f.pct)}</span><span>共 ${fmtBytes(f.globalBytes)}</span></div>
    ${extra.length ? `<div class="folder-sub"><span></span><span>${esc(extra.join(" · "))}</span></div>` : ""}
  </div>`;
}

$("dashFolders").addEventListener("click", removeFolderClick);
$("folderList").addEventListener("click", removeFolderClick);

async function removeFolderClick(e) {
  const id = e.target.dataset && e.target.dataset.removeFolder;
  if (!id) return;
  const name = e.target.dataset.folderName || "这个项目";
  const ok = await confirmBox("移除同步项目？",
    `移除「${esc(name)}」后两台电脑就不再同步这个项目了。<b>本机已收到的文件会保留</b>，只是不再更新。`, "移除");
  if (!ok) return;
  await withLoading(e.target, async () => {
    try {
      await api("POST", "/api/folder/remove", { folder_id: id });
      toast("已移除项目（本机文件保留）");
      pollStatus();
    } catch (err) { toast(friendly(err)); }
  }, "移除中…");
}

function renderDash() {
  const s = LAST_STATUS;
  const st = stateOf(s);
  const pct = Math.min(100, s.total.pct);
  $("ringPct").textContent = s.syncthing.api_ok ? fmtPct(s.total.pct) : "…";
  const fg = $("ringFg");
  fg.classList.remove("loading");
  fg.style.strokeDashoffset = (326.7 * (1 - pct / 100)).toFixed(1);
  fg.style.stroke = st.color;
  $("heroState").textContent = st.text;
  $("heroState").style.color = st.color;
  $("heroDetail").textContent = s.syncthing.api_ok
    ? `运行 ${fmtUptime(s.syncthing.uptime)} · 共 ${s.folders.length} 个项目 · ${s.devices.filter((d) => !d.self).filter((d) => d.connected).length}/${s.devices.filter((d) => !d.self).length} 台电脑在线`
    : (s.syncthing.note || "");
  const off = s.devices.filter((d) => !d.self && !d.connected).length;
  $("heroNext").innerHTML = s.folders.length === 0
    ? `<a class="btn primary" href="#/folders">第一步：建一个同步项目</a>`
    : (off ? `<span class="mut small">有电脑离线中，回来后文件会自动补齐</span>` : "");
  $("dashFolders").innerHTML = s.folders.map(folderCard).join("") ||
    `<div class="sticker-empty"><img src="/assets/stickers/第12弹-加油.png" alt="">还没有同步项目。建一个，然后把它分享给另一台电脑</div>`;
  $("dashDevices").innerHTML = s.devices.map((d) =>
    `<span class="chip"><span class="dot ${d.self || d.connected ? "green" : "grey"}"></span>${esc(d.name)}${d.self ? "（本机）" : d.connected ? "" : " · 离线"}</span>`
  ).join("");
}

async function renderDashErrors() {
  const fs = (LAST_STATUS.folders || []);
  const bad = fs.some((f) => f.pullErrors > 0 || f.state === "error");
  const box = $("dashErrors");
  if (!bad) { box.classList.add("hidden"); box._loaded = false; return; }
  box.classList.remove("hidden");
  if (box._loaded) return;
  box._loaded = true;
  box.innerHTML = "正在看是哪几个文件…";
  try {
    const data = await api("GET", "/api/folder-errors");
    const lines = [];
    data.folders.forEach((f) => {
      lines.push(`「${esc(f.folder)}」有 ${f.count} 个文件没同步成功。常见原因：文件名里带了电脑不让用的符号（比如英文的 ? * | ）。把名字改简单点，就会自动重传：`);
      f.items.forEach((it) => lines.push(`<span class="mono">…${esc(it.path.slice(-46))}</span>`));
    });
    box.innerHTML = lines.join("<br>");
  } catch (e) {
    box.innerHTML = "有几个文件没同步成功，把文件名改简单点（别带 ? * | 这类符号）就会自动重传。";
  }
}

function emptyWith(sticker, text) {
  return `<div class="sticker-empty"><img src="/assets/stickers/${sticker}" alt="">${esc(text)}</div>`;
}

/* ---------------- 设备与配对 ---------------- */

let MY_DEVICE = null;
let PENDING_DEVICES = [];
let PENDING_FOLDERS = [];

async function refreshDevicesPage() {
  loadMyDevice();
  renderShareFolders();
  renderPendingDevices();
  renderDeviceList();
}

async function loadMyDevice() {
  if (!MY_DEVICE) {
    try { MY_DEVICE = await api("GET", "/api/mydevice"); } catch (e) { return; }
  }
  $("myName").textContent = MY_DEVICE.name;
  $("myId").textContent = MY_DEVICE.id;
  $("myQr").src = `/api/qr?token=${encodeURIComponent(TOKEN)}&text=${encodeURIComponent(MY_DEVICE.id)}`;
}

$("btnCopyId").onclick = async () => {
  if (MY_DEVICE && (await copyText(MY_DEVICE.id))) toast("号码已复制。微信发给另一台电脑的主人，让 TA 在「认识一台新电脑」里粘贴");
};

function renderShareFolders() {
  if (!LAST_STATUS) return;
  $("shareFolders").innerHTML = LAST_STATUS.folders.map((f) =>
    `<label class="check-line"><input type="checkbox" value="${esc(f.id)}" checked>${esc(f.label)}</label>`
  ).join("") || `<span class="mut small">还没有同步项目，可以先去「同步项目」页建一个</span>`;
}

function renderPendingDevices() {
  const list = PENDING_DEVICES;
  $("pendingBox").classList.toggle("hidden", !list.length);
  $("pendingList").innerHTML = list.map((p, i) =>
    `<div class="pending-row"><span>${esc(p.name || "一台新设备")}</span>
     <span class="mono mut small">${esc(p.deviceID.slice(0, 14))}…</span>
     <button class="btn small primary" data-pending-device="${i}">接受并添加</button></div>`
  ).join("");
}

$("pendingList").addEventListener("click", async (e) => {
  const idx = e.target.dataset && e.target.dataset.pendingDevice;
  if (idx === undefined) return;
  const p = PENDING_DEVICES[Number(idx)];
  if (!p) return;
  const btn = e.target;
  await withLoading(btn, async () => {
    const ok = await confirmBox(
      "接受这台设备？",
      `「${esc(p.name || p.deviceID.slice(0, 14))}」将能和你同步文件。${LAST_STATUS.folders.length ? "目前不共享任何项目，接受后可再去项目里勾选共享。" : ""}`,
      "接受");
    if (!ok) return;
    try {
      await api("POST", "/api/device/add", { device_id: p.deviceID, name: p.name, folders: [] });
      toast("已接受，现在两边认识了");
      pollPending();
      renderDeviceList();
    } catch (err) { toast(friendly(err)); }
  }, "接受中…");
});

$("addDeviceForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const device_id = $("inDeviceId").value.trim();
  if (!device_id) { toast("先把对方的「电脑号码」粘贴进来"); return; }
  const folders = [...document.querySelectorAll("#shareFolders input:checked")].map((i) => i.value);
  if (!folders.length) {
    const ok = await confirmBox("先确认一下", "你还没有勾选任何要共享的项目——这样连是连上了，但两边不会有任何文件来回。要就这样添加吗？", "就这样添加");
    if (!ok) return;
  }
  const msg = $("addDeviceMsg");
  msg.className = "form-msg";
  msg.textContent = "正在添加…";
  try {
    await api("POST", "/api/device/add", {
      device_id, name: $("inDeviceName").value.trim(), folders,
      auto_accept: $("inAutoAccept").checked,
    });
    msg.className = "form-msg ok";
    msg.textContent = "申请已发出！对方屏幕上会出现确认提示，等 TA 点接受就通了";
    $("inDeviceId").value = "";
    $("inDeviceName").value = "";
    renderDeviceList();
  } catch (err) {
    msg.className = "form-msg bad";
    msg.textContent = friendly(err);
  }
});

function renderDeviceList() {
  if (!LAST_STATUS) return;
  const rows = LAST_STATUS.devices.map((d) => {
    const dot = d.self || d.connected ? "green" : "grey";
    const sub = d.self ? "本机" :
      d.connected ? `在线 · ${esc(d.address)} · v${esc(d.clientVersion)}` : "离线（回来后文件自动补齐）";
    const tags = [];
    if (d.autoAccept) tags.push(`<span class="mini-tag">自动接收 TA 的项目</span>`);
    const rm = d.self ? "" :
      `<button class="btn small danger-ghost" data-remove="${esc(d.id)}" data-name="${esc(d.name)}">移除</button>`;
    return `<div class="dev-row"><span class="dot ${dot}"></span>
      <div class="grow"><div class="dev-name">${esc(d.name)}${d.self ? "（本机）" : ""} ${tags.join("")}</div>
      <div class="dev-sub">${sub}</div><div class="dev-sub mono">${esc(d.id)}</div></div>${rm}</div>`;
  });
  $("deviceList").innerHTML = rows.join("") ||
    emptyWith("第12弹-挥手.png", "还没有别的电脑。把上面那串号码发给对方，或把对方的号码粘贴进来");
}

$("deviceList").addEventListener("click", async (e) => {
  const id = e.target.dataset && e.target.dataset.remove;
  if (!id) return;
  const name = e.target.dataset.name || "这台设备";
  const ok = await confirmBox("移除设备？",
    `移除「${esc(name)}」后，两边就不再同步了（已同步到本机的文件会保留）。`, "移除");
  if (!ok) return;
  await withLoading(e.target, async () => {
    try {
      await api("POST", "/api/device/remove", { device_id: id });
      toast("已移除");
      pollStatus();
    } catch (err) { toast(friendly(err)); }
  }, "移除中…");
});

/* ---------------- 同步项目 ---------------- */

async function refreshFoldersPage() {
  renderPendingProjects();
  renderNewProjectDevices();
  renderFolderList();
}

function renderNewProjectDevices() {
  if (!LAST_STATUS) return;
  $("newProjectDevices").innerHTML = LAST_STATUS.devices.filter((d) => !d.self).map((d) =>
    `<label class="check-line"><input type="checkbox" value="${esc(d.id)}" ${d.connected ? "" : ""}>${esc(d.name)}${d.connected ? "" : "（离线，上线后会收到）"}</label>`
  ).join("") || `<span class="mut small">还没有别的电脑。先去「设备与配对」添加一台，回来就能勾选共享</span>`;
}

function renderPendingProjects() {
  const list = PENDING_FOLDERS;
  $("pendingProjects").classList.toggle("hidden", !list.length);
  $("pendingProjectList").innerHTML = list.map((p, i) => `
    <div class="pending-project">
      <div class="pp-head"><b>「${esc(p.folderLabel)}」</b><span class="mut small">来自 ${esc(p.deviceName)}</span></div>
      <div class="pp-row">
        <input class="pp-path" data-pp-path="${i}" placeholder="选一个本机保存位置">
        <button class="btn small" data-pp-browse="${i}" type="button">浏览…</button>
        <label class="check-line small"><input type="checkbox" data-pp-auto="${i}"> 以后自动接收</label>
        <button class="btn small primary" data-pp-accept="${i}" type="button">接收</button>
      </div>
      <div class="pp-msg form-msg" data-pp-msg="${i}"></div>
    </div>`).join("");
}

$("pendingProjectList").addEventListener("click", async (e) => {
  const d = e.target.dataset;
  if (d.ppBrowse !== undefined) {
    const input = document.querySelector(`[data-pp-path="${d.ppBrowse}"]`);
    await chooseFolder(input);
    return;
  }
  if (d.ppAccept === undefined) return;
  const i = Number(d.ppAccept);
  const p = PENDING_FOLDERS[i];
  if (!p) return;
  const path = document.querySelector(`[data-pp-path="${i}"]`).value.trim();
  const auto = document.querySelector(`[data-pp-auto="${i}"]`).checked;
  const msgEl = document.querySelector(`[data-pp-msg="${i}"]`);
  const btn = e.target;
  if (!path) { msgEl.className = "pp-msg form-msg bad"; msgEl.textContent = "先选一个保存在本机的位置"; return; }
  await withLoading(btn, async () => {
    msgEl.className = "pp-msg form-msg";
    msgEl.textContent = "正在接收…";
    try {
      await api("POST", "/api/folder/accept", {
        folder_id: p.folderID, label: p.folderLabel, path,
        device_id: p.deviceID, auto_accept: auto,
      });
      msgEl.className = "pp-msg form-msg ok";
      msgEl.textContent = "接收成功！文件正在过来，到「仪表盘」看进度";
      toast(`「${p.folderLabel}」接收成功`);
      pollStatus();
    } catch (err) {
      msgEl.className = "pp-msg form-msg bad";
      msgEl.textContent = friendly(err);
    }
  }, "接收中…");
});

$("btnBrowseNew").onclick = async () => {
  if (!hasPicker()) { toast("请直接粘贴文件夹路径"); return; }
  await chooseFolder($("inFolderPath"));
};

$("addFolderForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = $("addFolderMsg");
  const share = [...document.querySelectorAll("#newProjectDevices input:checked")].map((i) => i.value);
  await withLoading($("btnAddFolder"), async () => {
    msg.className = "form-msg";
    msg.textContent = "正在创建…";
    try {
      const r = await api("POST", "/api/folder/add", {
        path: $("inFolderPath").value.trim(),
        label: $("inFolderLabel").value.trim(),
        share_with: share,
      });
      msg.className = "form-msg ok";
      msg.textContent = r.shared.length ? "创建成功，已发出共享邀请" : "创建成功，正在首次扫描";
      $("inFolderPath").value = "";
      $("inFolderLabel").value = "";
      toast(`项目创建成功${r.shared.length ? `，共享邀请已发给 ${r.shared.length} 台电脑` : ""}`);
      pollStatus();
      renderNewProjectDevices();
    } catch (err) {
      msg.className = "form-msg bad";
      msg.textContent = friendly(err);
    }
  }, "创建中…");
});

function renderFolderList() {
  if (!LAST_STATUS) return;
  $("folderList").innerHTML = LAST_STATUS.folders.map(folderCard).join("") ||
    emptyWith("第12弹-加油.png", "还没有同步项目，在上面建一个吧");
}

/* ---------------- 动态 ---------------- */

function renderEvents(events) {
  $("eventEmpty").classList.add("hidden");
  const box = $("eventList");
  const rows = events.map((e) =>
    `<div class="event ${e.level}"><span class="t">${ts(e.ts)}</span><span>${esc(e.text)}</span></div>`
  );
  box.insertAdjacentHTML("afterbegin", rows.join(""));
  while (box.children.length > 120) box.lastChild.remove();
}

/* ---------------- 关于 / 反馈 / 更新 ---------------- */

let FEEDBACK_CONFIGURED = false;

$("btnFeedback").onclick = async () => {
  const text = $("inFeedback").value.trim();
  if (!text) { toast("先写点什么再发"); return; }
  await withLoading($("btnFeedback"), async () => {
    if (!FEEDBACK_CONFIGURED) {
      await copyText(text);
      $("fbMsg").textContent = "反馈渠道还在搭建，内容已复制，去个人主页找我就行";
      return;
    }
    try {
      const r = await api("POST", "/api/feedback", { text });
      if (r.ok) { toast("已送达，谢谢你！"); $("inFeedback").value = ""; }
    } catch (e) {
      await copyText(text);
      $("fbMsg").textContent = "发送失败，内容已复制，去个人主页找我即可";
    }
  }, "发送中…");
};

async function loadVersion() {
  try {
    const v = await api("GET", "/api/version");
    $("verBadge").textContent = "v" + v.version;
    $("verBadge").onclick = () => showChangelog(v);
    const u = v.update || {};
    if (u.enabled && u.has_update) {
      $("updateBanner").classList.remove("hidden");
      $("updateText").textContent = `发现新版本 v${u.remote_version}（现在 v${v.version}）`;
      $("btnUpdate").onclick = () => {
        openExternal(u.download_url || "https://github.com/lyzbcy/laoyu-sync/releases");
        toast("已打开下载页；下载慢的话过会儿再试");
      };
      $("btnChangelog2").onclick = () => showChangelog(v);
    }
  } catch (e) { /* ignore */ }
}

$("btnCheckUpdate").onclick = async () => {
  await withLoading($("btnCheckUpdate"), async () => {
    $("checkUpdateMsg").textContent = "正在打听最新版本…";
    try {
      const r = await api("POST", "/api/version/check");
      const u = r.update || {};
      $("checkUpdateMsg").textContent = u.enabled
        ? (u.has_update ? `有新版本 v${u.remote_version}！顶部有更新按钮` : "已经是最新版，粒子都在正确位置上")
        : "更新源还没接好（等仓库上线）";
    } catch (e) { $("checkUpdateMsg").textContent = friendly(e); }
  }, "检查中…");
};

function showChangelog(v) {
  infoModal("更新日志", v.changelog.map((c) =>
    `<div class="chg-item"><b>v${esc(c.ver)}</b> <span class="mut small">${esc(c.date)}</span>
     <ul>${c.items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul></div>`
  ).join(""));
}

/* ---------------- 启动 ---------------- */

async function loadMeta() {
  try {
    const meta = await api("GET", "/api/meta");
    FEEDBACK_CONFIGURED = !!meta.feedback_url_configured;
    HAS_PICKER = !!meta.has_window_picker;
  } catch (e) { /* ignore */ }
}

function boot() {
  route();
  loadMeta();
  pollStatus();
  pollEvents();
  pollPending();
  loadVersion();
}

boot();  // 必须放在所有声明之后（会引用 PAGES 等 const）
