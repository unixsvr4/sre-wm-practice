#!/bin/bash
# Clean shutdown — stops everything started by this repo.
# Run from repo root: bash shutdown.sh

set -euo pipefail

# ── helper: delete a K8s namespace and wait for it to fully disappear ────────
delete_ns() {
    local ns="$1"
    if kubectl get namespace "$ns" &>/dev/null 2>&1; then
        echo "  Deleting namespace $ns ..."
        kubectl delete namespace "$ns" --grace-period=5 &
        if kubectl wait --for=delete namespace/"$ns" --timeout=60s 2>/dev/null; then
            echo "  ✓ Namespace $ns fully terminated"
        else
            echo "  ⚠ Namespace $ns still terminating — pods will clean up shortly"
        fi
    else
        echo "  · Namespace $ns was not present"
    fi
}

echo "Shutting down sre-wm-practice demo..."

# ── [1] Background scripts ───────────────────────────────────────────────────
echo "[1/4] Stopping background scripts..."
pkill -f "generate_traffic.sh" 2>/dev/null \
    && echo "  ✓ generate_traffic.sh stopped" \
    || echo "  · generate_traffic.sh was not running"
pkill -f "synthetic_monitor.py" 2>/dev/null \
    && echo "  ✓ synthetic_monitor.py stopped" \
    || echo "  · synthetic_monitor.py was not running"
pkill -f "slo_report.py" 2>/dev/null \
    && echo "  ✓ slo_report.py stopped" \
    || echo "  · slo_report.py was not running"

# ── [2] Docker Compose stack ─────────────────────────────────────────────────
echo "[2/4] Stopping Docker Compose services (wm-practice)..."
COMPOSE_DIR="$(cd "$(dirname "$0")/observability" && pwd)"
if docker compose -f "$COMPOSE_DIR/docker-compose.yml" ps -q 2>/dev/null | grep -q .; then
    docker compose -f "$COMPOSE_DIR/docker-compose.yml" down
    echo "  ✓ All compose containers stopped"
else
    echo "  · No compose containers were running"
fi

# ── [3] Kubernetes namespace ─────────────────────────────────────────────────
echo "[3/4] Removing Kubernetes resources..."
kubectl config use-context orbstack 2>/dev/null || true
delete_ns wm-demo

# ── [4] Local Docker image ────────────────────────────────────────────────────
echo "[4/4] Removing local build image..."
if docker image inspect wm-sre-demo:local &>/dev/null 2>&1; then
    docker rmi wm-sre-demo:local
    echo "  ✓ Image wm-sre-demo:local removed"
else
    echo "  · Image wm-sre-demo:local was not present"
fi

# ── Final verification ────────────────────────────────────────────────────────
echo ""
echo "Remaining containers (OrbStack K8s system pods are normal):"
docker ps --format "  {{.Names}}\t{{.Status}}" \
    | grep -v "k8s_coredns\|k8s_local-path\|k8s_POD_coredns\|k8s_POD_local-path" \
    | grep -v "^$" || echo "  (none — all clean)"
echo ""
echo "Done. To restart: cd observability && docker compose up -d --build"
