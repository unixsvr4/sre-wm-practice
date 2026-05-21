#!/bin/bash
# Run PromQL queries against local Prometheus from the command line.
# Usage:
#   bash observability/promql.sh --traffic
#   bash observability/promql.sh --errors
#   bash observability/promql.sh --latency
#   bash observability/promql.sh --saturation
#   bash observability/promql.sh --slo
#   bash observability/promql.sh --all
#   bash observability/promql.sh --query 'your_custom_promql_here'

PROMETHEUS="${PROMETHEUS_URL:-http://localhost:9090}"
JOB="wm-demo"

# ── core: run one instant query and print results ────────────────────────────
run_query() {
    local title="$1"
    local query="$2"
    echo ""
    echo "━━━ $title"
    echo "    PromQL: $query"
    echo ""
    curl -sG "$PROMETHEUS/api/v1/query" \
        --data-urlencode "query=$query" \
        | python3 -c "
import sys, json, datetime

data = json.load(sys.stdin)
if data['status'] != 'success':
    print('  ERROR:', data.get('error', 'unknown'))
    sys.exit(1)

result = data['data']['result']
if not result:
    print('  (no data — is generate_traffic.sh running?)')
    sys.exit(0)

for r in result:
    labels = {k: v for k, v in r['metric'].items() if k != '__name__'}
    label_str = '  '.join(f'{k}={v}' for k, v in sorted(labels.items())) if labels else '(all)'
    val = float(r['value'][1])
    # auto-format based on magnitude
    if abs(val) < 0.001 and val != 0:
        formatted = f'{val:.6f}'
    elif abs(val) < 1:
        formatted = f'{val:.4f}'
    elif abs(val) < 100:
        formatted = f'{val:.3f}'
    else:
        formatted = f'{val:,.1f}'
    print(f'  {label_str:<60} {formatted}')
"
}

# ── named queries ────────────────────────────────────────────────────────────
do_traffic() {
    run_query \
        "TRAFFIC — Request Rate (rps) by endpoint" \
        "sum(rate(http_requests_total{job=\"$JOB\"}[1m])) by (endpoint)"
}

do_errors() {
    run_query \
        "ERRORS — 5xx Error Rate %" \
        "sum(rate(http_requests_total{job=\"$JOB\",status_code=~\"5..\"}[1m])) / sum(rate(http_requests_total{job=\"$JOB\"}[1m])) * 100"
    run_query \
        "ERRORS — Count by status code" \
        "sum(rate(http_requests_total{job=\"$JOB\"}[1m])) by (status_code, endpoint)"
}

do_latency() {
    run_query \
        "LATENCY — p99 per endpoint (seconds)" \
        "histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{job=\"$JOB\"}[1m])) by (le, endpoint))"
    run_query \
        "LATENCY — p50 per endpoint (seconds)" \
        "histogram_quantile(0.50, sum(rate(http_request_duration_seconds_bucket{job=\"$JOB\"}[1m])) by (le, endpoint))"
}

do_saturation() {
    run_query \
        "SATURATION — In-flight requests" \
        "http_requests_in_flight{job=\"$JOB\"}"
}

do_slo() {
    run_query \
        "SLO — Success rate % over 1h (target ≥ 99.9%)" \
        "(1 - (sum(rate(http_requests_total{job=\"$JOB\",status_code=~\"5..\"}[1h])) / sum(rate(http_requests_total{job=\"$JOB\"}[1h])))) * 100"
    run_query \
        "SLO — Payment errors by type (rate/s)" \
        "sum(rate(http_errors_total{job=\"$JOB\"}[1m])) by (error_type)"
}

do_all() {
    do_traffic
    do_errors
    do_latency
    do_saturation
    do_slo
}

# ── argument parsing ─────────────────────────────────────────────────────────
if [[ $# -eq 0 ]]; then
    echo "Usage: bash observability/promql.sh [OPTION]"
    echo ""
    echo "  --traffic      Request rate per endpoint"
    echo "  --errors       5xx error rate + breakdown by status code"
    echo "  --latency      p99 and p50 latency per endpoint"
    echo "  --saturation   In-flight requests"
    echo "  --slo          Success rate % + error budget burn"
    echo "  --all          Run all of the above"
    echo "  --query <expr> Run a custom PromQL expression"
    echo ""
    echo "Environment:"
    echo "  PROMETHEUS_URL  (default: http://localhost:9090)"
    exit 0
fi

case "$1" in
    --traffic)    do_traffic ;;
    --errors)     do_errors ;;
    --latency)    do_latency ;;
    --saturation) do_saturation ;;
    --slo)        do_slo ;;
    --all)        do_all ;;
    --query)
        shift
        if [[ -z "${1:-}" ]]; then
            echo "Error: --query requires a PromQL expression"
            exit 1
        fi
        run_query "Custom query" "$1"
        ;;
    *)
        echo "Unknown option: $1  (run without args to see usage)"
        exit 1
        ;;
esac

echo ""
