#!/usr/bin/env python3
"""AIOps MCP Server(NovaCampus P3b)— 把 P3a 监控栈包成 Agent 可调用的只读取证工具集

定位:P3c NovaAgent 诊断链的"手"——收告警→查指标→捞日志→查变更→跑预案。
全部工具**只读**:只打 Prometheus 的 /api/v1/query* 只读端点、只 `docker logs` 读容器
stdout/stderr、playbook 只做取证序列;**绝不执行 restart/rm/exec 等任何写操作**。

工具(7 个,返回统一 _ok/_err JSON 字符串):
  get_service_status  一眼看全局:up/池/CPU/uptime
  list_alerts         收告警(依赖 Prometheus rule_files 加载 alerts.yml,见 C1)
  query_metrics       查 promql(即时/区间),带只读防护与点数/序列上限裁剪
  query_logs          捞容器日志(宿主 docker logs --since --tail,只读)+状态码分布
  query_changes       查变更:重启/故障注入窗口/注入触发次数(每条带出处)
  run_playbook        跑只读取证预案(playbooks.yml;恢复动作仅输出建议命令)
  gather_diagnosis    一键串起 status→alerts→metrics→logs→changes,带证据链

运行(宿主机 venv 形态,P3b 环境决策——容器内无 docker CLI/socket,实测见 docs/P3B.md):
  uv venv .venv && uv pip install "mcp==2.2.0"
  NO_PROXY="127.0.0.1,localhost" .venv/Scripts/python.exe server.py   # :18081 /sse /mcp
环境变量:PROMETHEUS_URL(默认 http://127.0.0.1:9090)、AIOPS_PORT(18081)、
  AIOPS_DOCKER_CONTAINER_MAP(service→容器名,逗号分隔)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from mcp.server.mcpserver import MCPServer

PROM_BASE = os.environ.get("PROMETHEUS_URL", "http://127.0.0.1:9090").rstrip("/")
CONTAINER_MAP = dict(
    kv.split("=", 1) for kv in os.environ.get(
        "AIOPS_DOCKER_CONTAINER_MAP",
        "ykt=nova-sims-ykt-1,jiaowu=nova-sims-jiaowu-1",
    ).split(",") if "=" in kv
)
SERVICES = sorted(CONTAINER_MAP) or ["ykt", "jiaowu"]
TZ8 = timezone(timedelta(hours=8))  # 输出统一 +0800 可读时间

MAX_SERIES = 200        # query_metrics 单次返回序列上限
MAX_POINTS = 200        # query_metrics 单序列点数上限
MAX_LOG_LINES = 80      # query_logs 返回命中行上限

mcp = MCPServer(
    "aiops-readonly",
    instructions=(
        "AIOps 只读取证工具集(服务:SIMS 模拟校园系统 ykt/jiaowu)。"
        "标准诊断流程:1) get_service_status 看全局;2) list_alerts 收告警;"
        "3) query_metrics 用 promql 定位(池利用率/5xx 速率/CPU);"
        "4) query_logs 捞对应服务日志佐证;5) query_changes 看窗口内重启/故障注入;"
        "6) run_playbook 按预案走完整取证;想一次拿全就用 gather_diagnosis。"
        "所有工具只读,恢复类操作只会得到'建议命令,需人工执行'。"
    ),
)


def _ok(**kw) -> str:
    return json.dumps({"ok": True, **kw}, ensure_ascii=False)


def _err(msg: str) -> str:
    return json.dumps({"ok": False, "error": msg}, ensure_ascii=False)


def _fmt_ts(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=TZ8).strftime("%Y-%m-%d %H:%M:%S+0800")


def _fmt_val(v: Any) -> str:
    try:
        return f"{float(v):.4g}"
    except (TypeError, ValueError):
        return str(v)


def _parse_time(s: str) -> float:
    """接受 unix 秒(字符串/数字)或 ISO 本地时间(按 +0800 解释)。"""
    s = str(s).strip()
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return float(s)
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ8)
    return dt.timestamp()


class AiopsGuardError(Exception):
    """query_metrics 只读防护拒绝。"""


_ALLOWED_PROM_PATHS = ("/api/v1/query", "/api/v1/query_range",
                       "/api/v1/rules", "/api/v1/alerts")  # 四者皆为只读端点


def _prom_get(path: str, params: dict, timeout: float = 10.0) -> dict:
    """只允许打 Prometheus 只读端点(query*/rules/alerts);写类/admin 路径一律拒绝。
    query_metrics 工具在此之上另行只允许 query/query_range。"""
    if path not in _ALLOWED_PROM_PATHS:
        raise AiopsGuardError(
            f"非法 Prometheus 路径: {path}(只允许 {' / '.join(_ALLOWED_PROM_PATHS)} 只读端点)"
        )
    url = f"{PROM_BASE}{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    if data.get("status") != "success":
        raise AiopsGuardError(f"Prometheus 返回错误: {str(data.get('error'))[:200]}")
    return data["data"]


def _job_filter(service: str) -> str:
    """service 名转 promql job 匹配串;空=全部。 service 只允许字母数字下划线,防 promql 注入。"""
    if not service:
        return "ykt|jiaowu"
    if not re.fullmatch(r"[a-zA-Z0-9_]+", service):
        raise AiopsGuardError(f"非法 service 名: {service!r}")
    return re.escape(service)


@mcp.tool()
def get_service_status(service: str = "") -> str:
    """一眼看全局:各模拟服务的存活/连接池/CPU/运行时长。

    何时调用:诊断第一步,先看全局再决定取证方向;也用于确认服务恢复。
    入参:service——ykt 或 jiaowu,缺省返回全部。
    返回字段:services[{job, up(1/0), pool_size, pool_in_use, pool_waiting,
    pool_utilization_pct(占池百分比,1 位小数), process_cpu_percent(多核口径,100%=1 核),
    uptime_seconds(进程已运行秒数)}];source=各指标的 promql 出处。
    """
    try:
        job = _job_filter(service)
        now = time.time()
        out: list[dict] = []
        probes = {
            "up": "up",
            "pool_size": "app_db_pool_size",
            "pool_in_use": "app_db_pool_in_use",
            "pool_waiting": "app_db_pool_waiting",
            "cpu": "process_cpu_percent",
            "start_time": "process_start_time_seconds",
        }
        merged: dict[str, dict] = {}
        for key, metric in probes.items():
            data = _prom_get("/api/v1/query", {"query": f"{metric}{{job=~\"{job}\"}}"})
            for r in data.get("result", []):
                j = r["metric"].get("job", "?")
                merged.setdefault(j, {})[key] = float(r["value"][1])
        for j, m in sorted(merged.items()):
            size = m.get("pool_size", 0) or 0
            in_use = m.get("pool_in_use", 0) or 0
            out.append({
                "job": j,
                "up": int(m.get("up", 0)),
                "pool_size": size,
                "pool_in_use": in_use,
                "pool_waiting": m.get("pool_waiting", 0),
                "pool_utilization_pct": round(in_use / size * 100, 1) if size else None,
                "process_cpu_percent": round(m.get("cpu", 0), 1),
                "uptime_seconds": round(now - m["start_time"]) if "start_time" in m else None,
            })
        return _ok(
            services=out,
            source="prometheus /api/v1/query: up, app_db_pool_size/in_use/waiting, "
                   "process_cpu_percent, process_start_time_seconds",
        )
    except (AiopsGuardError, urllib.error.URLError, TimeoutError, KeyError) as e:
        return _err(f"get_service_status 失败: {e}")


@mcp.tool()
def list_alerts(state: str = "all") -> str:
    """收告警:列出 Prometheus 告警(rules 来自 sims/prometheus/alerts.yml,C1)。

    何时调用:诊断第二步(或被"有告警吗"直接问起);与 run_playbook 联动定位。
    入参:state——all/firing/pending,缺省 all。
    返回字段:rules_count(已加载规则数)、alerts[{alertname, state, job, severity,
    value, active_at, description}]、source。
    注意:若 Prometheus 未加载任何规则,如实返回"无告警规则"并给出排查提示,
    **不会编造告警**;重启容器后 fault_active 序列缺失的已知限制见 docs/P3B.md。
    """
    if state not in ("all", "firing", "pending"):
        return _err(f"state 仅支持 all/firing/pending,收到 {state!r}")
    try:
        rules = _prom_get("/api/v1/rules", {})
        groups = rules.get("groups", [])
        rule_names = [r["name"] for g in groups for r in g.get("rules", [])]
        if not rule_names:
            return _ok(
                rules_count=0, alerts=[],
                note="Prometheus 未加载任何告警规则——list_alerts 无真实数据源;"
                     "请检查 sims/prometheus/alerts.yml 与 docker-compose.sims.yml 的 rule_files 挂载",
                source="prometheus /api/v1/rules + /api/v1/alerts",
            )
        alerts_raw = _prom_get("/api/v1/alerts", {}).get("alerts", [])
        alerts = []
        for a in alerts_raw:
            if state != "all" and a.get("state") != state:
                continue
            labels = a.get("labels", {})
            ann = a.get("annotations", {})
            alerts.append({
                "alertname": labels.get("alertname"),
                "state": a.get("state"),
                "job": labels.get("job"),
                "severity": labels.get("severity"),
                "value": _fmt_val(a.get("value")),
                "active_at": a.get("activeAt"),
                "summary": ann.get("summary"),
                "description": ann.get("description"),
            })
        return _ok(
            rules_count=len(rule_names), rules=rule_names, alerts=alerts,
            state_filter=state,
            source="prometheus /api/v1/rules + /api/v1/alerts(规则文件 sims/prometheus/alerts.yml)",
        )
    except (AiopsGuardError, urllib.error.URLError, TimeoutError, KeyError) as e:
        return _err(f"list_alerts 失败: {e}")


@mcp.tool()
def query_metrics(promql: str, start: str = "", end: str = "",
                  step_s: float = 15.0, window_s: float | None = None) -> str:
    """查指标:执行 promql 即时/区间查询(LLM 友好输出,时间 +0800、数值 4 位有效)。

    何时调用:定位量化证据——池利用率(app_db_pool_in_use/app_db_pool_size)、
    5xx 速率(rate(http_requests_total{status=~"5.."}[30s]))、CPU(process_cpu_percent)等。
    入参:promql——PromQL 表达式(禁止分号/多语句);start/end——区间模式的时间
    (unix 秒或 ISO"YYYY-MM-DDTHH:MM:SS",按 +0800 解释);window_s——回看窗口秒数
    (传值如 300 即走 /api/v1/query_range,取 now-window→now;缺省 None=即时查询);
    step_s——区间步长(1~300s,默认 15)。
    返回字段:mode(instant/range)、series_total/series_returned/truncated(超 200 序列截断声明)、
    points_per_series/truncated_points(超 200 点截断声明)、
    results[{metric, values[{time(+0800 可读), value(4 位有效)}]}]、source。
    只读防护:仅允许 /api/v1/query 与 /api/v1/query_range;超时 10s。
    """
    promql = (promql or "").strip()
    if not promql:
        return _err("promql 不能为空")
    if ";" in promql:
        return _err("promql 含分号(多语句),已拒绝——本工具只接受单条只读查询")
    if len(promql) > 2000:
        return _err("promql 过长(>2000 字符),已拒绝")
    try:
        mode = "instant"
        params: dict[str, Any] = {"query": promql}
        used: dict[str, float] | None = None
        if start or end or (window_s is not None and float(window_s) > 0):
            mode = "range"
            end_ts = _parse_time(end) if end else time.time()
            w = float(window_s) if window_s else 300.0
            start_ts = _parse_time(start) if start else end_ts - w
            step = min(max(float(step_s or 15.0), 1.0), 300.0)
            params.update({"start": start_ts, "end": end_ts, "step": step})
            used = {"start": start_ts, "end": end_ts, "step": step}
        data = _prom_get(f"/api/v1/{'query_range' if mode == 'range' else 'query'}", params)
        result = data.get("result", [])
        series_total = len(result)
        truncated_series = series_total > MAX_SERIES
        shown = result[:MAX_SERIES]
        out = []
        points_per_series = 0
        truncated_points = False
        for r in shown:
            if mode == "range":
                vals = r.get("values", [])
                points_per_series = max(points_per_series, len(vals))
                truncated_points = truncated_points or len(vals) > MAX_POINTS
                vals_shown = vals[:MAX_POINTS]
                values = [{"time": _fmt_ts(v[0]), "value": _fmt_val(v[1])} for v in vals_shown]
            else:
                v = r.get("value")
                values = [{"time": _fmt_ts(v[0]), "value": _fmt_val(v[1])}] if v else []
            out.append({"metric": r.get("metric", {}), "values": values})
        resp: dict[str, Any] = {
            "promql": promql, "mode": mode,
            "series_total": series_total, "series_returned": len(out),
            "truncated": truncated_series or truncated_points,
            "results": out,
            "source": f"prometheus /api/v1/{'query_range' if mode == 'range' else 'query'}",
        }
        if truncated_series:
            resp["truncated_note"] = f"序列超 {MAX_SERIES} 上限,已截断(仅返回前 {MAX_SERIES} 条)"
        if truncated_points:
            resp["points_per_series"] = points_per_series
            resp["truncated_note"] = (resp.get("truncated_note", "") +
                                      f" 单序列点数超 {MAX_POINTS} 上限,已截断").strip()
        if mode == "range":
            resp["start"] = _fmt_ts(used["start"])
            resp["end"] = _fmt_ts(used["end"])
            resp["step_s"] = used["step"]
        return _ok(**resp)
    except (AiopsGuardError, urllib.error.URLError, TimeoutError, ValueError) as e:
        return _err(f"query_metrics 失败: {e}")


def _docker_logs(service: str, minutes: float, tail: int) -> tuple[int, str, str]:
    """只读 `docker logs --since --tail`(容器 stdout/stderr);不做任何写/exec 操作。"""
    container = CONTAINER_MAP.get(service)
    if not container:
        raise AiopsGuardError(
            f"未知 service={service!r}(可用: {sorted(CONTAINER_MAP)})"
        )
    cmd = ["docker", "logs", "--since", f"{max(1, int(minutes))}m",
           "--tail", str(max(1, int(tail))), container]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=20)
    if proc.returncode != 0:
        raise RuntimeError(f"docker logs 退出码 {proc.returncode}: {proc.stderr[:200]}")
    return len((proc.stdout + proc.stderr).splitlines()), proc.stdout, proc.stderr


_STATUS_RE = re.compile(r'"(?:GET|POST|PUT|DELETE|PATCH|HEAD) \S+ HTTP/1\.[01]" (\d{3})')


@mcp.tool()
def query_logs(service: str, keyword: str = "", minutes: float = 10, tail: int = 200) -> str:
    """捞日志:读取模拟服务容器最近日志(只读 docker logs),返回命中行与状态码分布。

    何时调用:需要"错误率↑"的文字证据时——如捞 503 行佐证连接池耗尽;
    keyword 常用 "503"、"500" 或具体路径。
    入参:service——必填,ykt 或 jiaowu;keyword——行内子串过滤,缺省不过滤;
    minutes——回看分钟数(默认 10);tail——最多读取的最近行数(默认 200)。
    返回字段:container、command_used(只读命令原文,可追出处)、total_scanned、
    matched_count、matched_lines(≤80 行,每行≤300 字符)、status_code_counts(如 {"503": 12})、
    note("503" 常见来源)。
    环境约束:依赖**宿主机** docker CLI(P3b 部署形态为宿主机 venv,weekly 容器内实测
    NO_DOCKER_CLI 且无 docker.sock);docker 不可用时报错说明,不返回空列表冒充"无异常"。
    """
    if service not in CONTAINER_MAP:
        return _err(f"service 必须是 {sorted(CONTAINER_MAP)} 之一,收到 {service!r}")
    try:
        total, stdout, stderr = _docker_logs(service, minutes, tail)
    except FileNotFoundError:
        return _err("宿主机未找到 docker CLI——query_logs 依赖它读取容器日志(只读);"
                    "请确认 Docker Desktop 已启动且 docker 在 PATH")
    except (AiopsGuardError, subprocess.TimeoutExpired, RuntimeError) as e:
        return _err(f"query_logs 失败: {e}")
    all_lines = (stdout + stderr).splitlines()
    matched = [ln for ln in all_lines if keyword in ln] if keyword else list(all_lines)
    codes: dict[str, int] = {}
    for ln in all_lines:
        m = _STATUS_RE.search(ln)
        if m:
            codes[m.group(1)] = codes.get(m.group(1), 0) + 1
    shown = [ln[:300] for ln in matched[:MAX_LOG_LINES]]
    note = ""
    if codes.get("503"):
        note = "503 来自 FastAPI HTTPException(db pool busy)——连接池等待超时即抛出,佐证池耗尽"
    return _ok(
        service=service, container=CONTAINER_MAP[service],
        command_used=f"docker logs --since {max(1, int(minutes))}m --tail {max(1, int(tail))} "
                     f"{CONTAINER_MAP[service]}(只读)",
        minutes=minutes, keyword=keyword, total_scanned=total,
        matched_count=len(matched), matched_lines=shown,
        status_code_counts=codes, note=note,
        source="宿主机 docker logs(容器 stdout/stderr 只读)",
    )


@mcp.tool()
def query_changes(service: str = "", minutes: float = 60) -> str:
    """查变更:窗口内的进程重启、故障注入窗口、注入触发次数——每条带 promql 出处。

    何时调用:异常时间点附近问"最近动过什么";把 503 抬升归因到注入演练或真实故障。
    入参:service——ykt/jiaowu,缺省全部;minutes——回看窗口(默认 60)。
    返回字段:window、changes[{kind(container_restart/fault_injection_window/
    fault_injection_trigger), job, type?, at/description, source(promql+取值)}]、
    limitation(fault_active 序列在容器重启后、首次注入前不存在)。
    出处指标:process_start_time_seconds(重启)、max_over_time(fault_active[w])(注入窗口)、
    increase(http_requests_total{path="/debug/fault/{mode}"}[w])(触发次数,path 模板不区分
    具体模式,mode 归属以 fault_active{type} 窗口为准)。
    """
    try:
        job = _job_filter(service)
        w = f"{max(1, int(minutes))}m"
        now = time.time()
        changes: list[dict] = []
        data = _prom_get("/api/v1/query", {
            "query": f"process_start_time_seconds{{job=~\"{job}\"}}"})
        for r in data.get("result", []):
            j = r["metric"].get("job", "?")
            start = float(r["value"][1])
            uptime = now - start
            changes.append({
                "kind": "process_start_time", "job": j,
                "started_at": _fmt_ts(start), "uptime_seconds": round(uptime),
                "recent_restart": uptime <= minutes * 60,
                "source": f"process_start_time_seconds{{job=\"{j}\"}}={start:.0f}",
            })
        data = _prom_get("/api/v1/query", {
            "query": f"max_over_time(fault_active{{job=~\"{job}\"}}[{w}])"})
        for r in data.get("result", []):
            m, val = r["metric"], float(r["value"][1])
            if val > 0:
                changes.append({
                    "kind": "fault_injection_window", "job": m.get("job"),
                    "type": m.get("type"),
                    "description": f"窗口 {w} 内 fault_active[{m.get('type')}] 曾为 1(注入/演练现场)",
                    "source": f"max_over_time(fault_active{{job=\"{m.get('job')}\",type=\"{m.get('type')}\"}}[{w}])=1",
                })
        data = _prom_get("/api/v1/query", {
            "query": f"sum by(job) (increase(http_requests_total{{path=\"/debug/fault/{{mode}}\",job=~\"{job}\"}}[{w}]))"})
        for r in data.get("result", []):
            val = float(r["value"][1])
            if val > 0:
                changes.append({
                    "kind": "fault_injection_trigger", "job": r["metric"].get("job"),
                    "count": int(val),
                    "description": f"窗口 {w} 内 /debug/fault/{{mode}} 被调用 {int(val)} 次",
                    "source": f"increase(http_requests_total{{path=\"/debug/fault/{{mode}}\"}}[{w}])={_fmt_val(val)}",
                })
        return _ok(
            window=w, changes=changes,
            limitation="容器重启后到首次注入前 fault_active 时间序列不存在——该窗口内"
                       "查不到注入记录不代表没有注入,需结合 query_logs 与演练计划判断",
            source="prometheus /api/v1/query(process_start_time_seconds / fault_active / http_requests_total)",
        )
    except (AiopsGuardError, urllib.error.URLError, TimeoutError, ValueError) as e:
        return _err(f"query_changes 失败: {e}")


# ---------- run_playbook:只读预案(playbooks.yml);红线:不执行任何写操作 ----------

_AIOPS_DIR = os.path.dirname(os.path.abspath(__file__))
_PLAYBOOKS_PATH = os.path.join(_AIOPS_DIR, "playbooks.yml")


def _mini_yaml(text: str) -> Any:
    """playbooks.yml 专用迷你解析器(严格子集:2 空格缩进/块映射/块列表/单行标量/
    {inline dict}/[inline list]),供无 pyyaml 环境回退;优先使用 pyyaml。"""
    lines = [ln.rstrip() for ln in text.splitlines()
             if ln.strip() and not ln.strip().startswith("#")]

    def scalar(s: str) -> Any:
        s = s.strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
            inner = s[1:-1]
            if s[0] == '"':
                inner = inner.replace('\\"', '"').replace("\\\\", "\\")
            return inner
        if s.startswith("[") and s.endswith("]"):
            return [scalar(x) for x in split_top(s[1:-1]) if x.strip()]
        if s.startswith("{") and s.endswith("}"):
            d = {}
            for part in split_top(s[1:-1]):
                if ":" in part:
                    k, v = part.split(":", 1)
                    d[k.strip()] = scalar(v)
            return d
        if s in ("true", "false"):
            return s == "true"
        for cast in (int, float):
            try:
                return cast(s)
            except ValueError:
                pass
        return s

    def split_top(s: str) -> list[str]:
        out, depth, cur = [], 0, ""
        for ch in s:
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
            if ch == "," and depth == 0:
                out.append(cur)
                cur = ""
            else:
                cur += ch
        if cur.strip():
            out.append(cur)
        return out

    def block(i: int, indent: int) -> tuple[Any, int]:
        if i >= len(lines):
            return None, i
        first = lines[i]
        ind = len(first) - len(first.lstrip())
        if ind < indent:
            return None, i
        if first.lstrip().startswith("- "):
            lst: list[Any] = []
            while i < len(lines):
                line = lines[i]
                ind = len(line) - len(line.lstrip())
                if ind != indent or not line.lstrip().startswith("- "):
                    break
                item = line.lstrip()[2:].strip()
                i += 1
                if item.startswith(("{", "[", '"', "'")):
                    lst.append(scalar(item))
                elif ":" in item:
                    k, v = item.split(":", 1)
                    d: dict = {}
                    if v.strip():
                        d[k.strip()] = scalar(v)
                    else:
                        sub, i = block(i, indent + 2)
                        d[k.strip()] = sub
                    while i < len(lines):
                        l2 = lines[i]
                        ind2 = len(l2) - len(l2.lstrip())
                        if ind2 == indent + 2 and not l2.lstrip().startswith("- "):
                            k2, v2 = l2.lstrip().split(":", 1)
                            i += 1
                            if v2.strip():
                                d[k2.strip()] = scalar(v2)
                            else:
                                sub, i = block(i, ind2 + 2)
                                d[k2.strip()] = sub
                        else:
                            break
                    lst.append(d)
                else:
                    lst.append(scalar(item))
            return lst, i
        d = {}
        while i < len(lines):
            line = lines[i]
            ind = len(line) - len(line.lstrip())
            if ind != indent or line.lstrip().startswith("- "):
                break
            k, v = line.strip().split(":", 1)
            if v.strip():
                d[k.strip()] = scalar(v)
                i += 1
            else:
                sub, i = block(i + 1, indent + 2)
                d[k.strip()] = sub if sub is not None else {}
        return d, i

    obj, _ = block(0, 0)
    return obj or {}


def _load_playbooks() -> dict:
    with open(_PLAYBOOKS_PATH, encoding="utf-8") as f:
        text = f.read()
    try:
        import yaml  # 可选依赖:有则用完整解析
        data = yaml.safe_load(text)
    except ImportError:
        data = _mini_yaml(text)
    return (data or {}).get("playbooks", {}) if isinstance(data, dict) else {}


_PLAYBOOK_TOOLS = {"get_service_status", "query_metrics", "query_logs",
                   "query_changes", "list_alerts"}


@mcp.tool()
def run_playbook(name: str, service: str = "", dry_run: bool = False) -> str:
    """跑只读取证预案:按 playbooks.yml 的步骤串起取证工具,产出带出处的根因候选。

    何时调用:告警已定性(如 SimsDbPoolSaturated firing)后,按预案走完整取证链,
    或用户点名"按预案排查"。**红线:本工具只执行只读取证,不执行 restart/rm/exec
    等任何写操作;mitigation 仅是建议命令,需人工执行。**
    入参:name——playbook 名(pool_exhaust / cpu_spike / service_down);service——
    目标服务(ykt/jiaowu,缺省用 playbook 的 applies_to);dry_run——true 仅返回步骤清单。
    返回字段:playbook、service、dry_run、signals[{expr, desc, result(现场查询值)}]、
    steps[{tool, args, why, result}]、root_cause_hints、mitigation{text, note="需人工执行"}。
    """
    playbooks = _load_playbooks()
    pb = playbooks.get(name)
    if not pb:
        return _err(f"未找到 playbook {name!r},可用: {sorted(playbooks)}")
    svc = service or (pb.get("applies_to") or ["ykt"])[0]
    signals = pb.get("signals") or []
    steps = pb.get("steps") or []
    base = {
        "playbook": name, "service": svc, "dry_run": bool(dry_run),
        "title": pb.get("title"),
        "root_cause_hints": pb.get("root_cause_hints") or [],
        "mitigation": {"text": pb.get("mitigation", ""),
                       "note": "仅建议命令,需人工执行;run_playbook 不执行任何写操作"},
        "source": f"mcp/aiops/playbooks.yml#{name}",
    }
    if dry_run:
        return _ok(**base, signals=signals, steps=steps, note="dry_run=true,未执行任何步骤")

    def _exec(tool: str, args: dict) -> dict:
        if tool not in _PLAYBOOK_TOOLS:
            return {"ok": False, "error": f"预案只允许只读工具 {sorted(_PLAYBOOK_TOOLS)},收到 {tool}"}
        fn = {"get_service_status": get_service_status, "query_metrics": query_metrics,
              "query_logs": query_logs, "query_changes": query_changes,
              "list_alerts": list_alerts}[tool]
        return json.loads(fn(**args))

    try:
        signal_results = []
        for s in signals:
            expr = s.get("expr", "")
            r = json.loads(query_metrics(expr)) if expr else {"ok": False, "error": "空 expr"}
            vals = []
            for item in r.get("results", []) if r.get("ok") else []:
                for vv in item.get("values", []):
                    vals.append({"job": item["metric"].get("job"), "value": vv["value"]})
            signal_results.append({"expr": expr, "desc": s.get("desc", ""),
                                   "fired": bool(vals), "samples": vals[:5],
                                   "error": r.get("error") if not r.get("ok") else None})
        step_results = []
        for st in steps:
            args = dict(st.get("args") or {})
            if svc and "service" in args and not args["service"]:
                args["service"] = svc
            r = _exec(st.get("tool", ""), args)
            step_results.append({"tool": st.get("tool"), "args": args, "why": st.get("why", ""),
                                 "ok": r.get("ok", False), "result": r})
        return _ok(**base, signals=signal_results, steps=step_results)
    except (AiopsGuardError, urllib.error.URLError, TimeoutError, ValueError) as e:
        return _err(f"run_playbook {name} 失败: {e}")


@mcp.tool()
def gather_diagnosis(service: str, minutes: float = 15) -> str:
    """一键诊断取证:串起 status→alerts→metrics→logs→changes,返回带证据链的结构化素材。

    何时调用:P3c ReAct 的快捷入口——用户描述"一卡通慢/报错"时,先用它一次性拿全
    诊断素材再深入;每条素材都能回溯到"哪个工具的哪个字段"。
    入参:service——必填(ykt/jiaowu);minutes——日志与变更窗口(默认 15 分钟)。
    返回字段:status(get_service_status 的 services)、alerts(list_alerts firing)、
    key_metrics{pool_utilization_pct, http_5xx_rate_per_s, process_cpu_percent},
    logs_summary{status_code_counts, error_lines(≤10), command_used},
    changes(query_changes)、evidence_chain[{field, tool, value}](字段级出处)、
    generated_at(+0800)。
    """
    if service not in CONTAINER_MAP:
        return _err(f"service 必须是 {sorted(CONTAINER_MAP)} 之一,收到 {service!r}")
    chain: list[dict] = []
    try:
        status = json.loads(get_service_status(service))
        svc_info = next((s for s in status.get("services", []) if s["job"] == service), None)
        if svc_info:
            chain.append({"field": f"status.{service}.pool_utilization_pct",
                          "tool": "get_service_status",
                          "value": svc_info.get("pool_utilization_pct")})
            chain.append({"field": f"status.{service}.up", "tool": "get_service_status",
                          "value": svc_info.get("up")})
        alerts = json.loads(list_alerts("firing"))
        key_metrics: dict[str, Any] = {}
        r = json.loads(query_metrics(
            f"app_db_pool_in_use{{job=\"{service}\"}} / app_db_pool_size{{job=\"{service}\"}}"))
        if r.get("ok") and r["results"]:
            key_metrics["pool_utilization_pct"] = round(float(r["results"][0]["values"][0]["value"]) * 100, 1)
            chain.append({"field": "key_metrics.pool_utilization_pct", "tool": "query_metrics",
                          "value": key_metrics["pool_utilization_pct"],
                          "promql": r["promql"]})
        r = json.loads(query_metrics(
            f"sum(rate(http_requests_total{{job=\"{service}\",status=~\"5..\"}}[30s]))"))
        if r.get("ok") and r["results"]:
            key_metrics["http_5xx_rate_per_s"] = float(r["results"][0]["values"][0]["value"])
            chain.append({"field": "key_metrics.http_5xx_rate_per_s", "tool": "query_metrics",
                          "value": key_metrics["http_5xx_rate_per_s"], "promql": r["promql"]})
        r = json.loads(query_metrics(f"process_cpu_percent{{job=\"{service}\"}}"))
        if r.get("ok") and r["results"]:
            key_metrics["process_cpu_percent"] = float(r["results"][0]["values"][0]["value"])
            chain.append({"field": "key_metrics.process_cpu_percent", "tool": "query_metrics",
                          "value": key_metrics["process_cpu_percent"], "promql": r["promql"]})
        logs = json.loads(query_logs(service, "", minutes=minutes, tail=150))
        logs_summary: dict[str, Any] = {"status_code_counts": logs.get("status_code_counts", {}),
                                        "command_used": logs.get("command_used")}
        err_lines = [ln for ln in logs.get("matched_lines", [])
                     if " 503 " in ln or " 500 " in ln or "ERROR" in ln][:10]
        logs_summary["error_lines"] = err_lines
        if err_lines:
            chain.append({"field": "logs_summary.error_lines", "tool": "query_logs",
                          "value": f"{len(err_lines)} 行错误样例(503/500/ERROR)"})
        changes = json.loads(query_changes(service, minutes=minutes))
        chain.append({"field": "changes", "tool": "query_changes",
                      "value": f"{len(changes.get('changes', []))} 条变更记录"})
        return _ok(
            service=service, minutes=minutes, generated_at=_fmt_ts(time.time()),
            status=svc_info, alerts=alerts.get("alerts", []),
            rules_count=alerts.get("rules_count"), key_metrics=key_metrics,
            logs_summary=logs_summary, changes=changes.get("changes", []),
            evidence_chain=chain,
            source="gather_diagnosis=get_service_status+list_alerts+query_metrics+query_logs+query_changes",
        )
    except (AiopsGuardError, urllib.error.URLError, TimeoutError, ValueError, KeyError) as e:
        return _err(f"gather_diagnosis 失败: {e}")


if __name__ == "__main__":
    # 双传输并存:SSE(/sse)+ Streamable HTTP(/mcp)——与 mcp/weekly 同构
    from contextlib import asynccontextmanager

    import uvicorn
    from starlette.applications import Starlette

    # 默认只监听回环地址:本服务无鉴权层,且 query_logs 会返回容器日志原文,
    # 默认对外全网卡监听等于把日志内容暴露到局域网。确需跨机访问时由部署方
    # 显式设 AIOPS_HOST=0.0.0.0,并自行在前置层加认证。
    host = os.environ.get("AIOPS_HOST", "127.0.0.1")
    port = int(os.environ.get("AIOPS_PORT", "18081"))

    sse_asgi = mcp.sse_app(sse_path="/sse", message_path="/messages/", host=host)
    http_asgi = mcp.streamable_http_app(streamable_http_path="/mcp", host=host)

    @asynccontextmanager
    async def lifespan(_app):
        # streamable_http_app 的 lifespan 负责 StreamableHTTPSessionManager 启动,
        # 必须带着跑,否则 /mcp 请求会报 task group 未初始化(weekly 同款)
        async with http_asgi.router.lifespan_context(http_asgi):
            async with sse_asgi.router.lifespan_context(sse_asgi):
                yield

    app = Starlette(routes=[*http_asgi.routes, *sse_asgi.routes], lifespan=lifespan)
    uvicorn.run(app, host=host, port=port)
