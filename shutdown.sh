#!/bin/bash
set -euo pipefail

echo "Shutting down sre-wm-practice demo..."

# ── Background scripts (generate_traffic.sh, synthetic_monitor.py) ──────────
echo "[1/4] Stopping background scripts..."
pkill -f "generate_traffic.sh" 2>/dev/null && echo "  ✓ generate_traffic.sh stopped" || echo "  · generate_traffic.sh was not running"
pkill -f "synthetic_monitor.py" 2>/dev/null && echo "  ✓ synthetic_monitor.py stopped" || echo "  · synthetic_monitor.py was not running"
pkill -f "slo_report.py"        2>/dev/null && echo "  ✓ slo_report.py stopped"        || echo "  · slo_report.py was not running"

# ── Docker Compose stack ─────────────────────────────────────────────────────
echo "[2/4] Stopping Docker Compose services..."
COMPOSE_DIR="$(cd "$(dirname "$0")/observability" && pwd)"
if docker compose -f "$COMPOSE_DIR/docker-compose.yml" ps -q 2>/dev/null | grep -q .; then
    docker compose -f "$COMPOSE_DIR/docker-compose.yml" down
    echo "  ✓ All containers stopped"
else
    echo "  · No containers were running"
fi

# ── Kubernetes namespace ─────────────────────────────────────────────────────
echo "[3/4] Removing Kubernetes resources (namespace wm-demo)..."
if kubectl get namespace wm-demo &>/dev/null 2>&1; then
    kubectl delete namespace wm-demo --grace-period=5
    echo "  ✓ Namespace wm-demo deleted"
else
    echo "  · Namespace wm-demo was not present"
fi

# ── Local Docker image (optional cleanup) ────────────────────────────────────
echo "[4/4] Removing local build image..."
if docker image inspect wm-sre-demo:local &>/dev/null 2>&1; then
    docker rmi wm-sre-demo:local
    echo "  ✓ Image wm-sre-demo:local removed"
else
    echo "  · Image wm-sre-demo:local was not present"
fi

echo ""
echo "Done. Nothing is running."
echo "To restart: cd observability && docker compose up -d --build"
