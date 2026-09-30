#!/usr/bin/env python3
"""P4c UI 验证(CDP, 照坑 34 做法): KB 页文件夹树 + @ 选择器 + 芯片, 断言非空才落盘。

产出: docs/p4c/evidence/after/{ui_checks.json, kb_page_after.png, at_picker.png}
"""
from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests
import websocket

BASE = "http://127.0.0.1:8900"
ROOT = Path(__file__).resolve().parent.parent.parent
OUT_DIR = ROOT / "docs" / "p4c" / "evidence" / "after"
PORT = 9349
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = os.path.join(os.environ.get("TEMP", "."), "nova-p4c-after-profile")
console = {"error": [], "exceptions": []}

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def launch_chrome():
    args = [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
            f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
            f"--user-data-dir={PROFILE}", "--no-proxy-server",
            "--window-size=1440,900", "--hide-scrollbars",
            "--force-device-scale-factor=1", "--disable-extensions", "about:blank"]
    proc = subprocess.Popen(args)
    for _ in range(60):
        try:
            if requests.get(f"http://127.0.0.1:{PORT}/json/version", timeout=1).ok:
                return proc
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    raise RuntimeError("Chrome 调试端口没起来")


class CDP:
    def __init__(self):
        tabs = requests.get(f"http://127.0.0.1:{PORT}/json/list", timeout=5).json()
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
                    raise RuntimeError(f"{method} -> {msg['error']}")
                return msg.get("result", {})
            self._event(msg)

    def _event(self, msg):
        m = msg.get("method", "")
        if m == "Runtime.exceptionThrown":
            d = msg.get("params", {}).get("exceptionDetails", {})
            console["exceptions"].append(str(d.get("text"))[:200])
        elif m in ("Runtime.consoleAPICalled", "Log.entryAdded"):
            p = msg.get("params", {})
            lvl = p.get("type") or p.get("level") or "other"
            txt = " ".join(str(a.get("value", "")) for a in p.get("args", []))[:200]
            if lvl == "error":
                console["error"].append(txt)

    def ev(self, expression, await_promise=True):
        r = self.cmd("Runtime.evaluate", expression=expression,
                     returnByValue=True, awaitPromise=await_promise)
        if r.get("exceptionDetails"):
            raise RuntimeError("eval 异常: " + json.dumps(r["exceptionDetails"])[:300])
        return r.get("result", {}).get("value")

    def drain(self, seconds):
        self.ws.settimeout(seconds)
        end = time.time() + seconds
        while time.time() < end:
            try:
                msg = json.loads(self.ws.recv())
            except Exception:  # noqa: BLE001
                break
            if msg.get("method"):
                self._event(msg)

    def shot(self, name):
        data = base64.b64decode(self.cmd("Page.captureScreenshot", format="png")["data"])
        io.open(OUT_DIR / name, "wb").write(data)
        return len(data)


def main() -> int:
    proc = launch_chrome()
    steps = []
    ok_all = True

    def step(name, cond, detail=""):
        nonlocal ok_all
        steps.append({"step": name, "pass": bool(cond), "detail": str(detail)[:300]})
        print(("[PASS] " if cond else "[FAIL] ") + name + (f" | {str(detail)[:110]}" if detail else ""))
        ok_all = ok_all and bool(cond)

    try:
        cdp = CDP()
        cdp.cmd("Runtime.enable")
        cdp.cmd("Log.enable")
        cdp.cmd("Page.enable")
        cdp.cmd("Emulation.setDeviceMetricsOverride", width=1440, height=900,
                deviceScaleFactor=1, mobile=False)
        cdp.cmd("Page.navigate", url=BASE + "/")
        cdp.drain(2.0)
        cdp.ev("(function(){document.getElementById('u').value='counselor';"
               "document.getElementById('p').value='counselor123';return 1;})()")
        cdp.ev("login()")
        cdp.drain(3.0)
        cdp.ev("switchTab('kb')")
        rows = 0
        for _ in range(40):
            rows = cdp.ev("document.querySelectorAll('#docs tr').length") or 0
            html = cdp.ev("document.getElementById('docs').innerHTML") or ""
            if rows and "empty" not in html:
                break
            time.sleep(0.5)
        cdp.drain(1.5)
        assert rows > 0, "KB 行为 0——坑 33 禁止落盘"

        tree_items = cdp.ev("document.querySelectorAll('#folder-tree .folder-item').length")
        step("C6 文件夹树渲染(全部文档/根目录入口)", tree_items >= 2, f"items={tree_items}")
        step("C6 新建文件夹按钮对员工可见",
             cdp.ev("document.getElementById('kb-new-folder').style.display !== 'none'"))
        step("C6 学段筛选下拉存在", cdp.ev("!!document.getElementById('kb-audience-filter')"))

        # UI 建夹 → 树里出现
        cdp.ev("newFolder()")
        cdp.ev("document.getElementById('nf-name').value='P4c UI 验证夹'")
        cdp.ev("createFolderSubmit(null)")
        cdp.drain(2.0)
        in_tree = cdp.ev("window._kbFolders.some(f=>f.name==='P4c UI 验证夹')")
        step("C6 UI 新建文件夹出现在树", bool(in_tree))
        kb_png = cdp.shot("kb_page_after.png")

        # @ 选择器: 键入 @ 唤起 → 列表非空 → 选中 → 芯片出现且问句无 @ 残留
        cdp.ev("document.getElementById('q').value='@'")
        cdp.ev("openAtPicker()")
        cdp.drain(1.5)
        n_items = cdp.ev("document.querySelectorAll('#at-picker .at-item').length")
        step("C4 @ 选择器弹出且选项非空", (cdp.ev("document.getElementById('at-picker').style.display") == 'block')
             and n_items > 0, f"items={n_items}")
        at_png = cdp.shot("at_picker.png")
        cdp.ev("(function(){var b=document.querySelector('#at-picker .at-item');b.click();return 1;})()")
        cdp.drain(0.5)
        q_value = cdp.ev("document.getElementById('q').value")
        chips = cdp.ev("document.querySelectorAll('#scope-chips .chip').length")
        step("C4 选中后 question 无 @ 残留", q_value == "", f"q={q_value!r}")
        step("C4 选中后范围芯片渲染", chips >= 1, f"chips={chips}")

        step("控制台零 error", len(console["error"]) == 0, console["error"][:3])

        # 清理 UI 建的夹
        cdp.ev("(async()=>{const f=window._kbFolders.find(x=>x.name==='P4c UI 验证夹');"
               "if(f) await api('/api/kb/folders/'+f.id+'?cascade=true',{method:'DELETE'});return 1;})()")
        cdp.drain(1.5)

        (OUT_DIR / "ui_checks.json").write_text(json.dumps({
            "kb_rows": rows, "kb_png_bytes": kb_png, "at_png_bytes": at_png,
            "at_items": n_items, "console": console, "steps": steps, "all_pass": ok_all,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n{'ALL PASS' if ok_all else 'HAS FAILURES'}")
        return 0 if ok_all else 1
    finally:
        try:
            requests.get(f"http://127.0.0.1:{PORT}/json/close/")
        except Exception:  # noqa: BLE001
            pass
        proc.kill()


if __name__ == "__main__":
    sys.exit(main())
