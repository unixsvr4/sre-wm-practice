# devops-weedmaps-practice
SRE interview practice repo for Weedmaps — built around their specific JD requirements.

## Start everything (60 seconds)

```bash
cd observability
docker compose up -d --build
# wait ~20s for app to build

# Seed traffic so golden signals appear in Grafana
bash generate_traffic.sh &
```

| Service | URL |
|---------|-----|
| App API | http://localhost:8080 |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000  (admin / admin) |
| Jaeger traces | http://localhost:16686 |
| Alertmanager | http://localhost:9093 |

---

## What to show in the 30-min manager call

### 1 — Golden signals in Grafana
Grafana opens with Prometheus pre-wired. Paste these PromQL queries in Explore:

```promql
# LATENCY — p99 response time
histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, endpoint))

# TRAFFIC — requests per second
sum(rate(http_requests_total[5m])) by (endpoint)

# ERRORS — 5xx error rate
sum(rate(http_requests_total{status_code=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))

# SATURATION — in-flight requests
http_requests_in_flight
```

**What to say:** "We instrument every service with these four signals from day one.
We alert on them before customers feel anything — the SLO alerts in `prometheus/alerts.yml`
fire when error rate > 1% or p99 > 500ms for 3 minutes."

---

### 2 — SLI/SLO/SLA (run this live)
```bash
python observability/slo_report.py --window 1h
```
Output shows: success rate, error budget total, budget consumed, budget remaining.

**What to say:**
- **SLI** = the measured number (success rate = 99.87%)
- **SLO** = internal target (99.9% — three nines)
- **SLA** = contractual version signed with customers
- **Error budget** = what's left before SLO breach. When it's < 10%, we freeze risky deploys and focus on reliability, not features. This is how we stay data-driven instead of subjective about when to ship.

---

### 3 — Distributed tracing in Jaeger
Open http://localhost:16686 → select service `weedmaps-sre-demo` → Find Traces.

**What to say:** "OpenTelemetry is the convergence of OpenTracing, OpenCensus, and OpenMetrics
into one vendor-neutral standard. Every span shows exact latency per operation — DB calls,
downstream services — so we can pinpoint where time is spent, not just know that something
is slow."

---

### 4 — Synthetic monitoring
```bash
python scripts/synthetic_monitor.py
```
Runs scripted user journeys every 10 seconds, reports availability %.

**What to say:** "Passive monitoring waits for real users to hit errors.
Synthetic monitoring runs scripted journeys from outside the cluster 24/7 — it's how
we catch a broken checkout flow at 3am before any customer does.
We'd run this from multiple AWS regions and alert if availability drops below threshold."

---

### 5 — Toil reduction (run on OrbStack K8s)
```bash
kubectl config use-context orbstack
python scripts/toil_check.py
python scripts/toil_check.py --auto-restart   # auto-delete CrashLoopBackOff pods
```

**What to say:** "Google SRE defines toil as manual, repetitive work that doesn't
permanently improve the system. Before this script, someone had to get paged,
SSH in, kubectl describe the pod, decide whether to restart it.
This script runs in CI as a cron job. It pages only when the restart isn't enough —
meaning the on-call gets real signal, not noise."

---

### 6 — CircleCI pipeline
Point to `.circleci/config.yml`.

**What to say:** "Weedmaps does multiple production deploys a day.
That requires: fast CI (lint+test in parallel with no flaky tests),
zero-downtime rolling deploys (`maxUnavailable: 0` in the Deployment),
readiness probes that prevent bad pods from getting traffic,
and a manual approval gate before prod so we're intentional not reckless.
The HPA in `k8s/hpa.yaml` handles traffic spikes automatically."

---

## GitHub branching strategy
(They ask about this in the JD)

**Trunk-based development** — the right answer for multiple-deploys-per-day:
- `main` is always deployable
- Feature branches live < 2 days (small PRs)
- Feature flags control what users see, not long-lived branches
- `release/x.y` branch only if a hotfix is needed against a frozen release

Why not GitFlow: long-lived branches create merge conflicts and slow release cadence.
Why not feature branches > 1 week: they diverge and the integration tax is too high.

---

## OpenTelemetry convergence (the interview answer)

"OpenTracing, OpenCensus, and OpenMetrics were competing standards.
OpenTelemetry merged all three into one SDK and wire format.
Everything in this repo uses OTel:
- Traces → OTLP gRPC → OTel Collector → Jaeger
- Metrics → Prometheus exposition format (OpenMetrics-compatible)
- The Collector acts as a vendor-neutral router — swap Jaeger for Datadog or Honeycomb
  by changing one exporter config line, zero app changes."

---

## Two strong questions to ask the manager

1. *"What's the current state of your error budget process — do teams have SLOs defined and is there a mechanism to freeze deploys when the budget is low?"*

2. *"How do you handle the tension between developer velocity (multiple deploys/day) and reliability when an error budget is burning fast?"*

---

## K8s manifests (apply to OrbStack)
```bash
kubectl config use-context orbstack
kubectl apply -f k8s/
kubectl get pods -n weedmaps-demo
```
*(Update the image in `k8s/deployment.yaml` to your registry first)*
