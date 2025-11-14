# Docker Compose Healthchecks vs Kubernetes Probes: Migration Guide

**Research Date:** 2025-11-14 **Status:** Comprehensive migration and
compatibility guide **Audience:** DevOps engineers, Platform engineers, SREs

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Conceptual Differences](#conceptual-differences)
3. [Comparison Tables](#comparison-tables)
4. [Migration Mapping Guide](#migration-mapping-guide)
5. [Kubernetes Probe Types](#kubernetes-probe-types)
6. [Configuration Parameters](#configuration-parameters)
7. [Production Best Practices](#production-best-practices)
8. [Helm Chart Patterns](#helm-chart-patterns)
9. [Decision Framework](#decision-framework)
10. [Real-World Examples](#real-world-examples)
11. [Common Pitfalls](#common-pitfalls)
12. [References](#references)

---

## Executive Summary

### Critical Finding: Kubernetes Does NOT Use Docker HEALTHCHECK

**🚨 KEY INSIGHT:** Since Kubernetes 1.8, Docker HEALTHCHECK instructions are
**explicitly disabled** in Kubernetes. Kubernetes uses its own sophisticated
probe system instead.

**What This Means:**

- Dockerfile `HEALTHCHECK` instructions have **no effect** in Kubernetes
  clusters
- You must configure Kubernetes probes separately in pod/deployment manifests
- Docker Compose healthchecks and Kubernetes probes are **not interchangeable**
- Multi-platform deployments require separate healthcheck configurations

### Why Kubernetes Uses Its Own Probe System

Kubernetes probes are more sophisticated than Docker healthchecks:

- **3 probe types** (liveness, readiness, startup) vs Docker's single
  healthcheck
- **4 probe mechanisms** (HTTP, TCP, Exec, gRPC) vs Docker's command-based
  approach
- **Separate actions** based on probe type (restart vs remove from load
  balancer)
- **Production-scale features** (startup delays, failure thresholds, success
  thresholds)

---

## Conceptual Differences

### Docker HEALTHCHECK Philosophy

Docker healthchecks are **passive monitoring tools**:

- Single health check command per container
- Reports container health status in CLI/API
- **Does NOT automatically restart** unhealthy containers
- Simple binary state: healthy or unhealthy
- Useful for local development and Docker Swarm

**Docker Compose Example:**

```yaml
services:
  postgres:
    image: postgres:15
    healthcheck:
      test: ['CMD-SHELL', 'pg_isready -U postgres']
      interval: 5s
      timeout: 3s
      retries: 5
      start_period: 10s
```

### Kubernetes Probe Philosophy

Kubernetes probes are **active orchestration tools**:

- Three distinct probe types with different purposes
- Automatic remediation actions (restart, remove from service)
- Sophisticated state management (alive, ready, started)
- Production-scale features (gradual rollout, zero-downtime updates)
- Designed for distributed systems at scale

**Kubernetes Example:**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: postgres
spec:
  containers:
    - name: postgres
      image: postgres:15
      livenessProbe:
        exec:
          command:
            - pg_isready
            - -U
            - postgres
        initialDelaySeconds: 30
        periodSeconds: 10
        timeoutSeconds: 5
        failureThreshold: 3
      readinessProbe:
        exec:
          command:
            - pg_isready
            - -U
            - postgres
        initialDelaySeconds: 10
        periodSeconds: 5
        timeoutSeconds: 3
        failureThreshold: 2
```

---

## Comparison Tables

### Docker HEALTHCHECK vs Kubernetes Probes

| Feature                   | Docker HEALTHCHECK        | Kubernetes Probes                                   |
| ------------------------- | ------------------------- | --------------------------------------------------- |
| **Number of probe types** | 1 (single healthcheck)    | 3 (liveness, readiness, startup)                    |
| **Probe mechanisms**      | Command-based only        | HTTP, TCP, Exec, gRPC                               |
| **Automatic restart**     | ❌ No                     | ✅ Yes (liveness probe)                             |
| **Traffic management**    | ❌ No                     | ✅ Yes (readiness probe)                            |
| **Startup handling**      | ⚠️ Grace period only      | ✅ Dedicated startup probe                          |
| **Failure actions**       | Log status change         | Restart, remove from service, or delay other probes |
| **Success threshold**     | ❌ Not configurable       | ✅ Configurable (1-N consecutive successes)         |
| **Failure threshold**     | ✅ `retries` parameter    | ✅ `failureThreshold` parameter                     |
| **Works in Kubernetes**   | ❌ Disabled since K8s 1.8 | ✅ Native integration                               |
| **Use case**              | Local dev, Docker Swarm   | Production Kubernetes                               |

### Configuration Parameter Mapping

| Docker Compose | Kubernetes                             | Notes                                       |
| -------------- | -------------------------------------- | ------------------------------------------- |
| `test`         | `httpGet`, `tcpSocket`, `exec`, `grpc` | K8s supports multiple mechanisms            |
| `interval`     | `periodSeconds`                        | Same concept, different name                |
| `timeout`      | `timeoutSeconds`                       | Same concept, different name                |
| `retries`      | `failureThreshold`                     | Same concept, different name                |
| `start_period` | `initialDelaySeconds` + Startup Probe  | K8s has more sophisticated startup handling |
| N/A            | `successThreshold`                     | New in K8s: consecutive successes needed    |
| N/A            | Liveness vs Readiness                  | K8s separates concerns                      |

### Docker start_period vs Kubernetes Startup Probe

| Aspect            | Docker `start_period`               | Kubernetes Startup Probe                      |
| ----------------- | ----------------------------------- | --------------------------------------------- |
| **Approach**      | Passive grace period                | Active health verification                    |
| **Behavior**      | Ignores failures for N seconds      | Actively checks until success                 |
| **Other probes**  | Run concurrently (failures ignored) | Liveness/readiness **disabled** until success |
| **Flexibility**   | Fixed time window                   | Dynamic (succeeds when app is ready)          |
| **Configuration** | Single timeout value                | Full probe config (period, threshold, etc.)   |
| **Best for**      | Predictable startup times           | Variable startup times                        |

---

## Migration Mapping Guide

### Step 1: Identify Docker Compose Healthchecks

**Docker Compose Example:**

```yaml
version: '3.8'
services:
  web:
    image: nginx
    healthcheck:
      test: ['CMD', 'curl', '-f', 'http://localhost/health']
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

  db:
    image: postgres:15
    healthcheck:
      test: ['CMD-SHELL', 'pg_isready -U postgres']
      interval: 5s
      timeout: 3s
      retries: 5
      start_period: 10s
```

### Step 2: Translate to Kubernetes Probes

**Manual Translation (Recommended for Production):**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
spec:
  replicas: 1
  selector:
    matchLabels:
      app: web
  template:
    metadata:
      labels:
        app: web
    spec:
      containers:
        - name: web
          image: nginx
          ports:
            - containerPort: 80

          # Startup Probe (replaces start_period)
          startupProbe:
            httpGet:
              path: /health
              port: 80
            initialDelaySeconds: 0
            periodSeconds: 10
            timeoutSeconds: 10
            failureThreshold: 4 # 40s total: 10s * 4 attempts

          # Liveness Probe (detects crashes)
          livenessProbe:
            httpGet:
              path: /health
              port: 80
            initialDelaySeconds: 0
            periodSeconds: 30
            timeoutSeconds: 10
            failureThreshold: 3

          # Readiness Probe (manages traffic routing)
          readinessProbe:
            httpGet:
              path: /health
              port: 80
            initialDelaySeconds: 0
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 2
            successThreshold: 1

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: db
spec:
  replicas: 1
  selector:
    matchLabels:
      app: db
  template:
    metadata:
      labels:
        app: db
    spec:
      containers:
        - name: postgres
          image: postgres:15
          ports:
            - containerPort: 5432
          env:
            - name: POSTGRES_PASSWORD
              value: 'password'

          # Startup Probe (fast-starting DB)
          startupProbe:
            exec:
              command:
                - pg_isready
                - -U
                - postgres
            initialDelaySeconds: 0
            periodSeconds: 5
            timeoutSeconds: 3
            failureThreshold: 2 # 10s total: 5s * 2 attempts

          # Liveness Probe
          livenessProbe:
            exec:
              command:
                - pg_isready
                - -U
                - postgres
            initialDelaySeconds: 0
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3

          # Readiness Probe (strict for DB)
          readinessProbe:
            exec:
              command:
                - pg_isready
                - -U
                - postgres
            initialDelaySeconds: 0
            periodSeconds: 5
            timeoutSeconds: 3
            failureThreshold: 2
            successThreshold: 1
```

### Step 3: Using Kompose for Automatic Conversion

**Install Kompose:**

```bash
# macOS
brew install kompose

# Linux
curl -L https://github.com/kubernetes/kompose/releases/download/v1.34.0/kompose-linux-amd64 -o kompose
chmod +x kompose
sudo mv ./kompose /usr/local/bin/kompose

# Windows
choco install kubernetes-kompose
```

**Convert Docker Compose to Kubernetes:**

```bash
# Basic conversion
kompose convert -f docker-compose.yml

# Output to specific directory
kompose convert -f docker-compose.yml -o k8s/

# Generate Helm chart
kompose convert -f docker-compose.yml -c

# Verbose output (see healthcheck translation)
kompose convert -f docker-compose.yml --verbose
```

**⚠️ Kompose Limitations:**

- Generates **basic probes** that need manual refinement
- May not optimize probe parameters for your use case
- Doesn't separate liveness/readiness concerns optimally
- **Review and customize** generated manifests before production use

### Step 4: Refine Generated Probes

After Kompose conversion, refine probes based on:

1. **Application startup time**: Adjust `initialDelaySeconds` and startup probe
2. **Resource intensity**: Increase `timeoutSeconds` for heavy operations
3. **Criticality**: Adjust `failureThreshold` based on tolerance
4. **Load patterns**: Configure `periodSeconds` based on traffic

---

## Kubernetes Probe Types

### 1. Liveness Probe

**Purpose:** Determines if the container is **alive** and functioning.

**Action on Failure:** Kubernetes **kills and restarts** the container.

**Use Cases:**

- Detect application deadlocks (process running but not responding)
- Detect memory leaks causing application freeze
- Recover from fatal application errors
- Handle unrecoverable corruption

**When NOT to Use:**

- During normal startup (use startup probe instead)
- For transient errors (use readiness probe)
- For dependency failures (may cause restart loops)

**Example:**

```yaml
livenessProbe:
  httpGet:
    path: /healthz
    port: 8080
    httpHeaders:
      - name: X-Health-Check
        value: liveness
  initialDelaySeconds: 30
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3
  successThreshold: 1
```

### 2. Readiness Probe

**Purpose:** Determines if the container is **ready to accept traffic**.

**Action on Failure:** Kubernetes **removes pod from Service load balancer** (no
restart).

**Use Cases:**

- Waiting for database connections to be established
- Waiting for cache warmup
- Managing traffic during deployments
- Handling temporary overload (backpressure)
- Graceful degradation during dependency failures

**Key Difference from Liveness:**

- Readiness failures are **temporary** (pod may recover)
- Liveness failures are **permanent** (pod needs restart)

**Example:**

```yaml
readinessProbe:
  httpGet:
    path: /ready
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 5
  timeoutSeconds: 3
  failureThreshold: 2
  successThreshold: 1
```

### 3. Startup Probe

**Purpose:** Determines if the **application has started** successfully.

**Action on Failure:** Kubernetes **kills and restarts** the container after all
retries exhausted.

**Key Behavior:**

- Runs **ONLY during startup**
- **Disables** liveness and readiness probes until successful
- Once succeeds, **never runs again** for container lifetime

**Use Cases:**

- Slow-starting legacy applications
- Applications with unpredictable initialization times
- Applications loading large datasets on startup
- JVM applications with long warmup periods

**Example:**

```yaml
startupProbe:
  httpGet:
    path: /startup
    port: 8080
  initialDelaySeconds: 0
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 30 # 300s total (5 minutes)
  successThreshold: 1
```

**Startup Probe Best Practice:**

```yaml
# For slow-starting apps (up to 5 minutes)
startupProbe:
  httpGet:
    path: /healthz
    port: 8080
  periodSeconds: 10
  failureThreshold: 30 # 300s = 10s * 30

# Fast liveness probe (after startup)
livenessProbe:
  httpGet:
    path: /healthz
    port: 8080
  periodSeconds: 10
  failureThreshold: 3 # 30s = 10s * 3
```

---

## Kubernetes Probe Mechanisms

### 1. HTTP Probe (httpGet)

**Most Common:** Best for web applications with HTTP endpoints.

**Configuration:**

```yaml
livenessProbe:
  httpGet:
    path: /healthz # Endpoint path
    port: 8080 # Port (number or name)
    host: 127.0.0.1 # Optional (defaults to pod IP)
    scheme: HTTP # HTTP or HTTPS
    httpHeaders: # Optional custom headers
      - name: X-Custom-Header
        value: Health-Check
  initialDelaySeconds: 30
  periodSeconds: 10
```

**Success Criteria:** HTTP status code **2xx or 3xx**

**Best Practices:**

- ✅ Use dedicated `/health`, `/ready`, `/healthz` endpoints
- ✅ Return 200 for healthy, 503 for unhealthy
- ✅ Include dependency checks in readiness endpoint
- ✅ Keep liveness endpoint lightweight (no DB queries)
- ❌ Don't reuse application endpoints (e.g., `/api/users`)

### 2. TCP Probe (tcpSocket)

**Simple:** Checks if a TCP connection can be established.

**Configuration:**

```yaml
livenessProbe:
  tcpSocket:
    port: 5432
  initialDelaySeconds: 15
  periodSeconds: 10
```

**Success Criteria:** TCP connection successfully opened.

**Use Cases:**

- Databases (MySQL, PostgreSQL, Redis)
- Message queues (RabbitMQ, Kafka)
- TCP-based services without HTTP

**⚠️ Limitations:**

- **Least informative** probe type
- Only checks port is open, not application health
- Can't verify application logic is working
- **Not recommended for gRPC** services

**When to Use:**

- No HTTP endpoint available
- Application doesn't support custom health checks
- Simple "is the port open?" verification needed

### 3. Exec Probe

**Most Flexible:** Runs a command inside the container.

**Configuration:**

```yaml
livenessProbe:
  exec:
    command:
      - cat
      - /tmp/healthy
  initialDelaySeconds: 5
  periodSeconds: 5
```

**Success Criteria:** Command exits with status code **0**.

**Use Cases:**

- Custom health check logic
- Applications without network endpoints
- File-based health checks
- Legacy applications

**Best Practices:**

- ✅ Use lightweight commands (avoid heavy scripts)
- ✅ Ensure command is available in container
- ✅ Return 0 for success, non-zero for failure
- ❌ Avoid long-running commands (use `timeoutSeconds`)

**Example: PostgreSQL**

```yaml
livenessProbe:
  exec:
    command:
      - pg_isready
      - -U
      - postgres
      - -d
      - mydb
  initialDelaySeconds: 30
  periodSeconds: 10
  timeoutSeconds: 5
```

**Example: Redis**

```yaml
livenessProbe:
  exec:
    command:
      - redis-cli
      - ping
  initialDelaySeconds: 30
  periodSeconds: 10
```

**⚠️ Performance Considerations:**

- Exec probes are **slower** than HTTP/TCP (spawn new process)
- Can fail when pod is at **maximum resource limits**
- Use HTTP probes when possible for better performance

### 4. gRPC Probe

**Modern:** Native gRPC health checking (Kubernetes 1.27+ GA).

**Configuration:**

```yaml
livenessProbe:
  grpc:
    port: 9090
    service: my.service.v1.Health # Optional
  initialDelaySeconds: 10
  periodSeconds: 10
```

**Success Criteria:** gRPC health check returns `SERVING` status.

**Requirements:**

- Kubernetes 1.24+ (beta), 1.27+ (GA)
- Application must implement
  [gRPC Health Checking Protocol](https://github.com/grpc/grpc/blob/master/doc/health-checking.md)

**Use Cases:**

- Microservices using gRPC
- High-performance applications
- Modern cloud-native apps

**Advantages:**

- Native gRPC support (no HTTP shim needed)
- More efficient than HTTP for gRPC services
- Application-aware health checking

**Example Implementation (Go):**

```go
import "google.golang.org/grpc/health/grpc_health_v1"

// Implement health check service
type healthServer struct {
    grpc_health_v1.UnimplementedHealthServer
}

func (s *healthServer) Check(ctx context.Context, in *grpc_health_v1.HealthCheckRequest) (*grpc_health_v1.HealthCheckResponse, error) {
    return &grpc_health_v1.HealthCheckResponse{
        Status: grpc_health_v1.HealthCheckResponse_SERVING,
    }, nil
}
```

---

## Configuration Parameters

### Complete Parameter Reference

| Parameter             | Type | Default | Min | Purpose                                               |
| --------------------- | ---- | ------- | --- | ----------------------------------------------------- |
| `initialDelaySeconds` | int  | 0       | 0   | Seconds after container starts before probe begins    |
| `periodSeconds`       | int  | 10      | 1   | How often to perform probe                            |
| `timeoutSeconds`      | int  | 1       | 1   | Seconds after which probe times out                   |
| `successThreshold`    | int  | 1       | 1   | Consecutive successes needed (must be 1 for liveness) |
| `failureThreshold`    | int  | 3       | 1   | Consecutive failures before action taken              |

### Parameter Deep Dive

#### initialDelaySeconds

**Purpose:** Delay before first probe execution.

**Best Practices:**

- **Startup probe:** Set to `0` (probe handles delays via `failureThreshold`)
- **Liveness probe:** Set to `0` if using startup probe, else use p99 startup
  time
- **Readiness probe:** Set to `0` or small value (5-10s)

**Example:**

```yaml
# With startup probe: No delay needed
startupProbe:
  httpGet:
    path: /healthz
    port: 8080
  initialDelaySeconds: 0
  periodSeconds: 10
  failureThreshold: 30 # Provides up to 300s for startup

livenessProbe:
  httpGet:
    path: /healthz
    port: 8080
  initialDelaySeconds: 0 # No delay; startup probe handles it
  periodSeconds: 10
```

#### periodSeconds

**Purpose:** How often to execute probe.

**Best Practices:**

- **Critical apps:** 5-10s (faster detection)
- **Normal apps:** 10-15s (balanced)
- **Low-priority apps:** 20-30s (lower overhead)

**Trade-offs:**

- Shorter periods = faster failure detection + higher overhead
- Longer periods = lower overhead + slower failure detection

**Example:**

```yaml
# Critical payment service
livenessProbe:
  periodSeconds: 5  # Check every 5s

# Background job processor
livenessProbe:
  periodSeconds: 30  # Check every 30s
```

#### timeoutSeconds

**Purpose:** Maximum time to wait for probe response.

**⚠️ Common Mistake:** Default is only **1 second** (often too short for
production).

**Best Practices:**

- **Fast endpoints:** 2-3s
- **Database queries:** 5-10s
- **Heavy operations:** 10-15s
- **Always test** under load to find realistic timeout

**Example:**

```yaml
# Lightweight health endpoint
readinessProbe:
  httpGet:
    path: /ready
    port: 8080
  timeoutSeconds: 3

# Database readiness check
readinessProbe:
  exec:
    command: ["pg_isready", "-U", "postgres"]
  timeoutSeconds: 5
```

#### successThreshold

**Purpose:** Consecutive successes needed before marking healthy.

**Restrictions:**

- **Must be 1** for liveness and startup probes
- Can be **1-N** for readiness probes

**Use Cases:**

- **Readiness:** Set to 2-3 to avoid flapping during intermittent issues
- **Liveness:** Always 1 (no choice)

**Example:**

```yaml
readinessProbe:
  httpGet:
    path: /ready
    port: 8080
  successThreshold: 2 # Must succeed 2 times before accepting traffic
  failureThreshold: 3 # Can fail 3 times before removing from service
```

#### failureThreshold

**Purpose:** Consecutive failures before taking action.

**Actions:**

- **Liveness:** Restart container after threshold reached
- **Readiness:** Remove from service after threshold reached
- **Startup:** Restart container after threshold reached

**Best Practices:**

- **Critical services:** 2-3 (fast recovery)
- **Normal services:** 3-5 (tolerate transient issues)
- **Tolerant services:** 5-10 (avoid unnecessary restarts)

**Calculation:**

```
Total time before action = periodSeconds × failureThreshold

Example:
periodSeconds: 10
failureThreshold: 3
Total: 30 seconds before restart
```

**Example:**

```yaml
# Fast failure detection (30s)
livenessProbe:
  periodSeconds: 10
  failureThreshold: 3

# Tolerant of transient issues (60s)
livenessProbe:
  periodSeconds: 10
  failureThreshold: 6
```

---

## Production Best Practices

### 1. Always Use All Three Probe Types

**Recommended Pattern:**

```yaml
containers:
  - name: app
    image: myapp:1.0

    # 1. Startup Probe (handles slow startup)
    startupProbe:
      httpGet:
        path: /healthz
        port: 8080
      periodSeconds: 10
      failureThreshold: 30 # Up to 5 minutes for startup

    # 2. Liveness Probe (detects deadlocks)
    livenessProbe:
      httpGet:
        path: /healthz
        port: 8080
      periodSeconds: 10
      failureThreshold: 3 # 30s before restart

    # 3. Readiness Probe (manages traffic)
    readinessProbe:
      httpGet:
        path: /ready
        port: 8080
      periodSeconds: 5
      failureThreshold: 2 # 10s before removing from service
      successThreshold: 1
```

### 2. Use Dedicated Health Endpoints

**❌ Bad: Reusing application endpoints**

```yaml
livenessProbe:
  httpGet:
    path: /api/users # DON'T: Application endpoint
    port: 8080
```

**✅ Good: Dedicated health endpoints**

```yaml
livenessProbe:
  httpGet:
    path: /healthz # Lightweight, no DB queries
    port: 8080

readinessProbe:
  httpGet:
    path: /ready # Checks DB, cache, dependencies
    port: 8080
```

**Endpoint Design:**

**`/healthz` (Liveness):**

- Returns 200 if application process is alive
- **No external dependencies** (no DB, no Redis, no API calls)
- Checks internal state only (memory, goroutines, threads)
- Responds in <100ms

**`/ready` (Readiness):**

- Returns 200 if ready to serve traffic
- **Checks all dependencies** (DB, cache, external APIs)
- May take longer (500ms-2s acceptable)
- Returns 503 if any dependency unavailable

### 3. Configure Based on Application Metrics

**Don't guess - measure!**

```yaml
# ❌ Bad: Default/guessed values
livenessProbe:
  httpGet:
    path: /healthz
    port: 8080
  initialDelaySeconds: 30  # Guessed
  periodSeconds: 10
  timeoutSeconds: 1        # Too short!
  failureThreshold: 3

# ✅ Good: Values based on real metrics
livenessProbe:
  httpGet:
    path: /healthz
    port: 8080
  initialDelaySeconds: 0                # Using startup probe
  periodSeconds: 10
  timeoutSeconds: 5                     # Measured p99: 2s, buffer: 3s
  failureThreshold: 3                   # Measured MTTR: 25s, allow 30s
```

**Metrics to Collect:**

- p50, p95, p99 startup times
- p50, p95, p99 health endpoint response times
- Mean time to recovery (MTTR) from failures
- Resource usage during health checks

### 4. Avoid Heavy Operations in Health Checks

**❌ Bad: Heavy operations**

```go
// DON'T: Full database query
func healthHandler(w http.ResponseWriter, r *http.Request) {
    rows, err := db.Query("SELECT COUNT(*) FROM users")  // Heavy!
    if err != nil {
        w.WriteHeader(503)
        return
    }
    w.WriteHeader(200)
}
```

**✅ Good: Lightweight checks**

```go
// Liveness: Just check if alive
func livenessHandler(w http.ResponseWriter, r *http.Request) {
    w.WriteHeader(200)
    w.Write([]byte("OK"))
}

// Readiness: Ping dependencies
func readinessHandler(w http.ResponseWriter, r *http.Request) {
    // Quick ping, not full query
    if err := db.Ping(); err != nil {
        w.WriteHeader(503)
        return
    }
    if err := redisClient.Ping().Err(); err != nil {
        w.WriteHeader(503)
        return
    }
    w.WriteHeader(200)
}
```

### 5. Adjust Probes Based on Criticality

**Critical Service (Payment Processing):**

```yaml
livenessProbe:
  httpGet:
    path: /healthz
    port: 8080
  periodSeconds: 5 # Check often
  timeoutSeconds: 3
  failureThreshold: 2 # Fail fast

readinessProbe:
  httpGet:
    path: /ready
    port: 8080
  periodSeconds: 3 # Very frequent
  timeoutSeconds: 2
  failureThreshold: 2 # Strict
  successThreshold: 2 # Require 2 successes
```

**Non-Critical Service (Logging):**

```yaml
livenessProbe:
  httpGet:
    path: /healthz
    port: 8080
  periodSeconds: 30 # Check less often
  timeoutSeconds: 10
  failureThreshold: 6 # Tolerate more failures

readinessProbe:
  httpGet:
    path: /ready
    port: 8080
  periodSeconds: 15
  timeoutSeconds: 5
  failureThreshold: 4 # More lenient
  successThreshold: 1
```

### 6. Probe Configuration by Application Type

**Fast Web Application (Node.js, Go):**

```yaml
startupProbe:
  httpGet:
    path: /healthz
    port: 8080
  periodSeconds: 5
  failureThreshold: 6 # 30s startup time

livenessProbe:
  httpGet:
    path: /healthz
    port: 8080
  periodSeconds: 10
  timeoutSeconds: 3
  failureThreshold: 3
```

**Slow JVM Application:**

```yaml
startupProbe:
  httpGet:
    path: /healthz
    port: 8080
  periodSeconds: 10
  failureThreshold: 60 # 10 minutes startup time

livenessProbe:
  httpGet:
    path: /healthz
    port: 8080
  periodSeconds: 15
  timeoutSeconds: 10 # JVM GC pauses
  failureThreshold: 5
```

**Database (PostgreSQL):**

```yaml
startupProbe:
  exec:
    command: ['pg_isready', '-U', 'postgres']
  periodSeconds: 5
  failureThreshold: 10 # 50s startup

livenessProbe:
  exec:
    command: ['pg_isready', '-U', 'postgres']
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3

readinessProbe:
  exec:
    command: ['psql', '-U', 'postgres', '-c', 'SELECT 1']
  periodSeconds: 5
  timeoutSeconds: 3
  failureThreshold: 2
```

### 7. Monitor and Update Probes

**Continuous improvement process:**

1. **Collect metrics** (Prometheus, Datadog, etc.)
2. **Analyze failures** (are restarts legitimate?)
3. **Adjust parameters** based on real-world data
4. **A/B test** changes in staging
5. **Gradually roll out** to production

**Prometheus Metrics to Monitor:**

```yaml
# Probe failures
kube_pod_container_status_restarts_total
kube_pod_status_ready

# Probe execution time
kubelet_http_requests_duration_seconds{handler="probes"}
```

### 8. Avoid Common Anti-Patterns

**❌ Anti-Pattern 1: Same probe for liveness and readiness**

```yaml
# DON'T: Restarting pod for dependency failure
livenessProbe:
  exec:
    command: ['check-db-connection'] # Will restart pod if DB is down!
```

**✅ Correct: Separate concerns**

```yaml
livenessProbe:
  httpGet:
    path: /healthz # Check app is alive (no external deps)

readinessProbe:
  httpGet:
    path: /ready # Check dependencies (DB, cache)
```

**❌ Anti-Pattern 2: No startup probe for slow apps**

```yaml
# DON'T: Long initialDelaySeconds
livenessProbe:
  httpGet:
    path: /healthz
    port: 8080
  initialDelaySeconds: 180 # 3 minutes delay - wasteful!
  periodSeconds: 10
  failureThreshold: 3
```

**✅ Correct: Use startup probe**

```yaml
startupProbe:
  httpGet:
    path: /healthz
    port: 8080
  periodSeconds: 10
  failureThreshold: 18 # Up to 3 minutes

livenessProbe:
  httpGet:
    path: /healthz
    port: 8080
  periodSeconds: 10
  failureThreshold: 3 # 30s after startup completes
```

---

## Helm Chart Patterns

### 1. Basic Helm Chart Template

**`templates/deployment.yaml`:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "app.fullname" . }}
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      {{- include "app.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "app.selectorLabels" . | nindent 8 }}
    spec:
      containers:
      - name: {{ .Chart.Name }}
        image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
        ports:
        - name: http
          containerPort: {{ .Values.service.port }}
          protocol: TCP

        {{- if .Values.probes.liveness.enabled }}
        livenessProbe:
          {{- toYaml .Values.probes.liveness.config | nindent 10 }}
        {{- end }}

        {{- if .Values.probes.readiness.enabled }}
        readinessProbe:
          {{- toYaml .Values.probes.readiness.config | nindent 10 }}
        {{- end }}

        {{- if .Values.probes.startup.enabled }}
        startupProbe:
          {{- toYaml .Values.probes.startup.config | nindent 10 }}
        {{- end }}
```

**`values.yaml`:**

```yaml
replicaCount: 1

image:
  repository: myapp
  tag: '1.0.0'
  pullPolicy: IfNotPresent

service:
  port: 8080

probes:
  liveness:
    enabled: true
    config:
      httpGet:
        path: /healthz
        port: http
      initialDelaySeconds: 0
      periodSeconds: 10
      timeoutSeconds: 5
      failureThreshold: 3
      successThreshold: 1

  readiness:
    enabled: true
    config:
      httpGet:
        path: /ready
        port: http
      initialDelaySeconds: 0
      periodSeconds: 5
      timeoutSeconds: 3
      failureThreshold: 2
      successThreshold: 1

  startup:
    enabled: true
    config:
      httpGet:
        path: /healthz
        port: http
      initialDelaySeconds: 0
      periodSeconds: 10
      timeoutSeconds: 5
      failureThreshold: 30
      successThreshold: 1
```

### 2. Named Templates for Reusability

**`templates/_healthchecks.tpl`:**

```yaml
{{/*
Standard HTTP liveness probe
*/}}
{{- define "app.livenessProbe.http" -}}
httpGet:
  path: {{ .path | default "/healthz" }}
  port: {{ .port | default "http" }}
  scheme: {{ .scheme | default "HTTP" }}
initialDelaySeconds: {{ .initialDelaySeconds | default 0 }}
periodSeconds: {{ .periodSeconds | default 10 }}
timeoutSeconds: {{ .timeoutSeconds | default 5 }}
failureThreshold: {{ .failureThreshold | default 3 }}
successThreshold: 1
{{- end }}

{{/*
Standard HTTP readiness probe
*/}}
{{- define "app.readinessProbe.http" -}}
httpGet:
  path: {{ .path | default "/ready" }}
  port: {{ .port | default "http" }}
  scheme: {{ .scheme | default "HTTP" }}
initialDelaySeconds: {{ .initialDelaySeconds | default 0 }}
periodSeconds: {{ .periodSeconds | default 5 }}
timeoutSeconds: {{ .timeoutSeconds | default 3 }}
failureThreshold: {{ .failureThreshold | default 2 }}
successThreshold: {{ .successThreshold | default 1 }}
{{- end }}

{{/*
Standard exec probe for databases
*/}}
{{- define "app.livenessProbe.exec" -}}
exec:
  command:
  {{- range .command }}
  - {{ . }}
  {{- end }}
initialDelaySeconds: {{ .initialDelaySeconds | default 30 }}
periodSeconds: {{ .periodSeconds | default 10 }}
timeoutSeconds: {{ .timeoutSeconds | default 5 }}
failureThreshold: {{ .failureThreshold | default 3 }}
successThreshold: 1
{{- end }}
```

**Usage in `templates/deployment.yaml`:**

```yaml
livenessProbe:
  {
    {
      - include "app.livenessProbe.http" (dict "path" "/health" "port" "http") |
      nindent 10,
    },
  }

readinessProbe:
  {
    {
      - include "app.readinessProbe.http" (dict "path" "/ready" "port" "http") |
      nindent 10,
    },
  }
```

### 3. Environment-Specific Overrides

**`values-production.yaml`:**

```yaml
probes:
  liveness:
    enabled: true
    config:
      httpGet:
        path: /healthz
        port: http
      periodSeconds: 5 # More frequent in prod
      timeoutSeconds: 3
      failureThreshold: 2 # Fail faster in prod

  readiness:
    enabled: true
    config:
      httpGet:
        path: /ready
        port: http
      periodSeconds: 3 # Very frequent in prod
      timeoutSeconds: 2
      failureThreshold: 2
      successThreshold: 2 # Stricter in prod
```

**`values-development.yaml`:**

```yaml
probes:
  liveness:
    enabled: true
    config:
      httpGet:
        path: /healthz
        port: http
      periodSeconds: 30 # Less frequent in dev
      timeoutSeconds: 10
      failureThreshold: 5 # More lenient in dev

  readiness:
    enabled: false # Disable in dev for faster iteration
```

**Deploy to environment:**

```bash
# Production
helm install myapp ./chart -f values-production.yaml

# Development
helm install myapp ./chart -f values-development.yaml
```

### 4. Per-Service Customization

**Multi-service chart with different probe needs:**

**`values.yaml`:**

```yaml
services:
  web:
    probes:
      liveness:
        httpGet:
          path: /healthz
          port: 8080
        periodSeconds: 10
        failureThreshold: 3
      readiness:
        httpGet:
          path: /ready
          port: 8080
        periodSeconds: 5
        failureThreshold: 2

  worker:
    probes:
      liveness:
        exec:
          command:
            - pgrep
            - worker
        periodSeconds: 30
        failureThreshold: 5
      readiness:
        enabled: false # Workers don't receive traffic

  database:
    probes:
      liveness:
        exec:
          command:
            - pg_isready
            - -U
            - postgres
        periodSeconds: 10
        timeoutSeconds: 5
        failureThreshold: 3
      readiness:
        tcpSocket:
          port: 5432
        periodSeconds: 5
        failureThreshold: 2
```

---

## Decision Framework

### When to Use Each Probe Type

```
┌─────────────────────────────────────────────────────────────────┐
│                   PROBE TYPE DECISION TREE                      │
└─────────────────────────────────────────────────────────────────┘

Does your app have a long/variable startup time?
├─ YES → Use STARTUP PROBE
│   └─ Configure: periodSeconds * failureThreshold = max startup time
└─ NO → Skip startup probe, use initialDelaySeconds on liveness

Can your app deadlock/hang while process is still running?
├─ YES → Use LIVENESS PROBE
│   └─ Action: Restart container on failure
└─ NO → Consider if you still want crash detection

Does your app depend on external services (DB, cache, APIs)?
├─ YES → Use READINESS PROBE
│   └─ Action: Remove from service, don't restart
└─ NO → Still use readiness for zero-downtime deployments

Does your app receive traffic from a Kubernetes Service?
├─ YES → Use READINESS PROBE (required)
│   └─ Manages traffic routing
└─ NO (e.g., cron job) → Readiness probe optional
```

### When to Use Each Probe Mechanism

```
┌─────────────────────────────────────────────────────────────────┐
│                 PROBE MECHANISM DECISION TREE                   │
└─────────────────────────────────────────────────────────────────┘

Does your app expose an HTTP API?
├─ YES → Use HTTP PROBE (most common)
│   └─ Advantages: Easy to implement, rich status codes
└─ NO → Continue

Does your app use gRPC?
├─ YES → Use gRPC PROBE (Kubernetes 1.27+)
│   └─ Advantages: Native gRPC, no HTTP shim needed
└─ NO → Continue

Does your app listen on a TCP port?
├─ YES → Use TCP PROBE
│   └─ Advantages: Simple, works for any TCP service
│   └─ Disadvantages: Least informative (only checks port open)
└─ NO → Continue

Can you run a command in the container?
└─ YES → Use EXEC PROBE
    └─ Advantages: Most flexible, custom logic
    └─ Disadvantages: Slower (spawns process), higher overhead
```

### Probe Configuration Decision Matrix

| Scenario                            | Startup Probe               | Liveness Probe | Readiness Probe |
| ----------------------------------- | --------------------------- | -------------- | --------------- |
| **Fast-starting stateless web app** | Optional (or short timeout) | ✅ Required    | ✅ Required     |
| **Slow-starting JVM application**   | ✅ Required (long timeout)  | ✅ Required    | ✅ Required     |
| **Stateless worker (no traffic)**   | Optional                    | ✅ Required    | ❌ Not needed   |
| **Stateful database**               | ✅ Required                 | ✅ Required    | ✅ Required     |
| **Batch job (CronJob)**             | Optional                    | Optional       | ❌ Not needed   |
| **Sidecar (logging, monitoring)**   | Optional                    | ✅ Required    | ❌ Not needed   |

### Threshold Configuration Guide

| Application Type                | failureThreshold | periodSeconds | Total Time Before Action |
| ------------------------------- | ---------------- | ------------- | ------------------------ |
| **Critical (payment, auth)**    | 2                | 5s            | 10s (fail fast)          |
| **Normal (web app, API)**       | 3                | 10s           | 30s (balanced)           |
| **Tolerant (batch, analytics)** | 5-6              | 15s           | 75-90s (lenient)         |
| **Database**                    | 3                | 10s           | 30s                      |
| **Cache (Redis, Memcached)**    | 3                | 5s            | 15s                      |

### Timeout Configuration Guide

| Operation Type                | Recommended timeoutSeconds | Rationale                    |
| ----------------------------- | -------------------------- | ---------------------------- |
| **Lightweight HTTP /healthz** | 2-3s                       | Fast check, no external deps |
| **HTTP /ready with deps**     | 5-10s                      | Includes DB/cache pings      |
| **Database query**            | 5-10s                      | Network + query execution    |
| **Redis/Memcached**           | 2-3s                       | Should be very fast          |
| **External API call**         | 5-15s                      | Depends on SLA               |
| **File system check**         | 1-2s                       | Local operation              |

---

## Real-World Examples

### Example 1: Next.js Web Application

**Scenario:** Fast-starting web app with database dependency.

**`deployment.yaml`:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nextjs-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: nextjs-app
  template:
    metadata:
      labels:
        app: nextjs-app
    spec:
      containers:
        - name: nextjs
          image: nextjs-app:1.0.0
          ports:
            - name: http
              containerPort: 3000
          env:
            - name: DATABASE_URL
              value: 'postgresql://user:pass@db:5432/app'

          # Startup: Handles initial DB connection
          startupProbe:
            httpGet:
              path: /api/health
              port: http
            initialDelaySeconds: 0
            periodSeconds: 5
            timeoutSeconds: 3
            failureThreshold: 12 # Up to 60s for startup
            successThreshold: 1

          # Liveness: Detects app deadlocks (no DB check)
          livenessProbe:
            httpGet:
              path: /api/health
              port: http
            initialDelaySeconds: 0
            periodSeconds: 10
            timeoutSeconds: 3
            failureThreshold: 3

          # Readiness: Manages traffic (checks DB connection)
          readinessProbe:
            httpGet:
              path: /api/ready
              port: http
            initialDelaySeconds: 0
            periodSeconds: 5
            timeoutSeconds: 5
            failureThreshold: 2
            successThreshold: 1
```

**Health endpoints:**

```typescript
// pages/api/health.ts (liveness)
export default function handler(req, res) {
  // Lightweight check - no DB queries
  res.status(200).json({ status: 'ok' });
}

// pages/api/ready.ts (readiness)
import { db } from '@/lib/db';

export default async function handler(req, res) {
  try {
    // Check database connection
    await db.raw('SELECT 1');
    res.status(200).json({ status: 'ready', database: 'connected' });
  } catch (error) {
    res.status(503).json({ status: 'not ready', database: 'disconnected' });
  }
}
```

### Example 2: Go Microservice with gRPC

**Scenario:** High-performance gRPC service with multiple dependencies.

**`deployment.yaml`:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: grpc-service
spec:
  replicas: 5
  selector:
    matchLabels:
      app: grpc-service
  template:
    metadata:
      labels:
        app: grpc-service
    spec:
      containers:
        - name: service
          image: grpc-service:2.1.0
          ports:
            - name: grpc
              containerPort: 9090
            - name: metrics
              containerPort: 8080

          # Startup: Fast-starting Go app
          startupProbe:
            grpc:
              port: 9090
            initialDelaySeconds: 0
            periodSeconds: 5
            timeoutSeconds: 2
            failureThreshold: 6 # 30s max startup

          # Liveness: gRPC health check
          livenessProbe:
            grpc:
              port: 9090
            initialDelaySeconds: 0
            periodSeconds: 10
            timeoutSeconds: 3
            failureThreshold: 3

          # Readiness: HTTP endpoint checking dependencies
          readinessProbe:
            httpGet:
              path: /ready
              port: metrics
            initialDelaySeconds: 0
            periodSeconds: 5
            timeoutSeconds: 5
            failureThreshold: 2
```

**Go implementation:**

```go
package main

import (
    "context"
    "net/http"

    "google.golang.org/grpc/health/grpc_health_v1"
)

// gRPC health check (for liveness)
type healthServer struct {
    grpc_health_v1.UnimplementedHealthServer
}

func (s *healthServer) Check(ctx context.Context, in *grpc_health_v1.HealthCheckRequest) (*grpc_health_v1.HealthCheckResponse, error) {
    return &grpc_health_v1.HealthCheckResponse{
        Status: grpc_health_v1.HealthCheckResponse_SERVING,
    }, nil
}

// HTTP readiness check (checks dependencies)
func readyHandler(w http.ResponseWriter, r *http.Request) {
    // Check database
    if err := db.Ping(); err != nil {
        w.WriteHeader(http.StatusServiceUnavailable)
        w.Write([]byte(`{"status":"not ready","database":"down"}`))
        return
    }

    // Check Redis
    if err := redisClient.Ping().Err(); err != nil {
        w.WriteHeader(http.StatusServiceUnavailable)
        w.Write([]byte(`{"status":"not ready","redis":"down"}`))
        return
    }

    w.WriteHeader(http.StatusOK)
    w.Write([]byte(`{"status":"ready"}`))
}
```

### Example 3: PostgreSQL StatefulSet

**Scenario:** Stateful database with slow startup and complex readiness.

**`statefulset.yaml`:**

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
spec:
  serviceName: postgres
  replicas: 3
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
        - name: postgres
          image: postgres:15
          ports:
            - name: postgres
              containerPort: 5432
          env:
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: postgres-secret
                  key: password
            - name: PGDATA
              value: /var/lib/postgresql/data/pgdata

          # Startup: Database initialization can be slow
          startupProbe:
            exec:
              command:
                - /bin/sh
                - -c
                - pg_isready -U postgres
            initialDelaySeconds: 10
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 30 # Up to 5 minutes for initialization

          # Liveness: Check if Postgres is accepting connections
          livenessProbe:
            exec:
              command:
                - /bin/sh
                - -c
                - pg_isready -U postgres
            initialDelaySeconds: 0
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3

          # Readiness: Verify can execute queries
          readinessProbe:
            exec:
              command:
                - /bin/sh
                - -c
                - |
                  pg_isready -U postgres &&
                  psql -U postgres -c 'SELECT 1' > /dev/null
            initialDelaySeconds: 5
            periodSeconds: 5
            timeoutSeconds: 3
            failureThreshold: 2

          volumeMounts:
            - name: data
              mountPath: /var/lib/postgresql/data

  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ['ReadWriteOnce']
        resources:
          requests:
            storage: 10Gi
```

### Example 4: Java Spring Boot Application

**Scenario:** Slow-starting JVM app with Spring Boot Actuator.

**`deployment.yaml`:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: spring-app
spec:
  replicas: 2
  selector:
    matchLabels:
      app: spring-app
  template:
    metadata:
      labels:
        app: spring-app
    spec:
      containers:
        - name: spring
          image: spring-app:1.0.0
          ports:
            - name: http
              containerPort: 8080
          env:
            - name: JAVA_OPTS
              value: '-Xms512m -Xmx2g'

          # Startup: JVM takes 2-3 minutes to start
          startupProbe:
            httpGet:
              path: /actuator/health/liveness
              port: http
            initialDelaySeconds: 30
            periodSeconds: 10
            timeoutSeconds: 10
            failureThreshold: 18 # Up to 3 minutes (10s * 18)

          # Liveness: Spring Boot Actuator liveness
          livenessProbe:
            httpGet:
              path: /actuator/health/liveness
              port: http
            initialDelaySeconds: 0
            periodSeconds: 15
            timeoutSeconds: 10 # Allow for GC pauses
            failureThreshold: 5 # 75s before restart (tolerant of GC)

          # Readiness: Spring Boot Actuator readiness
          readinessProbe:
            httpGet:
              path: /actuator/health/readiness
              port: http
            initialDelaySeconds: 0
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3
            successThreshold: 1

          resources:
            requests:
              memory: '512Mi'
              cpu: '250m'
            limits:
              memory: '2Gi'
              cpu: '1000m'
```

**Spring Boot configuration:**

```yaml
# application.yml
management:
  endpoint:
    health:
      probes:
        enabled: true
      show-details: always
  health:
    livenessState:
      enabled: true
    readinessState:
      enabled: true
```

### Example 5: Python FastAPI with Redis

**Scenario:** Python API with Redis cache dependency.

**`deployment.yaml`:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: fastapi-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: fastapi-app
  template:
    metadata:
      labels:
        app: fastapi-app
    spec:
      containers:
        - name: api
          image: fastapi-app:1.0.0
          ports:
            - name: http
              containerPort: 8000
          env:
            - name: REDIS_URL
              value: 'redis://redis:6379'

          # Startup: Python starts quickly
          startupProbe:
            httpGet:
              path: /health
              port: http
            initialDelaySeconds: 0
            periodSeconds: 5
            timeoutSeconds: 3
            failureThreshold: 12 # 60s max

          # Liveness: Check API is responding
          livenessProbe:
            httpGet:
              path: /health
              port: http
            initialDelaySeconds: 0
            periodSeconds: 10
            timeoutSeconds: 3
            failureThreshold: 3

          # Readiness: Check Redis connection
          readinessProbe:
            httpGet:
              path: /ready
              port: http
            initialDelaySeconds: 0
            periodSeconds: 5
            timeoutSeconds: 5
            failureThreshold: 2
```

**FastAPI implementation:**

```python
from fastapi import FastAPI, status
from redis import Redis
import os

app = FastAPI()
redis = Redis.from_url(os.getenv("REDIS_URL"))

@app.get("/health")
async def health():
    """Liveness probe - lightweight check"""
    return {"status": "ok"}

@app.get("/ready")
async def ready():
    """Readiness probe - check dependencies"""
    try:
        # Check Redis connection
        redis.ping()
        return {"status": "ready", "redis": "connected"}
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not ready", "redis": "disconnected", "error": str(e)}
        )
```

---

## Common Pitfalls

### 1. Using Docker HEALTHCHECK in Kubernetes

**❌ Problem:**

```dockerfile
# Dockerfile
FROM node:20
WORKDIR /app
COPY . .
RUN npm install

HEALTHCHECK --interval=30s --timeout=3s \
  CMD curl -f http://localhost:3000/health || exit 1

CMD ["npm", "start"]
```

**Why it's wrong:**

- Kubernetes **ignores** Docker HEALTHCHECK since v1.8
- No effect on pod lifecycle
- Wastes image build time

**✅ Solution:** Remove Docker HEALTHCHECK, configure Kubernetes probes instead.

### 2. Not Separating Liveness and Readiness

**❌ Problem:**

```yaml
# Using same endpoint that checks database
livenessProbe:
  httpGet:
    path: /ready # Checks DB connection
    port: 8080
```

**Why it's wrong:**

- Database outage causes liveness failure
- Pod gets restarted unnecessarily
- Creates cascading failures

**✅ Solution:**

```yaml
# Liveness: Only check app is alive
livenessProbe:
  httpGet:
    path: /healthz # No external dependencies
    port: 8080

# Readiness: Check dependencies
readinessProbe:
  httpGet:
    path: /ready # Checks DB, cache, etc.
    port: 8080
```

### 3. Default Timeout Too Short

**❌ Problem:**

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8080
  # timeoutSeconds: 1  (default - TOO SHORT!)
```

**Why it's wrong:**

- Default 1s timeout often insufficient
- False positives during load
- Unnecessary pod restarts

**✅ Solution:**

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8080
  timeoutSeconds: 5 # Realistic timeout based on testing
```

### 4. No Startup Probe for Slow Apps

**❌ Problem:**

```yaml
# JVM app takes 3 minutes to start
livenessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 180 # Wasteful!
  periodSeconds: 10
  failureThreshold: 3
```

**Why it's wrong:**

- If app starts in 30s, you wait 180s unnecessarily
- If app takes 181s, it gets killed
- Can't detect liveness issues during startup

**✅ Solution:**

```yaml
startupProbe:
  httpGet:
    path: /health
    port: 8080
  periodSeconds: 10
  failureThreshold: 18 # 3 minutes max (10s * 18)

livenessProbe:
  httpGet:
    path: /health
    port: 8080
  periodSeconds: 10
  failureThreshold: 3 # 30s after startup completes
```

### 5. Heavy Operations in Health Checks

**❌ Problem:**

```go
func healthHandler(w http.ResponseWriter, r *http.Request) {
    // DON'T: Heavy database query
    var count int
    db.QueryRow("SELECT COUNT(*) FROM orders WHERE status = 'pending'").Scan(&count)

    w.WriteHeader(200)
}
```

**Why it's wrong:**

- Health check times out under load
- False failures due to slow query
- Unnecessary database load

**✅ Solution:**

```go
func healthHandler(w http.ResponseWriter, r *http.Request) {
    // Lightweight ping only
    if err := db.Ping(); err != nil {
        w.WriteHeader(503)
        return
    }
    w.WriteHeader(200)
}
```

### 6. Readiness Probe on Batch Jobs

**❌ Problem:**

```yaml
# CronJob doesn't receive traffic
kind: CronJob
spec:
  template:
    spec:
      containers:
        - name: batch
          image: batch-job:1.0
          readinessProbe: # Unnecessary!
            httpGet:
              path: /ready
              port: 8080
```

**Why it's wrong:**

- Batch jobs don't receive service traffic
- Readiness probe serves no purpose
- Adds unnecessary complexity

**✅ Solution:**

```yaml
# Only liveness probe for batch jobs
kind: CronJob
spec:
  template:
    spec:
      containers:
        - name: batch
          image: batch-job:1.0
          livenessProbe: # Detect if job hangs
            exec:
              command: ['pgrep', 'batch-process']
            periodSeconds: 30
```

### 7. TCP Probes for gRPC

**❌ Problem:**

```yaml
# gRPC service using TCP probe
livenessProbe:
  tcpSocket:
    port: 9090
```

**Why it's wrong:**

- TCP probe only checks port is open
- Doesn't verify gRPC service is healthy
- Can't detect application-level failures

**✅ Solution:**

```yaml
# Use gRPC probe (Kubernetes 1.27+)
livenessProbe:
  grpc:
    port: 9090
  periodSeconds: 10
```

### 8. Not Monitoring Probe Failures

**❌ Problem:**

- Deploy probes and forget them
- No alerts on high restart rates
- No metrics collection

**✅ Solution:**

```yaml
# Prometheus alerts
groups:
  - name: kubernetes-probes
    rules:
      - alert: HighPodRestartRate
        expr: rate(kube_pod_container_status_restarts_total[15m]) > 0.1
        annotations:
          summary: 'Pod {{ $labels.pod }} restarting frequently'

      - alert: PodNotReady
        expr: kube_pod_status_ready{condition="false"} == 1
        for: 5m
        annotations:
          summary: 'Pod {{ $labels.pod }} not ready for 5 minutes'
```

---

## References

### Official Documentation

- [Kubernetes Probes (Official)](https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/)
- [Configure Liveness, Readiness and Startup Probes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/)
- [Docker Compose Healthcheck](https://docs.docker.com/compose/compose-file/compose-file-v3/#healthcheck)
- [Kompose - Docker Compose to Kubernetes](https://kompose.io/)
- [gRPC Health Checking Protocol](https://github.com/grpc/grpc/blob/master/doc/health-checking.md)

### Migration Tools

- [Kompose GitHub](https://github.com/kubernetes/kompose)
- [Docker Compose to Kubernetes Translator](https://kubernetes.io/docs/tasks/configure-pod-container/translate-compose-kubernetes/)

### Best Practices & Guides

- [Google Cloud: Kubernetes Best Practices - Health Checks](https://cloud.google.com/blog/products/containers-kubernetes/kubernetes-best-practices-setting-up-health-checks-with-readiness-and-liveness-probes)
- [Fairwinds: Guide to Kubernetes Liveness Probes](https://www.fairwinds.com/blog/a-guide-to-understanding-kubernetes-liveness-probes-best-practices)
- [Datree: Readiness and Liveness Probes Best Practices](https://www.datree.io/resources/kubernetes-readiness-and-liveness-probes-best-practices)
- [Better Stack: Kubernetes Health Checks Guide](https://betterstack.com/community/guides/monitoring/kubernetes-health-checks/)

### Tools & Monitoring

- [Prometheus Kubernetes Metrics](https://github.com/kubernetes/kube-state-metrics)
- [Grafana Kubernetes Dashboards](https://grafana.com/grafana/dashboards/?search=kubernetes+health)

---

## Summary

### Key Takeaways

1. **Kubernetes ignores Docker HEALTHCHECK** - configure probes separately
2. **Use all three probe types** - startup, liveness, readiness serve different
   purposes
3. **Separate concerns** - liveness checks app health, readiness checks
   dependencies
4. **Choose the right mechanism** - HTTP (most common), TCP (simple), Exec
   (flexible), gRPC (modern)
5. **Configure based on real metrics** - don't guess timeouts and thresholds
6. **Use startup probes for slow apps** - avoid long initialDelaySeconds
7. **Monitor probe failures** - track restarts and readiness issues
8. **Test under load** - probe configurations that work in dev may fail in
   production
9. **Keep probes lightweight** - avoid heavy operations that can timeout
10. **Update probes as apps evolve** - configurations are not set-and-forget

### Migration Checklist

- [ ] Identify all Docker Compose healthchecks
- [ ] Map each healthcheck to Kubernetes probe types
- [ ] Determine appropriate probe mechanisms (HTTP, TCP, Exec, gRPC)
- [ ] Configure startup probes for slow-starting applications
- [ ] Implement dedicated `/healthz` and `/ready` endpoints
- [ ] Test probes in staging environment under load
- [ ] Set up monitoring and alerting for probe failures
- [ ] Document probe configurations in Helm chart values
- [ ] Remove Docker HEALTHCHECK instructions from Dockerfiles
- [ ] Schedule regular probe configuration reviews

---

**Document Version:** 1.0 **Last Updated:** 2025-11-14 **Author:** Research
compiled from 12+ authoritative sources **Status:** Production-ready migration
guide
