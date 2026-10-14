#!/bin/bash
# frset_perf_measure.command — 在沙箱外测量 Stats.app 与 Frset.app 的运行开销
# 由 WorkBuddy 生成；只读测量，测完自动把两个 App 退回「未运行」状态。
OUT="/Users/sunyiyang/Desktop/Project/frset/rea-evidence/perf-measurement-$(date +%Y%m%d-%H%M).txt"
exec > >(tee "$OUT") 2>&1

echo "================================================================"
echo " Frset / Stats 性能开销测量  $(date)"
echo " 结果同时保存到: $OUT"
echo "================================================================"
echo
echo "[机器信息] $(sysctl -n machdep.cpu.brand_string 2>/dev/null || sysctl -n hw.model) | $(sysctl -n hw.ncpu) 逻辑核"
echo "[基线负载] $(uptime)"
echo "[基线内存] $(memory_pressure | tail -1)"
echo "[基线 Top CPU 进程]"
ps -Axo pid,%cpu,%mem,comm -r | head -9
echo

measure_app () {
  local apppath="$1" procname="$2" label="$3" warmup="$4" samples="$5"
  echo "################## $label ##################"
  open "$apppath"
  echo "→ 已启动，等待 ${warmup}s 稳定 … $(date +%H:%M:%S)"
  sleep "$warmup"
  local pid
  pid=$(pgrep -x "$procname" | head -1 || true)
  if [ -z "$pid" ]; then echo "!! 未找到进程 $procname，跳过"; return; fi
  echo "→ PID=$pid 开始采样（top 帧 + ps 序列）"
  echo "--- top 采样（含 POWER 能耗列，单位近似 Activity Monitor 能耗值）---"
  top -l "$samples" -s 2 -stats pid,cpu,power,mem,command 2>/dev/null \
    | grep -E "^ *$pid " | sed 's/^/   top| /'
  echo "--- ps 序列采样（%CPU / %MEM / RSS-KB，每 2s 一次）---"
  for i in $(seq 1 8); do
    ps -p "$pid" -o %cpu=,%mem=,rss= 2>/dev/null | while read -r a b c; do
      echo "   ps | $(date +%H:%M:%S) | cpu=$a% mem=$b% rss=$((c/1024))MB"
    done
    sleep 2
  done
  echo "--- 相关子进程 ---"
  ps -Axo pid,%cpu,%mem,rss,comm | grep -iE "$procname|Helper" | grep -viE "grep" | sed 's/^/   /'
  echo "[采样后负载] $(uptime)"
  echo "→ 退出 $label …"
  osascript -e "tell application \"$procname\" to quit" >/dev/null 2>&1 || true
  sleep 4
  if pgrep -x "$procname" >/dev/null 2>&1; then pkill -x "$procname"; echo "   (强制退出)"; else echo "   已正常退出"; fi
  sleep 3
  echo
}

measure_app "/Applications/Stats.app" "Stats" "① Stats.app（全模块：CPU/RAM/Disk/Net/Battery/GPU/Sensors）" 45 6
measure_app "/Applications/Frset.app" "Frset" "② Frset.app（现状：CPU/内存/磁盘灯/网速/系统状态）" 45 6

echo "================================================================"
echo " 测量完成 $(date)  结果已保存到:"
echo " $OUT"
echo " 此窗口可关闭。"
echo "================================================================"
