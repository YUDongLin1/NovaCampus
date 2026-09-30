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
