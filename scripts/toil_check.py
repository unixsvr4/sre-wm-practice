#!/usr/bin/env python3
"""
Toil reduction script — auto-detect pods in CrashLoopBackOff / OOMKilled.
Demonstrates SRE toil concept for the Weedmaps interview.

In SRE, "toil" = manual, repetitive, automatable operational work:
  Before: Ops gets paged → SSH into node → kubectl describe pod → decide action
  After:  This script runs every 5 min in CI / cron, pages only when action needed

Usage:
  kubectl config use-context orbstack
  python scripts/toil_check.py
  python scripts/toil_check.py --namespace payment-app --auto-restart
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime

BAD_REASONS = {"CrashLoopBackOff", "OOMKilled", "Error", "ImagePullBackOff", "ErrImagePull"}


def get_pods(namespace: str = None) -> list[dict]:
    cmd = ["kubectl", "get", "pods", "-o", "json"]
    cmd += ["-n", namespace] if namespace else ["-A"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"kubectl error: {result.stderr.strip()}")
        sys.exit(1)
    data = json.loads(result.stdout)
    bad = []
    for pod in data.get("items", []):
        ns  = pod["metadata"]["namespace"]
        name = pod["metadata"]["name"]
        for cs in pod.get("status", {}).get("containerStatuses", []):
            waiting = cs.get("state", {}).get("waiting", {})
            reason  = waiting.get("reason", "")
            if reason in BAD_REASONS:
                bad.append({
                    "namespace":  ns,
                    "pod":        name,
                    "container":  cs["name"],
                    "reason":     reason,
                    "restarts":   cs.get("restartCount", 0),
                })
    return bad


def restart_pod(ns: str, pod: str):
    result = subprocess.run(
        ["kubectl", "delete", "pod", pod, "-n", ns, "--grace-period=0"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"    → Deleted {ns}/{pod} (controller will recreate it)")
    else:
        print(f"    → Failed to delete: {result.stderr.strip()}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--namespace", "-n", help="Limit to one namespace (default: all)")
    parser.add_argument("--auto-restart", action="store_true",
                        help="Auto-delete CrashLoopBackOff pods so the controller restarts them")
    args = parser.parse_args()

    print(f"\n[{datetime.now().isoformat()}] Toil Check — bad pod scanner")
    print("=" * 60)
    bad = get_pods(args.namespace)

    if not bad:
        print("✓ All pods healthy — no action required")
        return 0

    print(f"⚠  {len(bad)} pod(s) need attention:\n")
    for p in bad:
        print(f"  {p['namespace']}/{p['pod']}")
        print(f"    container={p['container']}  reason={p['reason']}  restarts={p['restarts']}")
        if args.auto_restart and p["reason"] in {"CrashLoopBackOff", "OOMKilled"}:
            restart_pod(p["namespace"], p["pod"])

    print()
    print("Remediation guide:")
    print("  CrashLoopBackOff → kubectl logs <pod> -n <ns> --previous")
    print("  OOMKilled        → increase resources.limits.memory in the deployment")
    print("  ImagePullBackOff → check image name/tag and imagePullSecrets")
    return 1


if __name__ == "__main__":
    sys.exit(main())
