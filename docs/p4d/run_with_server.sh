#!/usr/bin/env bash
# P4d-fix 便捷脚本:在同一 shell 生命周期内起服务 → 跑指定命令 → 杀服务。
# 起因:Git Bash 无 setsid,`nohup &` 起的 uvicorn 会随本条命令结束被回收,
# 导致下一条命令连不上端口(实测 8902 连续两次 DOWN)。故把生命周期收进同一条命令。
#
# 用法: bash docs/p4d/run_with_server.sh <port> <python-s relative-to-novaagent> [args...]
#   例: bash docs/p4d/run_with_server.sh 8902 ../evals/run_evals.py
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
trap 'kill $SRV 2>/dev/null' EXIT
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
exit $RC
