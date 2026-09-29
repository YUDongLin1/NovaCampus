#!/usr/bin/env python3
"""P4b-0 复核补充:admin 角色的浏览器走查(回执 §六.2 自认未做,这里补上)。

产出 docs/p4b0/evidence/after/13_admin_main.png + 把断言并入 dom_probes.json 的 13_admin_main 键。
跑法:/d/anaconda3/python.exe docs/p4b0/admin_probe.py
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
OUT = r"E:\AILearn\NovaCampus\docs\p4b0\evidence\after"
PORT = 9346
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = os.path.join(os.environ.get("TEMP", "."), "nova-p4b0-admin-profile")

proc = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                         "--remote-debugging-port=%d" % PORT, "--remote-allow-origins=*",
                         "--user-data-dir=%s" % PROFILE, "--no-proxy-server",
                         "--window-size=1440,900", "--hide-scrollbars",
                         "--force-device-scale-factor=1", "--disable-extensions", "about:blank"])
for _ in range(60):
    try:
        if requests.get("http://127.0.0.1:%d/json/version" % PORT, timeout=1).ok:
            break
    except Exception:
        pass
    time.sleep(0.5)

tab = [t for t in requests.get("http://127.0.0.1:%d/json/list" % PORT, timeout=5).json()
       if t["type"] == "page"][0]
ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=180, suppress_origin=True)
mid = [0]
cons = {"error": [], "warning": [], "exceptions": []}


def cmd(method, **p):
    mid[0] += 1
    ws.send(json.dumps({"id": mid[0], "method": method, "params": p}))
    while True:
        m = json.loads(ws.recv())
        if m.get("id") == mid[0]:
            if "error" in m:
                raise RuntimeError("%s -> %s" % (method, m["error"]))
            return m.get("result", {})
        evt(m)


def evt(m):
    mm, p = m.get("method", ""), m.get("params", {})
    if mm == "Runtime.exceptionThrown":
        cons["exceptions"].append(str(p)[:200])
    elif mm in ("Runtime.consoleAPICalled", "Log.entryAdded"):
        lvl = p.get("type") or p.get("level")
        if lvl in ("error", "warning"):
            cons[lvl].append(str(p.get("args", p.get("text", "")))[:200])


def drain(sec):
    ws.settimeout(sec)
    end = time.time() + sec
    while time.time() < end:
        try:
            m = json.loads(ws.recv())
        except Exception:
            break
        if m.get("method"):
            evt(m)


def ev(expr):
    r = cmd("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
    if r.get("exceptionDetails"):
        raise RuntimeError(json.dumps(r["exceptionDetails"])[:300])
    return r.get("result", {}).get("value")


cmd("Page.enable"); cmd("Runtime.enable"); cmd("Log.enable")
cmd("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=1, mobile=False)
cmd("Page.navigate", url=BASE + "/")
drain(3.0)
ev("(function(){document.getElementById('u').value='admin';document.getElementById('p').value='admin123';return 1;})()")
ev("login()")
drain(4.0)
for _ in range(20):
    if ev("document.querySelectorAll('#docs tr').length") > 1:
        break
    drain(1.0)

probe = ev(r"""(function(){
  var tabs=[].slice.call(document.querySelectorAll('#tabs button')).map(function(b){
      return b.textContent.trim()+(b.classList.contains('active')?'(active)':'')+
             '[vis='+(b.style.display==='none'?'none':'shown')+']';});
  return {acct_name: document.getElementById('acct-name').textContent,
          acct_role: document.getElementById('acct-role').textContent,
          role_badge: document.getElementById('role-badge').textContent,
          tabs: tabs,
          kb_rows: document.querySelectorAll('#docs tr').length,
          first_row_has_del: /删除/.test((document.querySelector('#docs tr')||{innerText:''}).innerText),
          upload_row_vis: getComputedStyle(document.getElementById('upload-row')).display,
          import_row_vis: getComputedStyle(document.getElementById('import-row')).display,
          body_bg: getComputedStyle(document.body).backgroundColor,
          body_font: getComputedStyle(document.body).fontFamily.slice(0,46)};})()""")
png = base64.b64decode(cmd("Page.captureScreenshot", format="png")["data"])
io.open(os.path.join(OUT, "13_admin_main.png"), "wb").write(png)

path = os.path.join(OUT, "dom_probes.json")
d = json.load(io.open(path, encoding="utf-8"))
d["13_admin_main"] = probe
d["13_admin_console"] = {"error": len(cons["error"]), "warning": len(cons["warning"]),
                         "exceptions": len(cons["exceptions"])}
io.open(path, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
print("[admin] %s" % json.dumps(probe, ensure_ascii=False))
print("[admin] console error=%d warning=%d exceptions=%d, png=%d bytes"
      % (len(cons["error"]), len(cons["warning"]), len(cons["exceptions"]), len(png)))
ws.close()
try:
    CDP_URL = requests.get("http://127.0.0.1:%d/json/version" % PORT, timeout=3).json()["webSocketDebuggerUrl"]
    w2 = websocket.create_connection(CDP_URL, timeout=10, suppress_origin=True)
    w2.send(json.dumps({"id": 1, "method": "Browser.close"})); w2.close()
except Exception as e:
    print("(Browser.close 未成功: %s)" % e)
try:
    proc.wait(timeout=10)
except Exception:
    proc.kill()
