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

| Panel | Golden Signal | What to say in the interview |
|-------|--------------|------------------------------|
| Traffic — Request Rate (rps) | Traffic | "We alert when rate is 2× the 30-min baseline — catches traffic spikes and DDoS before customers feel it" |
| Errors — 5xx Rate | Errors | "SLO is 99.9% success rate. Alert fires at >1% error rate sustained for 2 minutes" |
| Latency — p99 & p50 | Latency | "The 5% slow-path in the app drives p99 tail latency — alert fires when p99 > 500ms for 3 minutes" |
| Saturation — In-flight Requests | Saturation | "4th golden signal — queue depth before the service saturates. Alert at >50 in-flight" |

---

#### 3b. Run PromQL queries live in Explore

**How to open Explore:**
1. Click **☰** → **Explore** (compass icon in the left sidebar)
2. Confirm the datasource dropdown at the top reads **Prometheus**
3. Paste each query into the query box → press **Shift+Enter** or click **Run query**
4. Set the time range (top right) to **Last 15 minutes** for best visibility

---

**Query 1 — Traffic: request rate per endpoint**
```promql
sum(rate(http_requests_total{job="wm-demo"}[1m])) by (endpoint)
```
Returns requests-per-second for each endpoint as separate lines.

- `rate()` computes per-second average over the time window
- `[1m]` = 1-minute window — responsive for live incident detection
- `by (endpoint)` = split by the endpoint label

> *Say: "This is our traffic signal. In alerting I use [5m] to avoid noise from brief spikes, but in Explore I use [1m] to see what's happening right now during an incident."*

---

**Query 2 — Errors: 5xx error rate as a percentage**
```promql
sum(rate(http_requests_total{job="wm-demo",status_code=~"5.."}[1m]))
/
sum(rate(http_requests_total{job="wm-demo"}[1m]))
* 100
```
Returns a single number — the percentage of requests returning 5xx (e.g. `2.1` = 2.1%).

- `status_code=~"5.."` is a **regex label matcher** — matches 500, 502, 503, 504
- Dividing errors by total gives the error ratio; multiply by 100 for percentage

> *Say: "Our SLO target is 99.9% success — 0.1% max error rate. The app intentionally has a ~2% error rate to make this visible in the demo. The `=~` operator does regex matching on label values — it's how Prometheus lets you match a class of status codes without listing each one."*

---

**Query 3 — Latency: p99 per endpoint**
```promql
histogram_quantile(0.99,
  sum(rate(http_request_duration_seconds_bucket{job="wm-demo"}[1m])) by (le, endpoint)
)
```
Returns p99 latency in seconds for each endpoint.

- `_bucket` is the histogram metric — counts how many requests fell into each latency band
- `by (le, endpoint)` — `le` = "less than or equal to", the bucket boundary label; required for `histogram_quantile`
- Change `0.99` → `0.50` for median latency

**To overlay p50 on the same graph:** click **+ Add query** and paste:
```promql
histogram_quantile(0.50,
  sum(rate(http_request_duration_seconds_bucket{job="wm-demo"}[1m])) by (le, endpoint)
)
```

> *Say: "The gap between p50 and p99 reveals tail latency. The app has a 5% slow path that sleeps 450–900ms — that's what drives the p99 up while p50 stays low. This is exactly the kind of issue averages hide but percentiles expose."*

---

**Query 4 — Saturation: in-flight requests**
```promql
http_requests_in_flight{job="wm-demo"}
```
A real-time Gauge — the number of requests being processed at this exact moment.

To display as a large number: click the **visualization type dropdown** (top-left of the panel) → select **Stat**.

> *Say: "Saturation is the hardest golden signal to define because it's service-specific. For a web service, in-flight requests is a leading indicator — when this climbs, latency follows seconds later. For a database, saturation would be connection pool exhaustion. For a queue worker, it'd be queue depth."*

---

**Query 5 — SLO burn rate: is the error budget burning too fast?**
```promql
(
  1 - (
    sum(rate(http_requests_total{job="wm-demo",status_code=~"5.."}[1h]))
    /
    sum(rate(http_requests_total{job="wm-demo"}[1h]))
  )
) * 100
```
Returns success rate % over the past hour. Target: ≥ 99.9%.

> *Say: "This is the SLO burn rate query on a 1-hour window. If it reads 99.5% right now, we've already burned 5× our daily error budget in one hour — at that rate the monthly budget exhausts in 6 hours. That triggers a deploy freeze and all hands on reliability. The 1-hour window catches fast burns; a 30-day window is used for monthly budget reporting."*

---

**Query 6 — Node CPU utilization from node-exporter**
```promql
100 - (avg by(instance)(rate(node_cpu_seconds_total{mode="idle"}[1m])) * 100)
```
Returns CPU utilization % of the host running the containers.

> *Say: "This is system-level saturation from node-exporter, independent of the app. We correlate host CPU with in-flight requests to distinguish 'the app is slow' from 'the host is overloaded'. In EKS we'd use container_cpu_usage_seconds_total and kube-state-metrics for pod-level CPU."*

---

#### 3c. View active alerts

1. Open **http://localhost:9093** — Alertmanager UI shows any currently firing alerts
2. Open **http://localhost:9090/alerts** — Prometheus shows all 4 alert rules and their current evaluation state

> *Say: "Alert rules live in `observability/prometheus/alerts.yml` — version-controlled, reviewed in PRs. In production these route to PagerDuty for on-call and Slack for the engineering channel. The goal is to alert on symptoms (high error rate, high latency) not causes — so the on-call focuses on impact, not guessing root causes at 3am."*

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

  Interview key points:
  · SLI = this measured success_rate number
  · SLO = 99.9% internal target
  · SLA = contractual SLO signed with customers / legal
  · Error budget = what's left before SLO breach
```

**What to say:**
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

> *Say: "OpenTelemetry is the merger of three competing standards — OpenTracing, OpenCensus, and OpenMetrics — into one vendor-neutral SDK and wire format. The app sends traces via OTLP gRPC to the OTel Collector, which forwards to Jaeger. To switch from Jaeger to Datadog or Honeycomb, I change one exporter line in otel-collector-config.yml — zero app code changes. That's the value of the vendor-neutral approach."*

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

> *Say: "Passive monitoring waits for a real user to hit an error before we know about it. Synthetic monitoring proactively runs scripted user journeys from outside the cluster every N seconds — it's how we catch a broken checkout at 3am before any customer does. In production we'd run this from multiple AWS regions and page on-call if availability drops below 99%. Weedmaps specifically called out synthetic monitoring flows in the JD — this is that."*

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

> *Say: "Google SRE defines toil as manual, repetitive, automatable operational work that scales linearly with service growth. Before this script, the on-call got paged, SSH'd into a node, ran kubectl describe, and decided whether to restart the pod. That's 5–10 minutes of toil per incident. This script runs as a cron job in CI — it pages only when auto-restart isn't enough, meaning the on-call gets actionable signal instead of noise."*

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

### Step 9 — CircleCI pipeline reference

Point to `.circleci/config.yml`. Walk through the 5 stages:

```
commit → lint-test → build (multi-arch amd64+arm64) → deploy-staging
       → smoke test → manual approval → promote-prod
```

**Key talking points:**
- Multi-arch build (`linux/amd64,linux/arm64`) — runs on both CI runners and M1 Macs
- `maxUnavailable: 0` in the K8s deployment = zero-downtime rolling updates
- Manual approval gate before prod = intentional, not reckless
- This supports **trunk-based development** → multiple deploys per day

**GitHub branching strategy** (they ask this in the JD):

> *Say: "Trunk-based development — main is always deployable, feature branches live less than 2 days, and feature flags control what users see rather than long-lived branches. GitFlow doesn't work for multiple deploys per day because long-lived branches create merge conflicts and slow release cadence."*

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

## Cheat sheet — interview answers

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
