#!/usr/bin/env python3
"""
Synthetic monitor — simulates real user journeys to validate SLOs externally.
Weedmaps explicitly calls this out in their JD: "Create and refine synthetic monitoring flows."

Key distinction from passive monitoring:
  Passive = wait for real users to trigger errors
  Synthetic = proactively run scripted journeys every N seconds from outside

Usage:
  python scripts/synthetic_monitor.py
  python scripts/synthetic_monitor.py --url http://localhost:8080 --interval 15
"""
import argparse
import time
import sys
import json
import urllib.request
from datetime import datetime

CHECKS = [
    {"path": "/health",        "expected": 200, "name": "health-check"},
    {"path": "/api/products",  "expected": 200, "name": "list-products"},
    {"path": "/api/products/1","expected": 200, "name": "get-product"},
    {"path": "/api/orders",    "expected": 200, "name": "list-orders"},
]

results_window = []   # rolling window for uptime %


def check(base_url: str, path: str, expected: int) -> tuple[bool, float, int]:
    url = f"{base_url}{path}"
    start = time.perf_counter()
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as r:
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
    except Exception:
        status = 0
    latency = time.perf_counter() - start
    return status == expected, latency, status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--interval", type=int, default=10,
                        help="Seconds between check runs")
    args = parser.parse_args()

    print(f"Synthetic monitor | target={args.url} | interval={args.interval}s")
    print("(In production this would push metrics to Prometheus pushgateway or Datadog)\n")

    run = 0
    while True:
        run += 1
        ts = datetime.now().strftime("%H:%M:%S")
        passed = 0
        print(f"[{ts}] Run #{run}")
        for c in CHECKS:
            ok, latency, status = check(args.url, c["path"], c["expected"])
            icon = "✓" if ok else "✗"
            print(f"  {icon}  {c['name']:<20}  {status}  {latency*1000:6.1f}ms")
            if ok:
                passed += 1
            results_window.append(ok)

        # Keep last 100 checks for rolling availability
        if len(results_window) > 100:
            results_window.pop(0)
        availability = sum(results_window) / len(results_window) * 100
        print(f"  Rolling availability (last {len(results_window)} checks): {availability:.1f}%\n")
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
