#!/usr/bin/env bash
# P4e S2-①: 渐进性阈值定标——早窗档与全缓冲档各连测 6 次,取**逐次 span** 分布。
# 目的: 把 STREAM_MIN_SPAN_MS 落在两侧分布之外(旧值 300 压在真流式分布里面)。
set -uo pipefail
cd E:/AILearn/NovaCampus

run_mode () {
  local mode="$1" port="$2" envset="$3"
  echo "########## MODE=${mode} (${envset}) port=${port} ##########"
  env ${envset} bash docs/p4d/run_with_server.sh "${port}" \
      ../docs/p4e/probe_stream_latency.py --base "http://127.0.0.1:${port}" \
      --mode "${mode}" --runs 6
  echo "[mode ${mode} rc=$?]"
}

run_mode span_early80 8940 "NOVA_GROUNDING_EARLY_WINDOW_CHARS=80"
run_mode span_full    8941 "NOVA_GROUNDING_EARLY_WINDOW_CHARS=0"
echo "=== ALL DONE ==="
