#!/usr/bin/env python3
"""P4c 第 0 步 BEFORE 取证(4):KB 页现状(分类下拉 + 文档表格)+ 截图

照 HANDOFF 坑 34 的做法:本机 headless Chrome + CDP 自己驱动、自己落盘 E: 盘。
坑 33: 断言 kb_rows>0、分类选项>0 才落盘(取到空值等于基线不存在)。
坑 34: 视口锁 1440x900(与 P4b-0 BEFORE 同几何);收尾只回收本脚本自己起的进程。

产出: docs/p4c/evidence/before/kb_page_probe.json
      docs/p4c/evidence/before/kb_page_before.png
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


# ---- 演示口令:一律从环境变量读,源码内不落明文(开源前脱敏要求) ----
def _demo_pw(role: str) -> str:
    r = role.upper()
    pwd = os.environ.get(f"NOVA_SEED_{r}_PASSWORD") or os.environ.get("NOVA_DEMO_PASSWORD", "")
    if not pwd:
        raise RuntimeError(
            f"未设置演示口令:请在 novaagent/.env 中写入 NOVA_DEMO_PASSWORD"
            f"(或 NOVA_SEED_{r}_PASSWORD)。")
    return pwd



BASE = "http://127.0.0.1:8900"
ROOT = Path(__file__).resolve().parent.parent.parent
OUT_DIR = ROOT / "docs" / "p4c" / "evidence" / "before"
PORT = 9347
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = os.path.join(os.environ.get("TEMP", "."), "nova-p4c-before-profile")
console = {"error": [], "warning": [], "exceptions": []}

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
        p = msg.get("params", {})
        if m == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails", {})
            console["exceptions"].append(str(d.get("text"))[:200])
        elif m in ("Runtime.consoleAPICalled", "Log.entryAdded"):
            lvl = p.get("type") or p.get("level") or "other"
            txt = " ".join(str(a.get("value", "")) for a in p.get("args", []))[:200]
            if lvl == "error":
                console["error"].append(txt)
            elif lvl == "warning":
                console["warning"].append(txt)

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


def main() -> int:
    proc = launch_chrome()
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
               "document.getElementById('p').value='%s';return 1;})()" % _demo_pw("counselor"))
        cdp.ev("login()")
        cdp.drain(3.0)
        cdp.ev("switchTab('kb')")
        # 等表格真的出来(坑 33: 空值不算基线)
        rows = 0
        for _ in range(40):
            rows = cdp.ev("document.querySelectorAll('#docs tr').length") or 0
            html = cdp.ev("document.getElementById('docs').innerHTML") or ""
            if rows and "empty" not in html:
                break
            time.sleep(0.5)
        cdp.drain(1.5)

        facts = {
            "url": BASE + "/",
            "role": "counselor",
            "viewport": "1440x900 (Emulation.setDeviceMetricsOverride 锁定)",
            "kb_rows": rows,
            "kb_filter_options": cdp.ev(
                "Array.from(document.querySelectorAll('#kb-cat-filter option')).map(o=>o.textContent)"),
            "kb_first_row_text": (cdp.ev(
                "document.querySelector('#docs tr') ? document.querySelector('#docs tr').innerText : ''") or "")[:200],
            "has_folder_tree": cdp.ev("!!document.getElementById('folder-tree')"),
            "has_at_picker": cdp.ev("!!document.getElementById('at-picker')"),
            "has_upload_row": cdp.ev("!!document.getElementById('upload-row')"),
            "has_import_row": cdp.ev("!!document.getElementById('import-row')"),
            "pane_kb_visible": cdp.ev("!!document.getElementById('pane-kb') && "
                                      "document.getElementById('pane-kb').classList.contains('active')"),
            "console": {"error": console["error"][:5], "warning": console["warning"][:5],
                        "exceptions": console["exceptions"][:5]},
        }
        assert facts["kb_rows"] > 0, f"KB 表格取到 0 行——基线无效(坑 33),禁止落盘: {facts}"
        assert len(facts["kb_filter_options"]) > 1, "分类下拉为空——基线无效,禁止落盘"

        data = base64.b64decode(cdp.cmd("Page.captureScreenshot", format="png")["data"])
        png = OUT_DIR / "kb_page_before.png"
        io.open(png, "wb").write(data)
        facts["screenshot"] = {"file": png.name, "bytes": len(data)}
        (OUT_DIR / "kb_page_probe.json").write_text(
            json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8")
        print("[OK] kb_page_probe.json + kb_page_before.png 已落盘")
        print(f"     kb_rows={facts['kb_rows']} 分类选项={len(facts['kb_filter_options'])} "
              f"folder_tree={facts['has_folder_tree']} @picker={facts['has_at_picker']} "
              f"console_error={len(console['error'])}")
        return 0
    finally:
        try:
            requests.get(f"http://127.0.0.1:{PORT}/json/close/")
        except Exception:  # noqa: BLE001
            pass
        proc.kill()  # 只回收本脚本自己起的 headless Chrome


if __name__ == "__main__":
    sys.exit(main())
