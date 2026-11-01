#!/bin/bash
# usage: run_one.sh NAME  (runs 3 plain harness-style runs, 1 cProfile, 1 sampled)
set -u
S="${E0_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
PY=/usr/bin/python3.11
n=$1; wt=$S/amdahl/$n; out=$S/amdahl_out/$n; mkdir -p $out/home $out/tmp
pp=$wt; [ -d $wt/src ] && pp=$wt:$wt/src
for i in 1 2 3; do
  t0=$(date +%s.%N)
  (cd $wt && env -i PATH=/usr/bin:/bin HOME=$out/home TMPDIR=$out/tmp PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$pp $PY benchmarks/bench_$n.py) > $out/plain$i.txt 2>&1
  rc=$?; t1=$(date +%s.%N)
  echo "$n plain$i rc=$rc wall=$(echo "$t1 - $t0" | bc)" | tee -a $out/times.txt
done
cd $S/amdahl_scripts
t0=$(date +%s.%N); env -i PATH=/usr/bin:/bin HOME=$out/home TMPDIR=$out/tmp PYTHONDONTWRITEBYTECODE=1 $PY -I -B driver.py cprofile $wt $n $out/prof.json > $out/cprof.txt 2>&1; rc=$?; t1=$(date +%s.%N)
echo "$n cprofile rc=$rc wall=$(echo "$t1 - $t0" | bc)" | tee -a $out/times.txt
t0=$(date +%s.%N); env -i PATH=/usr/bin:/bin HOME=$out/home TMPDIR=$out/tmp PYTHONDONTWRITEBYTECODE=1 $PY -I -B driver.py sample $wt $n $out/sample.json > $out/sample.txt 2>&1; rc=$?; t1=$(date +%s.%N)
echo "$n sample rc=$rc wall=$(echo "$t1 - $t0" | bc)" | tee -a $out/times.txt
