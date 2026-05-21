#!/usr/bin/env python3
"""
SLO Error Budget Report — run after generate_traffic.sh has been running for a few minutes.
Usage: python slo_report.py [--prometheus http://localhost:9090] [--window 1h]

Demonstrates: SLI/SLO/SLA understanding the Wm JD explicitly requires.
  SLI = measured success rate (what we observe)
  SLO = 99.9% success rate (what we promise internally)
  SLA = contractual version of the SLO (external commitment)
"""
import argparse
import sys
import urllib.request
import json

SLO_TARGET = 0.999  # 99.9% — three nines


def promql(base_url: str, query: str) -> float:
    url = f"{base_url}/api/v1/query?query={urllib.parse.quote(query)}"
    with urllib.request.urlopen(url, timeout=5) as r:
        data = json.loads(r.read())
    result = data["data"]["result"]
    return float(result[0]["value"][1]) if result else 0.0


def main():
    import urllib.parse

    parser = argparse.ArgumentParser()
    parser.add_argument("--prometheus", default="http://localhost:9090")
    parser.add_argument("--window", default="1h", help="e.g. 1h, 6h, 30d")
    args = parser.parse_args()

    w = args.window
    try:
        total = promql(args.prometheus, f'sum(increase(http_requests_total{{job="wm-demo"}}[{w}]))')
        errors = promql(args.prometheus, f'sum(increase(http_requests_total{{job="wm-demo",status_code=~"5.."}}[{w}]))')
    except Exception as e:
        print(f"Cannot reach Prometheus: {e}")
        print("Make sure docker compose is running and traffic has been generated.")
        sys.exit(1)

    if total < 1:
        print("No data yet — run: bash observability/generate_traffic.sh")
        sys.exit(1)

    error_rate = errors / total
    success_rate = 1 - error_rate

    # Error budget math
    # 99.9% SLO → allowed downtime per month = 0.1% × 30d × 24h × 60m = 43.8 min
    # For a custom window, scale proportionally
    window_minutes = _parse_window_minutes(w)
    budget_total_min = window_minutes * (1 - SLO_TARGET)
    budget_used_min  = window_minutes * error_rate
    budget_left_min  = max(0.0, budget_total_min - budget_used_min)
    budget_left_pct  = (budget_left_min / budget_total_min * 100) if budget_total_min > 0 else 0

    print()
    print("=" * 54)
    print(f"  SLO Error Budget Report  — window={w}")
    print("=" * 54)
    print(f"  SLO target:          {SLO_TARGET*100:.1f}%  (three nines)")
    print(f"  Actual success rate: {success_rate*100:.3f}%")
    print(f"  Total requests:      {total:,.0f}")
    print(f"  Errors (5xx):        {errors:,.0f}  ({error_rate*100:.3f}%)")
    print()
    print(f"  Error budget for window:  {budget_total_min:.1f} min")
    print(f"  Budget consumed:          {budget_used_min:.1f} min")
    print(f"  Budget remaining:         {budget_left_min:.1f} min  ({budget_left_pct:.1f}%)")
    status = "✓ WITHIN BUDGET" if success_rate >= SLO_TARGET else "✗ SLO BREACHED — budget exhausted"
    print(f"  Status:                   {status}")
    print("=" * 54)
    print()
    print("  Talking key points:")
    print("  · SLI = this measured success_rate number")
    print("  · SLO = 99.9% internal target (this report enforces it)")
    print("  · SLA = contractual SLO signed with customers / legal")
    print("  · Error budget = what's left before SLO breach")
    print("  · When budget is low → freeze risky deploys, focus on reliability")
    print()


def _parse_window_minutes(w: str) -> float:
    if w.endswith("d"):
        return float(w[:-1]) * 24 * 60
    if w.endswith("h"):
        return float(w[:-1]) * 60
    if w.endswith("m"):
        return float(w[:-1])
    return 60.0


if __name__ == "__main__":
    main()
