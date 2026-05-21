# sre-wm-practice
SRE practice repo for **Weedmaps** — cannabis tech, 100% cloud-native, K8s on AWS.
Everything runs locally on **Mac M1 with OrbStack**. No AWS account needed.

---

## Prerequisites

| Tool | Install | Check |
|------|---------|-------|
| OrbStack | [orbstack.dev](https://orbstack.dev) | `orb version` |
| Docker (via OrbStack) | included | `docker info` |
| kubectl (via OrbStack) | included | `kubectl version` |
| Python 3 | included on Mac | `python3 --version` |

> OrbStack provides both Docker and a built-in Kubernetes cluster (`orbstack` context).  
> No separate `kubectl` or `minikube` install needed.

---

## What's in this repo

```
sre-wm-practice/
├── app/                              ← FastAPI product/order service (golden signals + OTel traces)
├── k8s/
│   ├── deployment.yaml               ← K8s deployment (HPA, non-root UID, readiness probes)
│   ├── service.yaml
│   └── hpa.yaml                      ← Autoscales 2→10 replicas at 60% CPU
├── observability/
│   ├── docker-compose.yml            ← Full stack: app + OTel Collector + Jaeger + Prometheus + Grafana
│   ├── generate_traffic.sh           ← Seeds product/order traffic so dashboards show data
│   ├── otel-collector-config.yml     ← OTel Collector pipeline (OTLP → Jaeger)
│   ├── grafana/dashboards/           ← Pre-built Golden Signals dashboard (auto-loads)
│   └── prometheus/alerts.yml         ← 4 golden signal alert rules
├── scripts/
│   ├── synthetic_monitor.py          ← Scripted user journeys, rolling availability %
│   └── toil_check.py                 ← Scans for CrashLoopBackOff pods, optional auto-restart
├── .circleci/config.yml              ← CircleCI pipeline (their CI tool)
├── .github/workflows/ci.yml          ← GitHub Actions equivalent
├── terraform/eks.tf                  ← EKS cluster reference (Graviton2, IRSA, private API)
└── shutdown.sh                       ← Stops everything cleanly
```

---

## Step-by-step demo

### Step 1 — Start the full stack

```bash
cd sre-wm-practice/observability
docker compose up -d --build
```

Wait ~20s for the app image to build. Check all containers are up:

```bash
docker compose ps
```

All 6 services should show `Up` or `(healthy)`:

| Service | URL | What it is |
|---------|-----|-----------|
| App API | http://localhost:8080/health | FastAPI product/order microservice |
| Prometheus | http://localhost:9090 | Metrics scraper |
| Grafana | http://localhost:3000 | Dashboards — admin / admin |
| Jaeger | http://localhost:16686 | Distributed tracing UI |
| Alertmanager | http://localhost:9093 | Alert routing |
| OTel Collector | http://localhost:8888/metrics | Collector self-metrics |

---

### Step 2 — Generate traffic

Open a second terminal:

```bash
cd sre-wm-practice/observability
bash generate_traffic.sh &
```

This hits `/api/products`, `/api/orders` (POST + GET) every 0.3s with a mix of valid and invalid IDs — producing realistic golden signal metrics including a ~2% error rate and 5% slow-path for p99 demo.

---

### Step 3 — Grafana: Golden Signals dashboard

#### 3a. View the pre-built dashboard

1. Open **http://localhost:3000**
2. Log in: `admin` / `admin`
3. Click **☰** (hamburger menu, top-left) → **Dashboards**
4. Click **Golden Signals — wm-sre-demo**

The dashboard auto-refreshes every 5 seconds. If panels show "No data", confirm `generate_traffic.sh` is running (Step 2).

You'll see 4 live panels:

| Panel | Golden Signal | Analysis |
|-------|--------------|------------------------------|
| Traffic — Request Rate (rps) | Traffic | "We alert when rate is 2× the 30-min baseline — catches traffic spikes and DDoS before customers feel it" |
| Errors — 5xx Rate | Errors | "SLO is 99.9% success rate. Alert fires at >1% error rate sustained for 2 minutes" |
| Latency — p99 & p50 | Latency | "The 5% slow-path in the app drives p99 tail latency — alert fires when p99 > 500ms for 3 minutes" |
| Saturation — In-flight Requests | Saturation | "4th golden signal — queue depth before the service saturates. Alert at >50 in-flight" |

---

#### 3b. Run PromQL queries — two ways

Every query below works **in the Grafana UI** (visual) or **from the terminal** (instant, no browser needed). Both hit the same Prometheus API.

**Quick bash reference — all golden signals at once:**
```bash
bash observability/promql.sh --all
```

**Grafana Explore — how to switch to Code mode:**
1. Click **☰** → **Explore** (compass icon)
2. In the query panel, find the **`Builder | Code`** toggle on the right side of the `A (Prometheus)` row — click **Code**
3. The dropdowns disappear and a plain text box appears — paste your PromQL there
4. Press **Shift+Enter** or click **Run query**
5. Set the time range (top right) to **Last 15 minutes**

---

**Query 1 — Traffic: request rate per endpoint**

*Grafana UI — paste in Code mode:*
```promql
sum(rate(http_requests_total{job="wm-demo"}[1m])) by (endpoint)
```

*Bash:*
```bash
bash observability/promql.sh --traffic
```
```
━━━ TRAFFIC — Request Rate (rps) by endpoint
  endpoint=/api/products    1.245
  endpoint=/api/orders      1.245
  endpoint=/api/products/1  0.311
```

- `rate()` computes per-second average over the time window
- `[1m]` = 1-minute window for live incident detection; use `[5m]` in alert rules to reduce noise
- `by (endpoint)` = one line per endpoint

> *Analysis: "This is our traffic signal. In alerting I use [5m] to avoid noise from brief spikes, but in Explore I use [1m] to see what's happening right now during an incident."*

---

**Query 2 — Errors: 5xx error rate as a percentage**

*Grafana UI — paste in Code mode:*
```promql
sum(rate(http_requests_total{job="wm-demo",status_code=~"5.."}[1m]))
/
sum(rate(http_requests_total{job="wm-demo"}[1m]))
* 100
```

*Bash:*
```bash
bash observability/promql.sh --errors
```
```
━━━ ERRORS — 5xx Error Rate %
  (all)                     1.980

━━━ ERRORS — Count by status code
  endpoint=/api/orders  status_code=200    1.223
  endpoint=/api/orders  status_code=500    0.025
  endpoint=/api/products/150  status_code=404    0.311
```

- `status_code=~"5.."` is a **regex label matcher** — matches 500, 502, 503, 504 in one expression
- Dividing errors by total gives the ratio; ×100 for percentage

> *Analysis: "Our SLO target is 99.9% — 0.1% max error rate. The `=~` operator does regex matching on label values. If this stays above 1% for 2 minutes the ErrorRateHigh alert fires."*

---

**Query 3 — Latency: p99 and p50 per endpoint**

*Grafana UI — paste Query A in Code mode, click `+ Add query` for Query B:*
```promql
# Query A — p99
histogram_quantile(0.99,
  sum(rate(http_request_duration_seconds_bucket{job="wm-demo"}[1m])) by (le, endpoint)
)

# Query B — p50 (add as second query to overlay on the same graph)
histogram_quantile(0.50,
  sum(rate(http_request_duration_seconds_bucket{job="wm-demo"}[1m])) by (le, endpoint)
)
```

*Bash:*
```bash
bash observability/promql.sh --latency
```
```
━━━ LATENCY — p99 per endpoint (seconds)
  endpoint=/api/orders      0.812   ← 5% slow-path kicking in
  endpoint=/api/products    0.079
  endpoint=/api/products/1  0.049

━━━ LATENCY — p50 per endpoint (seconds)
  endpoint=/api/orders      0.058   ← p50 is fine; p99 is not
  endpoint=/api/products    0.044
```

- `_bucket` metric records counts per latency band
- `le` = "less than or equal to", the bucket boundary; required for histogram_quantile
- The p99−p50 gap is the tail latency story

> *Analysis: "The gap between p50 and p99 reveals tail latency. p99 of 812ms while p50 is 58ms means some users wait 14× longer. Averages completely hide this."*

---

**Query 4 — Saturation: in-flight requests**

*Grafana UI — paste in Code mode, then switch visualization to **Stat** for a live number:*
```promql
http_requests_in_flight{job="wm-demo"}
```

*Bash:*
```bash
bash observability/promql.sh --saturation
```
```
━━━ SATURATION — In-flight requests
  instance=app:8080  job=wm-demo    3.000
```

> *Analysis: "Saturation is the hardest golden signal because it's service-specific. For this web service, in-flight requests is a leading indicator — when it climbs, latency follows seconds later."*

---

**Query 5 — SLO burn rate**

*Grafana UI — paste in Code mode:*
```promql
(
  1 - (
    sum(rate(http_requests_total{job="wm-demo",status_code=~"5.."}[1h]))
    /
    sum(rate(http_requests_total{job="wm-demo"}[1h]))
  )
) * 100
```

*Bash:*
```bash
bash observability/promql.sh --slo
```
```
━━━ SLO — Success rate % over 1h (target ≥ 99.9%)
  (all)                     98.120
```

> *Analysis: "If this reads 98.1%, we've already burned through the monthly error budget in the first hour. That triggers a deploy freeze — stop shipping features, focus on reliability."*

---

**Query 6 — Custom query (any PromQL expression)**

*Bash only:*
```bash
bash observability/promql.sh --query 'rate(http_requests_total{job="wm-demo"}[30s])'
```

> *Analysis: "In production I query Prometheus directly from bash in runbooks and incident scripts. When a page fires at 3am I don't want to open a browser — I run the script and see numbers immediately."*

---

#### 3c. View active alerts

1. Open **http://localhost:9093** — Alertmanager UI shows any currently firing alerts
2. Open **http://localhost:9090/alerts** — Prometheus shows all 4 alert rules and their current evaluation state

> *Analysis: "Alert rules live in `observability/prometheus/alerts.yml` — version-controlled, reviewed in PRs. In production these route to PagerDuty for on-call and Slack for the engineering channel. The goal is to alert on symptoms (high error rate, high latency) not causes — so the on-call focuses on impact, not guessing root causes at 3am."*

---

### Step 4 — SLI/SLO/SLA report (run live)

```bash
cd sre-wm-practice
python observability/slo_report.py --window 1h
```

Example output:
```
======================================================
  SLO Error Budget Report  — window=1h
======================================================
  SLO target:          99.9%  (three nines)
  Actual success rate: 98.120%
  Total requests:      4,821
  Errors (5xx):        91  (1.880%)

  Error budget for window:  0.1 min
  Budget consumed:          1.1 min
  Budget remaining:         0.0 min  (0.0%)
  Status:                   ✗ SLO BREACHED — budget exhausted
======================================================

  Talking key points:
  · SLI = this measured success_rate number
  · SLO = 99.9% internal target
  · SLA = contractual SLO signed with customers / legal
  · Error budget = what's left before SLO breach
```

**Analysis:**
- **SLI** = the measured number — what we observe (success_rate: 98.12%)
- **SLO** = internal target we commit to (99.9% — three nines)
- **SLA** = contractual version of the SLO — the thing with financial penalties
- **Error budget** = `1 - SLO_target` = 0.1% of requests allowed to fail per month (43.8 minutes of downtime)
- *"When the budget is exhausted, we stop shipping features and focus on reliability. This turns SRE from a blocker into a business conversation: do we spend the budget on velocity or stability?"*

---

### Step 5 — Distributed tracing in Jaeger

1. Open **http://localhost:16686**
2. In the **Service** dropdown (top-left), select `wm-sre-demo`
3. Click **Find Traces**
4. Click any trace to expand it — you'll see spans for each endpoint with exact durations

**What to look for in the trace view:**
- The root span = the full request duration
- Child spans = `list-products`, `get-product`, `list-orders`, `create-order`
- Any span > 400ms = the 5% slow-path kicking in

> *Analysis: "OpenTelemetry is the merger of three competing standards — OpenTracing, OpenCensus, and OpenMetrics — into one vendor-neutral SDK and wire format. The app sends traces via OTLP gRPC to the OTel Collector, which forwards to Jaeger. To switch from Jaeger to Datadog or Honeycomb, I change one exporter line in otel-collector-config.yml — zero app code changes. That's the value of the vendor-neutral approach."*

---

### Step 6 — Synthetic monitoring (run live)

```bash
cd sre-wm-practice
python scripts/synthetic_monitor.py
```

Output every 10 seconds:
```
[14:25:18] Run #1
  ✓  health-check          200    16.5ms
  ✓  list-products         200    53.8ms
  ✓  get-product           200    33.8ms
  ✗  list-orders           500     5.6ms
  Rolling availability (last 4 checks): 87.5%
```

> *Analysis: "Passive monitoring waits for a real user to hit an error before we know about it. Synthetic monitoring proactively runs scripted user journeys from outside the cluster every N seconds — it's how we catch a broken checkout at 3am before any customer does. In production we'd run this from multiple AWS regions and page on-call if availability drops below 99%. Weedmaps specifically called out synthetic monitoring flows in the JD — this is that."*

Stop with **Ctrl+C**.

---

### Step 7 — Toil reduction (run on OrbStack K8s)

```bash
kubectl config use-context orbstack
python scripts/toil_check.py
```

If all pods are healthy:
```
✓ All pods healthy — no action required
```

To test the auto-restart feature (requires a CrashLoopBackOff pod):
```bash
python scripts/toil_check.py --auto-restart
```

> *Analysis: "Google SRE defines toil as manual, repetitive, automatable operational work that scales linearly with service growth. Before this script, the on-call got paged, SSH'd into a node, ran kubectl describe, and decided whether to restart the pod. That's 5–10 minutes of toil per incident. This script runs as a cron job in CI — it pages only when auto-restart isn't enough, meaning the on-call gets actionable signal instead of noise."*

---

### Step 8 — K8s deployment on OrbStack

```bash
# Build the image (OrbStack K8s shares the Docker daemon — no registry push needed)
docker build -t wm-sre-demo:local app/

# Deploy
kubectl config use-context orbstack
kubectl apply -f k8s/

# Verify
kubectl get pods -n wm-demo
kubectl get hpa -n wm-demo
```

Pods come up in ~15 seconds. Key hardening in `k8s/deployment.yaml`:

```yaml
runAsNonRoot: true
runAsUser: 1001          # numeric UID — required for K8s to verify non-root
readOnlyRootFilesystem: true
allowPrivilegeEscalation: false
capabilities:
  drop: ["ALL"]          # zero Linux capabilities
maxUnavailable: 0        # zero-downtime rolling deploys — required for multiple deploys/day
```

The HPA scales 2→10 replicas at 60% CPU — handles traffic spikes without manual intervention.

---

### Step 9 — CI/CD pipeline reference

Point to `.github/workflows/ci.yml` (**triggers on every push to main**). Walk through the 3 stages:

```
commit → lint (ruff) + pytest (7 tests) → SAST (Bandit) ──┐
                                         → build + Trivy ──┘
```

**Key talking points:**
- Pipeline runs on every push — any broken code shows up in GitHub Actions within 2 minutes
- Bandit SAST catches security hotspots (medium+ severity) without external tokens
- Trivy CVE scan on the built image — set `exit-code: 1` to gate on CRITICAL/HIGH in production
- Multi-arch build (`linux/amd64,linux/arm64`) — runs on both CI runners and M1 Macs
- `maxUnavailable: 0` in the K8s deployment = zero-downtime rolling updates
- This supports **trunk-based development** → multiple deploys per day

**GitHub branching strategy** (they ask this in the JD):

> *Analysis: "Trunk-based development — main is always deployable, feature branches live less than 2 days, and feature flags control what users see rather than long-lived branches. GitFlow doesn't work for multiple deploys per day because long-lived branches create merge conflicts and slow release cadence."*

---

### Step 10 — Shut down everything

```bash
cd sre-wm-practice
bash shutdown.sh
```

Stops in order:
1. Background scripts (`generate_traffic.sh`, `synthetic_monitor.py`, `slo_report.py`)
2. All Docker Compose containers (`wm-practice` project)
3. `wm-demo` K8s namespace — **waits for all pods to fully terminate**
4. Local Docker image `wm-sre-demo:local`

Final line prints `(none — all clean)` when `docker ps` has nothing left except OrbStack's own system pods (`coredns`, `local-path-provisioner`).

---

## Cheat sheet — talking answers

```
Stack:    FastAPI → OTel Collector → Jaeger (traces) + Prometheus → Grafana (metrics)
Signals:  Traffic (rps) + Errors (5xx%) + Latency (p99) + Saturation (in-flight)
SLO:      99.9% success rate → 43.8 min/month error budget → freeze deploys when exhausted
OTel:     OpenTracing + OpenCensus + OpenMetrics merged → one SDK, vendor-neutral wire format
CI/CD:    CircleCI → trunk-based → multi-arch build → staging smoke test → manual gate → prod
K8s:      HPA 2→10 replicas, maxUnavailable=0, non-root, readOnlyRootFilesystem, drop ALL caps
Toil:     Automate CrashLoopBackOff restarts → on-call gets signal not noise
Synth:    Scripted user journeys from outside the cluster → catch outages before users do
```

## Two strong questions to ask the manager

1. *"What's the current state of your error budget process — do teams have SLOs defined and is there a mechanism to freeze deploys when the budget is low?"*
2. *"How do you handle the tension between developer velocity (multiple deploys/day) and reliability when an error budget is burning fast?"*
