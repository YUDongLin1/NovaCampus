#!/usr/bin/env bash
# P4e S1-①:延迟对照(修正 N=0 语义后重跑)。
#   early80 = 早窗 80 字(默认档)   early60 = 早窗 60 字(N 取值对照)
#   full    = N=0 全量缓冲(M4 旧行为,回滚对照)
#   off     = 闸门整体关闭(P4e M4 之前,无闸门)
set -uo pipefail
cd E:/AILearn/NovaCampus

run_mode () {
  local mode="$1" port="$2" envset="$3"
  echo "########## MODE=${mode} (${envset}) port=${port} ##########"
  env ${envset} bash docs/p4d/run_with_server.sh "${port}" \
      ../docs/p4e/probe_stream_latency.py --base "http://127.0.0.1:${port}" \
      --mode "${mode}" --runs 3
  echo "[mode ${mode} rc=$?]"
}

run_mode full    8917 "NOVA_GROUNDING_EARLY_WINDOW_CHARS=0"
run_mode early80 8918 "NOVA_GROUNDING_EARLY_WINDOW_CHARS=80"
run_mode early60 8919 "NOVA_GROUNDING_EARLY_WINDOW_CHARS=60"
run_mode off     8920 "NOVA_GROUNDING_GATE=0"
echo "=== ALL DONE ==="
