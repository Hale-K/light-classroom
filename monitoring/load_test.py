"""轻课堂 API 压测脚本:多接口混合、并发 worker、持续指定时长。

用法: python load_test.py [时长秒] [并发数]
结束后输出状态码分布与延迟分位。
"""
import json
import random
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from collections import Counter

DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 45
WORKERS = int(sys.argv[2]) if len(sys.argv) > 2 else 24
BASE = "http://127.0.0.1:8001"

# 模拟真实使用:高频轻接口 + 低频重接口按权重混合
ENDPOINTS = [
    ("/health", 4),
    ("/api/v1/org/grades", 6),
    ("/api/v1/org/classes", 6),
    ("/api/v1/organization/tree", 3),
    ("/api/v1/staff", 3),
    ("/api/v1/auth/menus", 4),
    ("/api/v1/scheduling/resources", 2),
    ("/api/v1/org/students", 2),
]
POOL = [ep for ep, w in ENDPOINTS for _ in range(w)]

status_counter = Counter()
latencies = []
total = 0


def worker(stop_at: float, worker_id: int) -> tuple[int, list[float], Counter]:
    n = 0
    lats = []
    codes = Counter()
    rng = random.Random(worker_id)
    while time.time() < stop_at:
        path = rng.choice(POOL)
        t0 = time.perf_counter()
        try:
            req = urllib.request.Request(BASE + path, headers={"User-Agent": "load-test"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp.read()
                codes[resp.status] += 1
        except urllib.error.HTTPError as e:
            codes[e.code] += 1
        except Exception as e:
            codes[f"ERR:{type(e).__name__}"] += 1
        lats.append(time.perf_counter() - t0)
        n += 1
    return n, lats, codes


def main():
    stop_at = time.time() + DURATION
    print(f"压测开始: {DURATION}s, {WORKERS} 并发, {len(POOL)} 接口池(加权)")
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(lambda i: worker(stop_at, i), range(WORKERS)))
    total = sum(r[0] for r in results)
    lats = sorted(lat for r in results for lat in r[1])
    codes = Counter()
    for r in results:
        codes.update(r[2])

    def pct(p):
        return lats[min(int(len(lats) * p), len(lats) - 1)] * 1000 if lats else 0

    print(f"\n===== 结果 =====")
    print(f"总请求:  {total}")
    print(f"平均QPS: {total / DURATION:.1f}")
    print(f"P50: {pct(0.50):.0f}ms  P95: {pct(0.95):.0f}ms  P99: {pct(0.99):.0f}ms  MAX: {lats[-1]*1000:.0f}ms" if lats else "无数据")
    print(f"状态码:  {dict(codes)}")


if __name__ == "__main__":
    main()
