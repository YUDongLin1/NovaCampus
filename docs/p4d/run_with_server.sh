#!/usr/bin/env bash
# P4d-fix 便捷脚本:在同一 shell 生命周期内起服务 → 跑指定命令 → 杀服务。
# 起因:Git Bash 无 setsid,`nohup &` 起的 uvicorn 会随本条命令结束被回收,
# 导致下一条命令连不上端口(实测 8902 连续两次 DOWN)。故把生命周期收进同一条命令。
#
# 用法: bash docs/p4d/run_with_server.sh <port> <python-s relative-to-novaagent> [args...]
#   例: bash docs/p4d/run_with_server.sh 8902 ../evals/run_evals.py --base http://127.0.0.1:8902
#   ⚠ run_evals.py / smoke_test.py **必须**带 --base(见下方自检):它们有模块级默认
#     BASE=http://127.0.0.1:8900,漏掉就会连到别人的常驻实例(坑 57,本项目已白跑 6 轮)。
#   退出码:0=脚本成功**且**端口已关闭;2=服务未就绪;3=缺 --base;4=端口没关掉(孤儿实例)。
set -uo pipefail
PORT="$1"; shift
REL="$1"; shift
ROOT="E:/AILearn/NovaCampus"
export NO_PROXY="127.0.0.1,localhost"
export NOVAAGENT_EVAL_TEMPERATURE=0

# P4e M5 ①:自检 —— 评测脚本必须显式 --base,否则会回落到模块级默认 :8900。
#
# 【为什么必须自检】run_evals.py 有模块级 `BASE = "http://127.0.0.1:8900"`,而本脚本
# 起的服务在 $PORT。两者不一致时,评测**全程连的是 :8900** —— 极可能是**他人的常驻
# 旧实例**(实测过一次:15:40 启动的进程,加载的是 FUSION_TOP_K 改动前的 8 槽代码),
# 于是"代码改了但评测没生效",表现为 `qa-12` 之类的**假红**,极易被误判成修法失败
# 去改用例(违反坑 39/52)。本单就因此白跑 6 轮整轮评测。
#
# 判据:被跑的脚本是 run_evals.py(或 smoke_test.py,见下)却没有 --base → 直接退出。
# 二者历史上都有模块级默认 BASE 的问题,故一并检查。
if [[ "$REL" == *run_evals.py* || "$REL" == *smoke_test.py* ]]; then
  if [[ "$*" != *--base* ]]; then
    echo "[FATAL] $REL 未指定 --base。" >&2
    echo "        服务起在 $PORT,而脚本会回落到模块级默认 http://127.0.0.1:8900 ——" >&2
    echo "        极可能是他人的常驻旧实例,会造出「代码改了但评测没生效」的假红(坑 39/52)。" >&2
    echo "        正确用法: bash $0 $PORT $REL --base http://127.0.0.1:$PORT" >&2
    exit 3
  fi
fi

cd "$ROOT/novaagent"
.venv/Scripts/python.exe -m uvicorn novaagent.main:app --port "$PORT" --host 127.0.0.1 > /tmp/nova"$PORT".log 2>&1 &
SRV=$!

# ---------- P4f C0-⑤: 收尾必须**按端口复查**,不能只看"命令退出码 0" ----------
# 【原缺陷】旧实现是 `trap 'kill $SRV' EXIT`。Git Bash 的 `kill` 用的是 **MSYS PID
#   命名空间**,而 $! 拿到的是 Windows 侧 uvicorn 的 PID(坑 61:实测 kill 返回成功、
#   端口仍在听)。复核方本轮实测到脚本打印 `[server] done rc=0, shutting down 8936`
#   之后 :8936 **仍在监听**;历史上还因此留下过 :8906/:8907、:8923 三个孤儿实例,
#   两次都是靠**实现方复查端口**才发现的。
# 【为什么必须复查而不是信退出码】
#   "kill 命令返回 0" 与 "进程真的死了" 是两件事(坑 37:health=200 也不证明是谁起的)。
#   孤儿实例的代价是真实的:下一个复跑的人会连上别人的旧进程,拿到一个
#   **代码版本不对**的服务 → 造出"代码改了但评测没生效"的假红(坑 57)。
#   所以收尾必须**以端口是否关闭为准**,并在没关掉时以非 0 退出——让调用方看见。
#
# 终止方式按优先级三段(2026-09-03 真机验证后重排,见下方「实测记录」):
#   ① `taskkill //PID <端口上的 Windows PID> //F` —— 最权威。
#      ⚠ **不能用 `$SRV`**:`$!` 是 **MSYS PID 命名空间**里的编号,Windows 的 taskkill
#        拿着它找不到进程(实测 taskkill 静默失败,脚本一路退化到 shell kill)。
#        端口上那个 PID 才是 Windows PID —— 而端口才是事实(坑 57 同源:
#        "命令返回 0" 与 "进程真死了" 是两件事,坑 37)。
#   ② `taskkill //PID $SRV //F` —— 兜底,万一 netstat 拿不到。
#   ③ shell 内建 `kill $SRV` —— 最后手段(仅保证 MSYS 侧父子关系被拆掉)。
#
# 【实测记录(2026-09-03,:8941)】第一版只用 ②③,结果:
#   [server] taskkill 静默失败 → [server] shell kill issued → 端口确实关了,
#   但**主流程在进程尚未被终止时就查了端口**,恒判 `closed=False` → `exit 4`,
#   随后 trap 才真正终止并打印 `closed=True`。退出码与事实**相反**,比不报错更坏。
#   故必须:① 用 Windows PID;② 先终止、等端口关,再据端口状态定退出码。
port_closed() {
  # 端口无监听者 → 0(closed)。Git Bash 下用 curl 探一次最省事、不依赖额外工具。
  ! curl -s -m 2 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1
}

# 该端口当前监听者的 **Windows PID**(取不到则空)。LISTENING 行才有 PID。
port_win_pid() {
  netstat -ano 2>/dev/null \
    | grep -E "127\.0\.0\.1:$PORT[[:space:]]+0\.0\.0\.0:0[[:space:]]+LISTENING" \
    | awk '{print $NF}' | head -1
}

terminate_server() {
  local wpid
  wpid="$(port_win_pid)"
  if [ -n "$wpid" ]; then
    echo "[server] taskkill //PID $wpid //F (端口 $PORT 上的 Windows PID)"
    taskkill //PID "$wpid" //F >/dev/null 2>&1 \
      && echo "[server] taskkill issued" \
      || echo "[server] taskkill failed(rc=$?)"
  else
    echo "[server] 端口 $PORT 上没查到 LISTENING PID,退到 SRV=$SRV"
    taskkill //PID "$SRV" //F >/dev/null 2>&1 \
      && echo "[server] taskkill(SRV) issued" || true
  fi
  # 兜底:taskkill 都不可用时用 shell 内建 kill 拆掉 MSYS 父子关系
  if ! port_closed; then
    kill "$SRV" 2>/dev/null && echo "[server] shell kill issued" \
      || echo "[server] shell kill failed(rc=$?)"
  fi
  # 轮询等待端口真正关闭(进程被杀到 socket 释放通常 <2s,留 10s 余量)
  local n=0
  while [ "$n" -lt 5 ]; do
    if port_closed; then return 0; fi
    n=$((n + 1))
    sleep 2
  done
  return 1
}

CLEANED=0
cleanup() {
  # 幂等:主流程已经收尾过就别再跑一遍(否则打印两套 [port-check],读的人会懵)
  [ "$CLEANED" = "1" ] && return 0
  CLEANED=1
  terminate_server
  if port_closed; then
    echo "[port-check] :$PORT closed=True"
  else
    # ⚠ 仍有人监听:可能 PID 没杀掉,或端口被**别的**进程占着(两种都要让人看见)
    echo "[port-check] :$PORT closed=False  <-- 端口仍在监听,可能有孤儿实例" >&2
    netstat -ano 2>/dev/null | grep -E "127\.0\.0\.1:$PORT[[:space:]]" >&2 || true
  fi
}

# 用 EXIT trap 而不是直接调用:异常退出(命令 not found、Ctrl-C)时同样要收尾,
# 否则又留孤儿(C0-⑤ 要修的就是这一类"没走到收尾"的路径)。
trap 'cleanup' EXIT

READY=0
for i in $(seq 1 40); do
  sleep 3
  if curl -s -m 3 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then READY=1; break; fi
done
if [ "$READY" != "1" ]; then
  echo "[FATAL] 服务未就绪,日志尾部:"; tail -20 "/tmp/nova$PORT.log"; exit 2
fi
echo "[server] ready on $PORT (pid=$SRV), running: $REL $*"
.venv/Scripts/python.exe "$REL" "$@"
RC=$?
echo "[server] done rc=$RC, shutting down $PORT"
# 收尾 + 端口复查**在主流程里做**,不是只靠 EXIT trap。
# ⚠ 第一版把端口判定写在 `exit $RC` 前、终止动作只发生在 trap 里 ——
#   于是判定那一刻进程还活着、端口必然在听 → **恒 exit 4**;
#   紧接着 trap 才真正杀掉并打印 closed=True。退出码与事实相反(2026-09-03 :8941 实测)。
#   端口没关掉 → 退出码非 0(哪怕被跑的脚本本身 rc=0):
#   「实例没关掉」本身就是本脚本的失败,不能让调用方以为一切正常
#   (坑 55 的精神:退出码必须反映真实状态,不能只反映被调脚本的状态)。
cleanup
if ! port_closed; then
  exit 4
fi
exit $RC
