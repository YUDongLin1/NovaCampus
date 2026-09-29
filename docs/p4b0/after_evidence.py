#!/usr/bin/env python3
"""P4b-0 复核人取证脚本:用 CDP 驱动真浏览器(headless Chrome),把 after 证据写到 E 盘。

为什么自己写:P4b-0 会话与本次复核会话的 Chrome DevTools MCP 都因"工作区根不含 E: 盘"
拒绝 filePath(见 HANDOFF 坑与 memory),`evidence/after/` 只有 invariants.json。
本脚本用本机 websocket-client + Chrome remote debugging 直接 Page.captureScreenshot,
绕开该限制,产出与 `evidence/before/` **同名配对**的截图 + 同探针的 DOM 状态。

跑法(需 NovaAgent 在 :8900 且加载的是本分支代码):
    /d/anaconda3/python.exe docs/p4b0/after_evidence.py
产出:docs/p4b0/evidence/after/*.png、after/dom_probes.json、after/console_log.json
"""
import base64
import io
import json
import os
import subprocess
import sys
import time

import requests
import websocket

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = "http://127.0.0.1:8900"
OUT_DIR = r"E:\AILearn\NovaCampus\docs\p4b0\evidence\after"
PORT = 9345
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = os.path.join(os.environ.get("TEMP", "."), "nova-p4b0-after-profile")
probes = {}
console = {"error": [], "warning": [], "other": [], "exceptions": []}


def launch_chrome():
    args = [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
            "--remote-debugging-port=%d" % PORT, "--remote-allow-origins=*",
            "--user-data-dir=%s" % PROFILE, "--no-proxy-server",
            "--window-size=1440,900", "--hide-scrollbars", "--force-device-scale-factor=1",
            "--disable-extensions", "about:blank"]
    proc = subprocess.Popen(args)
    for _ in range(60):
        try:
            if requests.get("http://127.0.0.1:%d/json/version" % PORT, timeout=1).ok:
                return proc
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("Chrome 调试端口没起来")


class CDP:
    def __init__(self):
        tabs = requests.get("http://127.0.0.1:%d/json/list" % PORT, timeout=5).json()
        page = [t for t in tabs if t["type"] == "page"][0]
        self.ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=180,
                                             suppress_origin=True)
        self.mid = 0

    def cmd(self, method, **params):
        self.mid += 1
        mid = self.mid
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError("%s -> %s" % (method, msg["error"]))
                return msg.get("result", {})
            self._event(msg)

    def _event(self, msg):
        m = msg.get("method", "")
        p = msg.get("params", {})
        if m == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails", {})
            console["exceptions"].append(str(d.get("text")) + " | " + str(d.get("exception", {}).get("description"))[:300])
        elif m in ("Runtime.consoleAPICalled", "Log.entryAdded"):
            lvl = p.get("type") or p.get("level") or "other"
            txt = " ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", []))
            txt = txt or str(p.get("text", ""))[:300]
            src = p.get("source", "")
            if lvl in ("error", "warning"):
                console[lvl].append({"from": m, "source": src, "text": txt[:300], "url": p.get("url", "")})
            else:
                console["other"].append({"level": lvl, "text": txt[:200]})

    def ev(self, expression, await_promise=True):
        r = self.cmd("Runtime.evaluate", expression=expression,
                     returnByValue=True, awaitPromise=await_promise)
        if r.get("exceptionDetails"):
            raise RuntimeError("eval 异常: %s" % json.dumps(r["exceptionDetails"])[:400])
        return r.get("result", {}).get("value")

    def shot(self, name):
        data = base64.b64decode(self.cmd("Page.captureScreenshot", format="png")["data"])
        io.open(os.path.join(OUT_DIR, name), "wb").write(data)
        return len(data)


def drain_events(cdp, seconds):
    """被动收 events(控制台报错是事件推送,不 cmd 就收不到)。"""
    cdp.ws.settimeout(seconds)
    end = time.time() + seconds
    while time.time() < end:
        try:
            msg = json.loads(cdp.ws.recv())
        except websocket.WebSocketTimeoutException:
            break
        except websocket.WebSocketConnectionClosedException:
            break
        if msg.get("method"):
            cdp._event(msg)


def login(cdp, user, pwd):
    cdp.cmd("Page.navigate", url=BASE + "/")
    drain_events(cdp, 2.0)
    cdp.ev("(function(){document.getElementById('u').value=%r;"
           "document.getElementById('p').value=%r;return 1;})()" % (user, pwd))
    cdp.ev("login()")
    drain_events(cdp, 3.0)


def wait_docs(cdp, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        n = cdp.ev("document.querySelectorAll('#docs tr').length")
        if n and 'class="empty"' not in (cdp.ev("document.getElementById('docs').innerHTML") or ""):
            return n
        time.sleep(0.5)
    return cdp.ev("document.querySelectorAll('#docs tr').length")


COMMON = r"""(function(){
  var tabs=[].slice.call(document.querySelectorAll('#tabs button')).map(function(b){
      return b.textContent.trim()+(b.classList.contains('active')?'(active)':'')+
             '[vis='+(b.style.display==='none'?'none':'shown')+']';});
  var msgs=[].slice.call(document.querySelectorAll('#messages .msg'));
  return {
    acct_name: document.getElementById('acct-name').textContent,
    acct_role: document.getElementById('acct-role').textContent,
    role_badge: document.getElementById('role-badge').textContent,
    tabs: tabs,
    kb_rows: document.querySelectorAll('#docs tr').length,
    upload_row_vis: getComputedStyle(document.getElementById('upload-row')).display,
    import_row_vis: getComputedStyle(document.getElementById('import-row')).display,
    body_font: getComputedStyle(document.body).fontFamily.slice(0,60),
    body_bg: getComputedStyle(document.body).backgroundColor,
    toast: document.getElementById('toast').textContent,
    msg_total: msgs.length,
    bot_msgs: msgs.filter(function(m){return m.classList.contains('bot');}).length
  };})()"""


def main():
    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)
    proc = launch_chrome()
    cdp = CDP()
    cdp.cmd("Page.enable")
    cdp.cmd("Runtime.enable")
    cdp.cmd("Log.enable")
    # 视口锁成与 BEFORE 完全一致的 1440x900(headless=new 的 window-size 会扣掉窗口边框,
    # 几何不一致会让像素差虚高),这样同名截图配对才有意义。
    cdp.cmd("Emulation.setDeviceMetricsOverride", width=1440, height=900,
            deviceScaleFactor=1, mobile=False)

    # ---------- 01 登录页(冷启动,无 token) ----------
    cdp.cmd("Network.clearBrowserCache")
    cdp.cmd("Storage.clearDataForOrigin", origin=BASE, storageTypes="local_storage,cookies")
    cdp.cmd("Page.navigate", url=BASE + "/")
    drain_events(cdp, 3.0)
    probes["01_login_page"] = cdp.ev(r"""(function(){
      var box=document.getElementById('login-box');
      return {heading: document.querySelector('#login-box h2').textContent,
              sub: document.querySelector('#login-box .sub').textContent,
              demo_cred: document.querySelector('#login-box .demo-cred').textContent,
              user_default: document.getElementById('u').value,
              login_box_visible: getComputedStyle(box).display,
              seal: document.querySelector('.login-seal').textContent,
              css_applied: getComputedStyle(document.querySelector('.btn-login')).backgroundColor,
              btn_bg_image: getComputedStyle(document.querySelector('.btn-login')).backgroundImage.slice(0,80),
              login_box_style: getComputedStyle(document.getElementById('login-box')).borderRadius};})()""")
    print("[01] 登录页 bytes=", cdp.shot("01_login_page.png"))
    cdp.ev("(function(){document.getElementById('p').value='wrong-pass';})()")
    cdp.ev("login()")
    drain_events(cdp, 2.0)
    probes["01_login_fail"] = {"login_err": cdp.ev("document.getElementById('login-err').textContent"),
                              "login_box_still_visible": cdp.ev("getComputedStyle(document.getElementById('mask')).display")}
    print("[01-fail] bytes=", cdp.shot("01_login_fail.png"))

    # ---------- 02 student ----------
    login(cdp, "student", "student123")
    wait_docs(cdp)
    probes["02_student_main"] = cdp.ev(COMMON)
    print("[02] student kb_rows=", probes["02_student_main"]["kb_rows"],
          "bytes=", cdp.shot("02_student_main.png"))

    # ---------- counselor 登录:03 问答 / 04 KB 分块 / 05 设置 / 06 周报 / 07 拒答 ----------
    login(cdp, "counselor", "counselor123")
    wait_docs(cdp)
    probes["10_counselor_main"] = cdp.ev(COMMON)
    cdp.shot("10_counselor_main.png")

    cdp.ev("document.getElementById('q').value='研究生申请休学需要提交哪些材料?'")
    cdp.ev("send()")
    drain_events(cdp, 25.0)
    probes["03_chat_sources"] = cdp.ev(r"""(function(){
      var bots=[].slice.call(document.querySelectorAll('#messages .msg.bot'));
      var last=bots[bots.length-1];
      return {bot_msgs: bots.length,
              last_text_head: last? last.innerText.slice(0,180):null,
              sources_blocks: last? [].slice.call(last.querySelectorAll('.sources'))
                 .map(function(m){return m.innerText.replace(/\n/g,' | ');}):[],
              streaming_left: document.querySelectorAll('#messages .streaming').length};})()""")
    print("[03] sources=", probes["03_chat_sources"]["sources_blocks"], "bytes=", cdp.shot("03_chat_sources.png"))

    cdp.ev(r"document.getElementById('q').value='宿舍空调坏了怎么报修，维修师傅电话多少?'")
    cdp.ev("send()")
    drain_events(cdp, 20.0)
    probes["07_refusal_template"] = cdp.ev(r"""(function(){
      var bots=[].slice.call(document.querySelectorAll('#messages .msg.bot'));
      var last=bots[bots.length-1];
      var t=last? last.innerText:'';
      return {question_id:'rind-04',
              last_bot_head: t.slice(0,220),
              has_exit_block: t.indexOf('建议咨询出口')>=0,
              exits: t.slice(t.indexOf('建议咨询出口')).split('\n').slice(0,4),
              has_citation: /\[\d+\]/.test(t)};})()""")
    cdp.shot("07_chat_tool_trace.png")

    cdp.ev("switchTab('kb')")
    drain_events(cdp, 3.0)
    cdp.ev("(function(){var s=document.getElementById('kb-cat-filter');s.value='政策文件';s.onchange();})()")
    drain_events(cdp, 3.0)
    probes["04_kb_filter"] = {
        "filter_value": cdp.ev("document.getElementById('kb-cat-filter').value"),
        "rows": cdp.ev(r"[].slice.call(document.querySelectorAll('#docs tr')).slice(0,3).map(function(r){return r.innerText.replace(/\n/g,' | ');})")}
    cdp.ev("(function(){document.getElementById('kb-cat-filter').value='';loadDocs();})()")
    drain_events(cdp, 3.0)
    cdp.ev("(function(){var rows=[].slice.call(document.querySelectorAll('#docs tr'));"
           "var r=rows.filter(function(x){return x.innerText.indexOf('收费公示')>=0;})[0]||rows[0];"
           "r.querySelector('button.link').click();return 1;})()")
    drain_events(cdp, 4.0)
    probes["04_kb_modal"] = {
        "modal_title": cdp.ev("document.getElementById('modal-title').textContent"),
        "modal_visible": cdp.ev("document.getElementById('modal').style.display"),
        "modal_body_head": cdp.ev("document.getElementById('modal-body').innerText.slice(0,150)")}
    print("[04] modal=", probes["04_kb_modal"]["modal_title"], "bytes=", cdp.shot("04_kb_chunks_modal.png"))
    cdp.ev("closeModal()")

    cdp.ev("openSettings()")
    drain_events(cdp, 4.0)
    probes["05_settings"] = {
        "modal_title": cdp.ev("document.getElementById('modal-title').textContent"),
        "modal_head": cdp.ev(r"document.getElementById('modal-body').innerText.slice(0,110).replace(/\n/g,'\\n')"),
        "model_radios": cdp.ev("[].slice.call(document.querySelectorAll('#modal-body input')).map(function(i){return i.value;})"),
        "has_custom_form": cdp.ev("!!document.querySelector('#modal-body textarea, #modal-body input[type=text], #modal-body input:not([type=radio])')")}
    print("[05] settings bytes=", cdp.shot("05_settings_modal.png"))
    cdp.ev("closeModal()")

    cdp.ev("switchTab('weekly')")
    drain_events(cdp, 4.0)
    probes["06_weekly_tab"] = cdp.ev(r"""(function(){return {
      pane_active: document.getElementById('pane-weekly').classList.contains('active'),
      w_cat: document.getElementById('w-cat').value,
      expand_btn_label: document.getElementById('expand-btn').textContent,
      archive_disabled: document.getElementById('archive-btn').disabled,
      archived: [].slice.call(document.querySelectorAll('#archived li')).slice(0,4).map(function(li){return li.innerText.replace(/\n/g,' ');})};})()""")
    cdp.ev("document.getElementById('w-content').value='和小王谈了补考压力，担心挂科。'")
    cdp.ev("expandFragment()")
    drain_events(cdp, 30.0)
    probes["06_weekly_expand"] = {"expanded_head": (cdp.ev("document.getElementById('w-content').value") or "")[:120]}
    cdp.ev("document.getElementById('w-content').value='和小王谈了补考压力，担心挂科。'")
    cdp.shot("06_weekly_counselor.png")

    cdp.ev("document.getElementById('w-start').value='2026-09-21'")
    cdp.ev("renderReport()")
    drain_events(cdp, 45.0)
    probes["06_weekly_report"] = {
        "weekly_out_visible": cdp.ev("getComputedStyle(document.getElementById('weekly-out')).display"),
        "weekly_out_head": (cdp.ev("document.getElementById('weekly-out').innerText") or "")[:160],
        "archive_btn_enabled": cdp.ev("!document.getElementById('archive-btn').disabled")}
    print("[06] report bytes=", cdp.shot("06_weekly_report.png"))

    # ---------- 资源加载与内容类型(网络层) ----------
    # ---------- 08 合成 renderMeta 探针(与 BEFORE 同输入,零运行时漂移的逐字比对) ----------
    probes["08_rendermeta_synthetic"] = {
        "renderMeta_trace_sample": cdp.ev(r"""(function(){
          var host=document.createElement('div'); host.className='msg bot';
          document.getElementById('messages').appendChild(host);
          renderMeta(host, [{title:'SAMPLE-TITLE-A',score:0.9},{title:'SAMPLE-TITLE-B',score:0.8}],
                     [{tool:'add_fragment'}]);
          var out=[].slice.call(host.querySelectorAll('.sources'))
                    .map(function(s){return s.innerText.replace(/\n/g,' | ');}).join(' | ');
          host.remove(); return out;})()""")}
    # ---------- 01 登录页可见文本全集(用于"UI 文案无丢失"对账) ----------
    probes["12_login_visible_text"] = cdp.ev("document.getElementById('login-box').innerText")
    cdp.cmd("Storage.clearDataForOrigin", origin=BASE, storageTypes="local_storage,cookies")
    cdp.cmd("Page.navigate", url=BASE + "/")
    drain_events(cdp, 3.0)
    probes["12_login_visible_text"] = cdp.ev("document.getElementById('login-box').innerText")

    probes["11_assets"] = cdp.ev(r"""(async function(){
      var urls=['/css/theme.css','/js/api.js','/js/ui.js','/js/chat.js','/js/kb.js','/js/weekly.js'];
      var out=[];
      for (var i=0;i<urls.length;i++){
        var r=await fetch(urls[i]); var t=await r.text();
        out.push({url:urls[i], status:r.status, ct:r.headers.get('content-type'),
                  bytes:new Blob([t]).size});}
      return out;})()""")
    json.dump(probes, io.open(os.path.join(OUT_DIR, "dom_probes.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    json.dump(console, io.open(os.path.join(OUT_DIR, "console_log.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("\n[CONSOLE] error=%d warning=%d exceptions=%d" % (len(console["error"]), len(console["warning"]),
                                                             len(console["exceptions"])))
    for e in console["error"][:6]:
        print("   ERR ", e)
    for e in console["warning"][:6]:
        print("   WARN", e)
    for e in console["exceptions"][:6]:
        print("   EXC ", e)
    print("\n[SUM] 证据已写入 %s" % OUT_DIR)
    cdp.ws.close()
    try:
        CDP().cmd("Browser.close")
    except Exception:
        pass
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()          # 只回收本脚本自己起的 headless Chrome,绝不动用户的浏览器


if __name__ == "__main__":
    main()
