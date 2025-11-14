# Docker Healthcheck Observability: Monitoring, Logging & Alerting Strategies

**Research Report** **Date:** 2025-11-14 **Focus:** Production-grade Docker
healthcheck observability patterns, monitoring integrations, and incident
response automation

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Core Healthcheck Concepts](#core-healthcheck-concepts)
3. [Monitoring Integration Strategies](#monitoring-integration-strategies)
4. [Logging Best Practices](#logging-best-practices)
5. [Metrics Collection & Exporters](#metrics-collection--exporters)
6. [Visualization with Grafana](#visualization-with-grafana)
7. [Alerting Strategies](#alerting-strategies)
8. [Debugging Failed Healthchecks](#debugging-failed-healthchecks)
9. [Log Aggregation Solutions](#log-aggregation-solutions)
10. [Container Orchestrator Integration](#container-orchestrator-integration)
11. [SRE Patterns & SLO/SLI Integration](#sre-patterns--slosli-integration)
12. [Incident Response Automation](#incident-response-automation)
13. [Production Configurations](#production-configurations)
14. [Recommendations & Best Practices](#recommendations--best-practices)

---

## Executive Summary

### Key Findings

Docker healthchecks are **critical for production environments** but suffer from
limited native observability:

- ✅ **Native healthcheck support** exists in Docker Engine
- ❌ **No built-in Prometheus metrics** for healthcheck status
- ❌ **Limited logging** (only last 4096 bytes stored)
- ✅ **Orchestrators leverage healthchecks** for automated recovery
- ⚠️ **Kubernetes ignores Docker healthchecks** (uses own probes)

### Critical Gaps

1. **Metrics Gap:** Neither Docker's native Prometheus endpoint nor cAdvisor
   expose healthcheck status metrics
2. **Logging Gap:** Healthcheck output is truncated and not integrated with
   standard logging pipelines
3. **Observability Gap:** No standard way to aggregate healthcheck events across
   clusters

### Solutions Landscape

| Component              | Purpose                             | Maturity            | Recommendation                            |
| ---------------------- | ----------------------------------- | ------------------- | ----------------------------------------- |
| **Docker Healthcheck** | Container-level health verification | ✅ Stable           | Use for Docker Swarm, standalone          |
| **Kubernetes Probes**  | Pod-level health in K8s             | ✅ Production-ready | Replace Docker healthchecks in K8s        |
| **Custom Exporters**   | Healthcheck metrics                 | 🟡 Community-driven | Required for Prometheus integration       |
| **cAdvisor**           | Container metrics                   | ✅ Production-ready | Use for general metrics (not healthcheck) |
| **ELK/Loki**           | Log aggregation                     | ✅ Production-ready | Essential for healthcheck log analysis    |

---

## Core Healthcheck Concepts

### Healthcheck Parameters

```yaml
# Docker Compose example
healthcheck:
  test: ['CMD', 'curl', '-f', 'http://localhost:8080/health']
  interval: 30s # Time between checks (default: 30s)
  timeout: 10s # Max wait for response (default: 30s)
  start_period: 40s # Grace period during startup (default: 0s)
  retries: 3 # Consecutive failures to mark unhealthy (default: 3)
```

### Container States

1. **starting:** Initial state during `start_period`
2. **healthy:** All checks passing
3. **unhealthy:** `retries` consecutive failures

### Health Status Lifecycle

```
Container Start → [starting] → First Check
                      ↓
                 start_period grace
                      ↓
              ┌───────┴────────┐
              ↓                ↓
         [healthy]         [unhealthy]
              ↑                ↓
              └────────────────┘
           After retries reset
```

---

## Monitoring Integration Strategies

### Challenge: No Native Prometheus Metrics

**Problem Statement (as of 2024):**

- Docker's native Prometheus endpoint does **not** expose healthcheck metrics
- cAdvisor also **does not** provide healthcheck status
- GitHub issue [#2166](https://github.com/google/cadvisor/issues/2166) remains
  unresolved

**Quote from DevOps Stack Exchange:**

> "You will need to roll your own Prometheus Exporter to accomplish this."

### Solution 1: Custom Prometheus Exporters

#### A. gesellix/health-exporter

**GitHub:** https://github.com/gesellix/health-exporter

```yaml
# docker-compose.yml
services:
  health-exporter:
    image: gesellix/health-exporter:latest
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    ports:
      - '9090:9090'
    environment:
      HEALTH_EXPORTER_INTERVAL: 30s
```

**Metrics Exposed:**

```prometheus
# Each service status exposed as metric
health_status{container_name="app", status="healthy"} 1
health_status{container_name="db", status="unhealthy"} 0

# Overall health
health_overall 1
```

#### B. snapp-incubator/health-exporter

**GitHub:** https://github.com/snapp-incubator/health-exporter

**Features:**

- Continuous endpoint probing with configurable RPS
- High-resolution metrics (success rate, latency percentiles)
- Synthetic load testing capabilities

```yaml
# Configuration example
endpoints:
  - name: api_health
    url: http://api:8080/health
    interval: 5s
    timeout: 3s
    expected_status: 200
```

**Metrics Generated:**

```prometheus
health_check_success_rate{endpoint="api_health"} 0.98
health_check_latency_p99{endpoint="api_health"} 150.5
health_check_failures_total{endpoint="api_health"} 12
```

### Solution 2: Docker Engine Metrics (Experimental)

Docker Engine can expose metrics in Prometheus format (experimental feature).

**Enable in daemon.json:**

```json
{
  "metrics-addr": "0.0.0.0:9323",
  "experimental": true
}
```

**Prometheus scrape config:**

```yaml
scrape_configs:
  - job_name: 'docker'
    static_configs:
      - targets: ['docker-host:9323']
```

**Limitations:**

- Experimental feature (stability not guaranteed)
- Limited healthcheck-specific metrics
- Requires Docker daemon configuration access

### Solution 3: Application-Level Health Endpoints

**Spring Boot Actuator Example:**

```java
@RestController
public class HealthController {
    @GetMapping("/actuator/health")
    public ResponseEntity<Health> health() {
        return ResponseEntity.ok(
            Health.up()
                .withDetail("database", "connected")
                .withDetail("redis", "connected")
                .build()
        );
    }
}
```

**Prometheus scrape:**

```yaml
scrape_configs:
  - job_name: 'spring-boot'
    metrics_path: '/actuator/prometheus'
    static_configs:
      - targets: ['app:8080']
```

### Solution 4: cAdvisor for General Metrics

While cAdvisor doesn't provide healthcheck metrics, it's essential for container
resource monitoring.

```yaml
# docker-compose.yml
cadvisor:
  image: gcr.io/cadvisor/cadvisor:latest
  volumes:
    - /:/rootfs:ro
    - /var/run:/var/run:ro
    - /sys:/sys:ro
    - /var/lib/docker/:/var/lib/docker:ro
  ports:
    - '8080:8080'
```

**Available Metrics:**

```prometheus
container_cpu_usage_seconds_total
container_memory_usage_bytes
container_network_receive_bytes_total
container_fs_reads_bytes_total
# Note: NO container_health_status metric
```

---

## Logging Best Practices

### Challenge: Limited Healthcheck Logging

**Docker's Constraints:**

- Only **4096 bytes** of healthcheck output stored
- Output accessible via `docker inspect` (not `docker logs`)
- No integration with standard logging drivers

### Best Practice 1: Dedicated Health Log Files

**Inside Container:**

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD /app/healthcheck.sh 2>&1 | tee -a /var/log/healthcheck.log || exit 1
```

**healthcheck.sh:**

```bash
#!/bin/bash
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Perform health check
if curl -f http://localhost:8080/health; then
  echo "$TIMESTAMP [INFO] Health check passed"
  exit 0
else
  echo "$TIMESTAMP [ERROR] Health check failed"
  exit 1
fi
```

**Mount logs to host:**

```yaml
volumes:
  - ./logs:/var/log
```

### Best Practice 2: Structured Logging

**JSON Log Format:**

```bash
#!/bin/bash
log_health() {
  echo "{\"timestamp\":\"$(date -u +%s)\",\"level\":\"$1\",\"message\":\"$2\",\"check\":\"$3\",\"status\":\"$4\"}"
}

if curl -f http://localhost:8080/health > /dev/null 2>&1; then
  log_health "INFO" "Health check passed" "http" "200"
  exit 0
else
  log_health "ERROR" "Health check failed" "http" "connection_refused"
  exit 1
fi
```

### Best Practice 3: Log Rotation

**Docker logging driver configuration:**

```yaml
services:
  app:
    logging:
      driver: 'json-file'
      options:
        max-size: '10m'
        max-file: '3'
        labels: 'service,environment'
        tag: '{{.Name}}/{{.ID}}'
```

### Best Practice 4: Centralized Logging

**Docker logging to syslog:**

```yaml
logging:
  driver: syslog
  options:
    syslog-address: 'tcp://logs.example.com:514'
    tag: '{{.Name}}/{{.ID}}'
```

**Docker logging to Fluentd:**

```yaml
logging:
  driver: fluentd
  options:
    fluentd-address: 'localhost:24224'
    tag: 'docker.{{.Name}}'
```

---

## Metrics Collection & Exporters

### Complete Monitoring Stack Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Monitoring Stack                          │
│                                                               │
│  ┌──────────────┐      ┌──────────────┐                     │
│  │  cAdvisor    │────► │  Prometheus  │────► Grafana        │
│  │ (resources)  │      │              │                     │
│  └──────────────┘      │              │                     │
│                        │              │                     │
│  ┌──────────────┐      │              │                     │
│  │ Node Exporter│────► │              │                     │
│  │ (host metrics)      │              │                     │
│  └──────────────┘      │              │                     │
│                        │              │                     │
│  ┌──────────────┐      │              │                     │
│  │ Health       │────► │              │                     │
│  │ Exporter     │      │              │                     │
│  └──────────────┘      └──────────────┘                     │
│                                                               │
│  ┌──────────────┐      ┌──────────────┐                     │
│  │ Containers   │────► │  Loki/ELK    │────► Grafana        │
│  │ (logs)       │      │              │                     │
│  └──────────────┘      └──────────────┘                     │
└─────────────────────────────────────────────────────────────┘
```

### Complete Docker Compose Example

```yaml
version: '3.8'

services:
  # Application with healthcheck
  app:
    image: myapp:latest
    healthcheck:
      test: ['CMD', 'curl', '-f', 'http://localhost:8080/health']
      interval: 30s
      timeout: 10s
      start_period: 40s
      retries: 3
    labels:
      - 'monitoring.enable=true'
    logging:
      driver: 'json-file'
      options:
        max-size: '10m'
        max-file: '3'

  # cAdvisor - Container metrics
  cadvisor:
    image: gcr.io/cadvisor/cadvisor:latest
    container_name: cadvisor
    privileged: true
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:ro
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro
      - /dev/disk/:/dev/disk:ro
    ports:
      - '8080:8080'
    restart: unless-stopped

  # Node Exporter - Host metrics
  node-exporter:
    image: prom/node-exporter:latest
    container_name: node-exporter
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
      - '--collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)'
    ports:
      - '9100:9100'
    restart: unless-stopped

  # Custom Health Exporter
  health-exporter:
    image: gesellix/health-exporter:latest
    container_name: health-exporter
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    ports:
      - '9090:9090'
    restart: unless-stopped

  # Prometheus - Metrics storage & querying
  prometheus:
    image: prom/prometheus:latest
    container_name: prometheus
    volumes:
      - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml
      - ./prometheus/alert_rules.yml:/etc/prometheus/alert_rules.yml
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.console.libraries=/etc/prometheus/console_libraries'
      - '--web.console.templates=/etc/prometheus/consoles'
      - '--web.enable-lifecycle'
    ports:
      - '9090:9090'
    restart: unless-stopped
    healthcheck:
      test:
        [
          'CMD',
          'wget',
          '--quiet',
          '--tries=1',
          '--spider',
          'http://localhost:9090/-/ready',
        ]
      interval: 30s
      timeout: 10s
      retries: 3

  # AlertManager - Alert routing
  alertmanager:
    image: prom/alertmanager:latest
    container_name: alertmanager
    volumes:
      - ./alertmanager/config.yml:/etc/alertmanager/config.yml
      - alertmanager_data:/alertmanager
    command:
      - '--config.file=/etc/alertmanager/config.yml'
      - '--storage.path=/alertmanager'
    ports:
      - '9093:9093'
    restart: unless-stopped

  # Grafana - Visualization
  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    volumes:
      - grafana_data:/var/lib/grafana
      - ./grafana/dashboards:/etc/grafana/provisioning/dashboards
      - ./grafana/datasources:/etc/grafana/provisioning/datasources
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=admin
      - GF_USERS_ALLOW_SIGN_UP=false
    ports:
      - '3000:3000'
    restart: unless-stopped
    healthcheck:
      test:
        [
          'CMD-SHELL',
          'wget --no-verbose --tries=1 --spider http://localhost:3000/api/health
          || exit 1',
        ]
      interval: 30s
      timeout: 10s
      retries: 3

  # Loki - Log aggregation
  loki:
    image: grafana/loki:latest
    container_name: loki
    volumes:
      - ./loki/config.yml:/etc/loki/config.yml
      - loki_data:/loki
    command: -config.file=/etc/loki/config.yml
    ports:
      - '3100:3100'
    restart: unless-stopped

  # Promtail - Log shipping to Loki
  promtail:
    image: grafana/promtail:latest
    container_name: promtail
    volumes:
      - /var/log:/var/log:ro
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - ./promtail/config.yml:/etc/promtail/config.yml
    command: -config.file=/etc/promtail/config.yml
    restart: unless-stopped

volumes:
  prometheus_data:
  alertmanager_data:
  grafana_data:
  loki_data:
```

### Prometheus Configuration

**prometheus.yml:**

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

# Alertmanager configuration
alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - alertmanager:9093

# Load rules
rule_files:
  - 'alert_rules.yml'

# Scrape configurations
scrape_configs:
  # Prometheus itself
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  # cAdvisor
  - job_name: 'cadvisor'
    static_configs:
      - targets: ['cadvisor:8080']

  # Node Exporter
  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']

  # Custom Health Exporter
  - job_name: 'health-exporter'
    static_configs:
      - targets: ['health-exporter:9090']
    relabel_configs:
      - source_labels: [__address__]
        target_label: instance
        replacement: 'docker-health'

  # Application health endpoints
  - job_name: 'app-health'
    metrics_path: '/actuator/prometheus'
    static_configs:
      - targets: ['app:8080']
    relabel_configs:
      - source_labels: [__address__]
        target_label: service
        replacement: 'myapp'
```

---

## Visualization with Grafana

### Pre-built Dashboards

1. **Docker Dashboard** (ID: 10585)
   - URL: https://grafana.com/grafana/dashboards/10585-docker-dashboard/
   - Metrics: CPU, Memory, Network, Disk I/O per container

2. **Docker and System Monitoring** (ID: 893)
   - URL: https://grafana.com/grafana/dashboards/893-main/
   - Comprehensive view of Docker and host metrics

3. **Healthchecks.io Dashboard** (ID: 18998)
   - URL: https://grafana.com/grafana/dashboards/18998-healthchecks-io/
   - Total healthchecks, down checks, status per service

### Custom Healthcheck Dashboard

**JSON Model:**

```json
{
  "dashboard": {
    "title": "Docker Healthcheck Status",
    "panels": [
      {
        "title": "Healthcheck Status Overview",
        "type": "stat",
        "targets": [
          {
            "expr": "sum(health_status)",
            "legendFormat": "Total Healthy Containers"
          }
        ]
      },
      {
        "title": "Unhealthy Containers",
        "type": "table",
        "targets": [
          {
            "expr": "health_status{status=\"unhealthy\"} == 0",
            "format": "table",
            "instant": true
          }
        ]
      },
      {
        "title": "Health Check Failures Over Time",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(health_check_failures_total[5m])",
            "legendFormat": "{{container_name}}"
          }
        ]
      },
      {
        "title": "Health Check Latency (P99)",
        "type": "graph",
        "targets": [
          {
            "expr": "histogram_quantile(0.99, health_check_latency_bucket)",
            "legendFormat": "{{endpoint}}"
          }
        ]
      }
    ]
  }
}
```

### PromQL Queries for Healthcheck Monitoring

```promql
# Containers currently unhealthy
health_status{status="unhealthy"} == 0

# Health check failure rate (last 5 minutes)
rate(health_check_failures_total[5m])

# Average health check latency
avg(health_check_latency_seconds)

# Containers that have been unhealthy for > 5 minutes
health_status{status="unhealthy"} == 0 and time() - health_status_change_timestamp > 300

# Success rate (last hour)
sum(rate(health_check_success_total[1h])) / sum(rate(health_check_total[1h])) * 100
```

---

## Alerting Strategies

### AlertManager Configuration

**alertmanager/config.yml:**

```yaml
global:
  resolve_timeout: 5m
  slack_api_url: 'https://hooks.slack.com/services/YOUR/WEBHOOK/URL'

route:
  group_by: ['alertname', 'cluster', 'service']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 12h
  receiver: 'default'
  routes:
    # Critical alerts to PagerDuty
    - match:
        severity: critical
      receiver: 'pagerduty'
      continue: true

    # Warning alerts to Slack
    - match:
        severity: warning
      receiver: 'slack'

    # Healthcheck failures
    - match:
        alertname: ContainerUnhealthy
      receiver: 'slack'
      repeat_interval: 30m

receivers:
  - name: 'default'
    slack_configs:
      - channel: '#alerts'
        title: 'Alert: {{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.description }}{{ end }}'

  - name: 'slack'
    slack_configs:
      - channel: '#monitoring'
        send_resolved: true
        title: '{{ .GroupLabels.alertname }}'
        text: |
          *Status:* `{{ .Status }}`
          *Severity:* `{{ .CommonLabels.severity }}`
          {{ range .Alerts }}
          *Description:* {{ .Annotations.description }}
          *Details:* {{ .Annotations.summary }}
          {{ end }}

  - name: 'pagerduty'
    pagerduty_configs:
      - service_key: 'YOUR_PAGERDUTY_SERVICE_KEY'
        description:
          '{{ .GroupLabels.alertname }}: {{ .CommonAnnotations.summary }}'
```

### Alert Rules

**prometheus/alert_rules.yml:**

```yaml
groups:
  - name: healthcheck_alerts
    interval: 30s
    rules:
      # Container is unhealthy
      - alert: ContainerUnhealthy
        expr: health_status{status="unhealthy"} == 0
        for: 2m
        labels:
          severity: warning
          component: docker
        annotations:
          summary: 'Container {{ $labels.container_name }} is unhealthy'
          description:
            'Container {{ $labels.container_name }} has been unhealthy for more
            than 2 minutes.'

      # Container is down
      - alert: ContainerDown
        expr: up{job="cadvisor"} == 0
        for: 1m
        labels:
          severity: critical
          component: docker
        annotations:
          summary: 'Container {{ $labels.instance }} is down'
          description:
            'Container {{ $labels.instance }} has been down for more than 1
            minute.'

      # High health check failure rate
      - alert: HighHealthCheckFailureRate
        expr: rate(health_check_failures_total[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
          component: healthcheck
        annotations:
          summary:
            'High health check failure rate for {{ $labels.container_name }}'
          description:
            'Container {{ $labels.container_name }} has failure rate of {{
            $value }} checks/sec over the last 5 minutes.'

      # Health check latency is high
      - alert: HighHealthCheckLatency
        expr: health_check_latency_p99 > 5
        for: 5m
        labels:
          severity: warning
          component: healthcheck
        annotations:
          summary: 'High health check latency for {{ $labels.endpoint }}'
          description:
            'P99 latency for {{ $labels.endpoint }} is {{ $value }}s (threshold:
            5s).'

      # Container restarting frequently
      - alert: ContainerRestartingFrequently
        expr: rate(container_restarts_total[1h]) > 5
        for: 5m
        labels:
          severity: critical
          component: docker
        annotations:
          summary:
            'Container {{ $labels.container_name }} restarting frequently'
          description:
            'Container {{ $labels.container_name }} has restarted {{ $value }}
            times in the last hour.'

      # Memory usage high
      - alert: ContainerMemoryHigh
        expr:
          (container_memory_usage_bytes / container_spec_memory_limit_bytes) *
          100 > 80
        for: 5m
        labels:
          severity: warning
          component: docker
        annotations:
          summary: 'Container {{ $labels.container_name }} memory usage high'
          description:
            'Container {{ $labels.container_name }} is using {{ $value }}% of
            its memory limit.'

      # CPU usage high
      - alert: ContainerCPUHigh
        expr: rate(container_cpu_usage_seconds_total[5m]) * 100 > 80
        for: 5m
        labels:
          severity: warning
          component: docker
        annotations:
          summary: 'Container {{ $labels.container_name }} CPU usage high'
          description:
            'Container {{ $labels.container_name }} CPU usage is {{ $value }}%.'
```

### Notification Channels

#### Slack Integration

```yaml
- name: 'slack-critical'
  slack_configs:
    - api_url: 'https://hooks.slack.com/services/YOUR/WEBHOOK/URL'
      channel: '#production-alerts'
      username: 'AlertManager'
      icon_emoji: ':rotating_light:'
      title: 'CRITICAL: {{ .GroupLabels.alertname }}'
      text: |
        *Severity:* `{{ .CommonLabels.severity }}`
        *Environment:* `{{ .CommonLabels.environment }}`
        {{ range .Alerts }}
        *Container:* `{{ .Labels.container_name }}`
        *Status:* {{ if eq .Status "firing" }}:fire: FIRING{{ else }}:white_check_mark: RESOLVED{{ end }}
        *Description:* {{ .Annotations.description }}
        *Runbook:* {{ .Annotations.runbook_url }}
        {{ end }}
```

#### Email Integration

```yaml
- name: 'email'
  email_configs:
    - to: 'ops-team@example.com'
      from: 'alertmanager@example.com'
      smarthost: 'smtp.example.com:587'
      auth_username: 'alertmanager@example.com'
      auth_password: 'password'
      headers:
        Subject:
          '[{{ .Status | toUpper }}{{ if eq .Status "firing" }}:{{
          .Alerts.Firing | len }}{{ end }}] {{ .GroupLabels.alertname }}'
```

#### PagerDuty Integration

```yaml
- name: 'pagerduty-critical'
  pagerduty_configs:
    - routing_key: 'YOUR_PAGERDUTY_INTEGRATION_KEY'
      severity:
        '{{ if eq .CommonLabels.severity "critical" }}critical{{ else
        }}warning{{ end }}'
      description:
        '{{ .GroupLabels.alertname }}: {{ .CommonAnnotations.summary }}'
      details:
        firing: '{{ template "pagerduty.default.instances" .Alerts.Firing }}'
        resolved:
          '{{ template "pagerduty.default.instances" .Alerts.Resolved }}'
```

### Specialized Alerting Tools

#### 1. Docker-Healthcheck-Alert

**GitHub:** https://github.com/l-Legacy-l/Docker-Healthcheck-Alert

```yaml
services:
  healthcheck-alert:
    image: l-legacy-l/docker-healthcheck-alert:latest
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      - SMTP_HOST=smtp.gmail.com
      - SMTP_PORT=587
      - SMTP_USER=alerts@example.com
      - SMTP_PASS=your_password
      - ALERT_EMAIL=ops@example.com
      - CHECK_INTERVAL=60
```

**Features:**

- Detects unhealthy containers
- Sends email alerts
- Sends recovery notifications

#### 2. Kontrol

**GitHub:** https://github.com/kalisio/kontrol

```yaml
services:
  kontrol:
    image: kalisio/kontrol:latest
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      - SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
      - HEALTHCHECK_INTERVAL=30s
```

**Features:**

- Health checks against resources
- Healing commands via Docker API
- Slack notifications
- Auto-restart unhealthy containers

---

## Debugging Failed Healthchecks

### Step 1: Inspect Health Status

```bash
# View detailed health status
docker inspect --format "{{json .State.Health }}" container_name | jq

# Output example:
{
  "Status": "unhealthy",
  "FailingStreak": 5,
  "Log": [
    {
      "Start": "2024-11-14T10:30:00.123456789Z",
      "End": "2024-11-14T10:30:05.987654321Z",
      "ExitCode": 1,
      "Output": "curl: (7) Failed to connect to localhost port 8080: Connection refused"
    },
    ...
  ]
}
```

### Step 2: View Recent Logs

```bash
# View container logs
docker logs container_name --tail 100

# View logs with timestamps
docker logs container_name --timestamps --since 10m

# Follow logs in real-time
docker logs -f container_name
```

### Step 3: Manual Healthcheck Execution

```bash
# Execute healthcheck command manually
docker exec container_name curl -f http://localhost:8080/health

# Or using the exact healthcheck command
docker exec container_name sh -c "curl -f http://localhost:8080/health"

# Test with verbose output
docker exec container_name curl -v http://localhost:8080/health
```

### Step 4: Interactive Debugging

```bash
# Enter container shell
docker exec -it container_name /bin/bash

# Inside container, check:
# 1. Process status
ps aux | grep java

# 2. Port listening
netstat -tuln | grep 8080
# or
ss -tuln | grep 8080

# 3. Network connectivity
curl -v http://localhost:8080/health

# 4. DNS resolution (if external checks)
nslookup database-host
ping database-host

# 5. File permissions
ls -la /app/healthcheck.sh

# 6. Dependencies
which curl
curl --version
```

### Step 5: Common Issues & Solutions

#### Issue 1: Missing Dependencies

**Symptom:**

```
/bin/sh: curl: not found
```

**Solution:**

```dockerfile
# Install curl in Dockerfile
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Or use wget
HEALTHCHECK --interval=30s --timeout=10s \
  CMD wget --quiet --tries=1 --spider http://localhost:8080/health || exit 1
```

#### Issue 2: Port Mismatch

**Symptom:**

```
curl: (7) Failed to connect to localhost port 8080: Connection refused
```

**Solution:**

```yaml
# Use internal port, not exposed port
healthcheck:
  test: ['CMD', 'curl', '-f', 'http://localhost:8080/health'] # ✅ Internal port
  # NOT: http://localhost:3000/health  # ❌ External port mapping
```

#### Issue 3: Timing Issues

**Symptom:** Container marked unhealthy during startup

**Solution:**

```yaml
healthcheck:
  test: ['CMD', 'curl', '-f', 'http://localhost:8080/health']
  interval: 30s
  timeout: 10s
  start_period: 60s # ✅ Increase grace period for slow startup
  retries: 3
```

#### Issue 4: Long-Running Healthchecks

**Symptom:**

```
Health check exceeded timeout (10s)
```

**Solution:**

```yaml
healthcheck:
  test: ['CMD', 'curl', '-f', '-m', '5', 'http://localhost:8080/health'] # -m 5: max 5 seconds
  timeout: 10s # ✅ Ensure timeout > curl max-time
```

### Debugging Workflow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                 Healthcheck Failure                          │
└────────────────────┬────────────────────────────────────────┘
                     ↓
         ┌───────────────────────┐
         │ docker inspect         │
         │ Check Health.Status   │
         └───────────┬───────────┘
                     ↓
         ┌───────────────────────┐
         │ Review Health.Log     │
         │ Exit codes & output   │
         └───────────┬───────────┘
                     ↓
         ┌───────────────────────┐
         │ docker exec           │
         │ Manual healthcheck    │
         └───────────┬───────────┘
                     ↓
              ┌──────┴──────┐
              │   Success?   │
              └──┬────────┬──┘
          Yes   │        │   No
                │        │
                ↓        ↓
    ┌──────────────┐  ┌──────────────┐
    │ Timing issue │  │ Deep dive:   │
    │ Adjust:      │  │ - Logs       │
    │ start_period │  │ - Processes  │
    │ retries      │  │ - Ports      │
    │ interval     │  │ - Network    │
    └──────────────┘  │ - Deps       │
                      └──────────────┘
```

---

## Log Aggregation Solutions

### Solution 1: Loki + Promtail + Grafana

#### Architecture Overview

```
Docker Containers → Promtail → Loki → Grafana
                       ↑
                  Docker logs
                  Log files
```

#### Loki Configuration

**loki/config.yml:**

```yaml
auth_enabled: false

server:
  http_listen_port: 3100

ingester:
  lifecycler:
    address: 127.0.0.1
    ring:
      kvstore:
        store: inmemory
      replication_factor: 1
    final_sleep: 0s
  chunk_idle_period: 5m
  chunk_retain_period: 30s

schema_config:
  configs:
    - from: 2020-10-24
      store: boltdb
      object_store: filesystem
      schema: v11
      index:
        prefix: index_
        period: 168h

storage_config:
  boltdb:
    directory: /loki/index

  filesystem:
    directory: /loki/chunks

limits_config:
  enforce_metric_name: false
  reject_old_samples: true
  reject_old_samples_max_age: 168h

chunk_store_config:
  max_look_back_period: 0s

table_manager:
  retention_deletes_enabled: true
  retention_period: 168h
```

#### Promtail Configuration

**promtail/config.yml:**

```yaml
server:
  http_listen_port: 9080
  grpc_listen_port: 0

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  # Docker container logs
  - job_name: docker
    static_configs:
      - targets:
          - localhost
        labels:
          job: docker
          __path__: /var/lib/docker/containers/*/*-json.log

    pipeline_stages:
      - json:
          expressions:
            output: log
            stream: stream
            attrs:
      - json:
          expressions:
            tag:
          source: attrs
      - regex:
          expression: (?P<container_name>(?:[^|]*[^|]))
          source: tag
      - labels:
          container_name:
          stream:

  # System logs
  - job_name: system
    static_configs:
      - targets:
          - localhost
        labels:
          job: system
          __path__: /var/log/*.log

  # Application-specific healthcheck logs
  - job_name: healthchecks
    static_configs:
      - targets:
          - localhost
        labels:
          job: healthchecks
          __path__: /var/log/healthcheck*.log

    pipeline_stages:
      - json:
          expressions:
            timestamp: timestamp
            level: level
            message: message
            check: check
            status: status
      - labels:
          level:
          check:
          status:
      - timestamp:
          source: timestamp
          format: Unix
```

#### Grafana Loki Queries

```logql
# All healthcheck failures
{job="healthchecks"} |= "ERROR"

# Healthcheck failures for specific container
{container_name="app"} |= "health check failed"

# Parse JSON logs and filter
{job="healthchecks"} | json | status="failed"

# Count failures over time
count_over_time({job="healthchecks"} |= "ERROR" [5m])

# Rate of healthcheck failures
rate({job="healthchecks"} |= "ERROR" [5m])
```

### Solution 2: ELK Stack (Elasticsearch, Logstash, Kibana)

#### Architecture Overview

```
Docker Containers → Logspout → Logstash → Elasticsearch → Kibana
```

#### Docker Compose Configuration

```yaml
services:
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.11.0
    environment:
      - discovery.type=single-node
      - 'ES_JAVA_OPTS=-Xms512m -Xmx512m'
      - xpack.security.enabled=false
    volumes:
      - elasticsearch_data:/usr/share/elasticsearch/data
    ports:
      - '9200:9200'
    healthcheck:
      test:
        ['CMD-SHELL', 'curl -f http://localhost:9200/_cluster/health || exit 1']
      interval: 30s
      timeout: 10s
      retries: 5

  logstash:
    image: docker.elastic.co/logstash/logstash:8.11.0
    volumes:
      - ./logstash/pipeline:/usr/share/logstash/pipeline
    ports:
      - '5000:5000/udp'
    environment:
      - 'LS_JAVA_OPTS=-Xmx256m -Xms256m'
    depends_on:
      - elasticsearch

  kibana:
    image: docker.elastic.co/kibana/kibana:8.11.0
    ports:
      - '5601:5601'
    environment:
      - ELASTICSEARCH_HOSTS=http://elasticsearch:9200
    depends_on:
      - elasticsearch

  logspout:
    image: gliderlabs/logspout:latest
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    command: udp://logstash:5000
    depends_on:
      - logstash
```

#### Logstash Pipeline

**logstash/pipeline/docker-logs.conf:**

```ruby
input {
  udp {
    port => 5000
    codec => json
  }
}

filter {
  # Parse Docker container name
  if [docker][name] {
    mutate {
      add_field => { "container_name" => "%{[docker][name]}" }
    }
  }

  # Parse healthcheck logs (JSON format)
  if [message] =~ /^\{.*\}$/ {
    json {
      source => "message"
      target => "healthcheck"
    }

    if [healthcheck][check] {
      mutate {
        add_field => {
          "check_type" => "%{[healthcheck][check]}"
          "check_status" => "%{[healthcheck][status]}"
          "log_level" => "%{[healthcheck][level]}"
        }
      }
    }
  }

  # Add timestamp
  date {
    match => [ "timestamp", "UNIX", "ISO8601" ]
    target => "@timestamp"
  }

  # Tag healthcheck failures
  if [check_status] == "failed" or [log_level] == "ERROR" {
    mutate {
      add_tag => [ "healthcheck_failure" ]
    }
  }
}

output {
  elasticsearch {
    hosts => ["elasticsearch:9200"]
    index => "docker-logs-%{+YYYY.MM.dd}"
  }

  # Debug output
  stdout {
    codec => rubydebug
  }
}
```

#### Kibana Queries

```
# Healthcheck failures in last 24 hours
check_status:"failed" AND @timestamp:[now-24h TO now]

# Specific container healthchecks
container_name:"app" AND check_type:"http"

# Error level logs
log_level:"ERROR"

# Healthcheck failure rate
tags:"healthcheck_failure"
```

### Loki vs ELK Comparison

| Feature                 | Loki                         | ELK Stack                     |
| ----------------------- | ---------------------------- | ----------------------------- |
| **Index Strategy**      | Label-based (metadata only)  | Full-text indexing            |
| **Storage Cost**        | Low (doesn't index content)  | High (indexes everything)     |
| **Query Speed**         | Fast for label queries       | Fast for full-text search     |
| **Setup Complexity**    | Simple                       | Complex                       |
| **Resource Usage**      | Low                          | High                          |
| **Full-Text Search**    | Limited                      | Excellent                     |
| **Grafana Integration** | Native                       | Via plugin                    |
| **Best For**            | Cloud-native, cost-conscious | Enterprise, rich search needs |

---

## Container Orchestrator Integration

### Docker Swarm

#### Native Healthcheck Integration

Docker Swarm **uses Docker healthchecks** to manage service availability.

**Service Definition:**

```yaml
version: '3.8'

services:
  app:
    image: myapp:latest
    deploy:
      replicas: 3
      restart_policy:
        condition: on-failure
        delay: 5s
        max_attempts: 3
        window: 120s
      update_config:
        parallelism: 1
        delay: 10s
        failure_action: rollback
        monitor: 60s
        order: start-first
    healthcheck:
      test: ['CMD', 'curl', '-f', 'http://localhost:8080/health']
      interval: 30s
      timeout: 10s
      start_period: 40s
      retries: 3
```

**Behavior:**

- Swarm monitors healthcheck status
- Unhealthy replicas are replaced automatically
- Rolling updates respect healthcheck status
- Traffic routing avoids unhealthy containers

**Check service status:**

```bash
# View service tasks
docker service ps app

# View task logs
docker service logs app

# Inspect specific task
docker inspect <task_id>
```

### Kubernetes

#### CRITICAL: Kubernetes Ignores Docker Healthchecks

**Official Kubernetes Behavior:**

- Docker HEALTHCHECK directive is **explicitly disabled** since Kubernetes 1.8
- Kubernetes does **not** expose Docker healthcheck status in API server
- You **must** use Kubernetes probes instead

#### Kubernetes Probe Types

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app
spec:
  containers:
    - name: app
      image: myapp:latest
      ports:
        - containerPort: 8080

      # Liveness Probe - When to restart container
      livenessProbe:
        httpGet:
          path: /health
          port: 8080
        initialDelaySeconds: 15
        periodSeconds: 10
        timeoutSeconds: 5
        successThreshold: 1
        failureThreshold: 3

      # Readiness Probe - When to route traffic
      readinessProbe:
        httpGet:
          path: /ready
          port: 8080
        initialDelaySeconds: 5
        periodSeconds: 5
        timeoutSeconds: 3
        successThreshold: 1
        failureThreshold: 3

      # Startup Probe - For slow-starting containers
      startupProbe:
        httpGet:
          path: /health
          port: 8080
        initialDelaySeconds: 0
        periodSeconds: 10
        timeoutSeconds: 5
        successThreshold: 1
        failureThreshold: 30 # 30 * 10s = 5 minutes max startup
```

#### Probe Types Comparison

| Probe Type         | Purpose                   | Failure Action           | Use Case                   |
| ------------------ | ------------------------- | ------------------------ | -------------------------- |
| **livenessProbe**  | Is app alive?             | Restart container        | Detect deadlocks, crashes  |
| **readinessProbe** | Is app ready for traffic? | Remove from service      | Database not ready, warmup |
| **startupProbe**   | Has app started?          | Restart if startup fails | Slow legacy apps           |

#### Probe Mechanisms

**1. HTTP GET:**

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8080
    httpHeaders:
      - name: X-Custom-Header
        value: HealthCheck
```

**2. TCP Socket:**

```yaml
livenessProbe:
  tcpSocket:
    port: 5432
```

**3. Exec Command:**

```yaml
livenessProbe:
  exec:
    command:
      - cat
      - /tmp/healthy
```

**4. gRPC (Kubernetes 1.24+):**

```yaml
livenessProbe:
  grpc:
    port: 50051
    service: my.Service
```

#### Best Practices for Kubernetes

**1. Use Different Endpoints:**

```yaml
# Liveness: Check if app is alive (lightweight)
livenessProbe:
  httpGet:
    path: /healthz

# Readiness: Check if app can serve traffic (heavier checks)
readinessProbe:
  httpGet:
    path: /readyz
```

**2. Tune for Slow Startups:**

```yaml
startupProbe:
  httpGet:
    path: /health
  failureThreshold: 30
  periodSeconds: 10
# Allows up to 5 minutes for startup (30 * 10s)

livenessProbe:
  httpGet:
    path: /health
  initialDelaySeconds: 0 # startupProbe handles initial delay
  periodSeconds: 10
```

**3. Avoid Cascading Failures:**

```yaml
# DON'T check downstream dependencies in liveness
livenessProbe:
  httpGet:
    path: /health # Only check THIS service

# DO check dependencies in readiness
readinessProbe:
  httpGet:
    path: /ready # Can check database, cache, etc.
```

#### Migration from Docker Healthcheck to Kubernetes

**Before (Docker Compose):**

```yaml
healthcheck:
  test: ['CMD', 'curl', '-f', 'http://localhost:8080/health']
  interval: 30s
  timeout: 10s
  start_period: 40s
  retries: 3
```

**After (Kubernetes):**

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8080
  periodSeconds: 30 # interval
  timeoutSeconds: 10 # timeout
  failureThreshold: 3 # retries

startupProbe:
  httpGet:
    path: /health
    port: 8080
  periodSeconds: 10
  failureThreshold: 4 # 40s start_period / 10s period
```

---

## SRE Patterns & SLO/SLI Integration

### Core SRE Concepts

**SLI (Service Level Indicator):**

- Quantifiable measure of service health
- Examples: Availability, latency, error rate

**SLO (Service Level Objective):**

- Target value or range for an SLI
- Example: 99.9% availability over 30 days

**SLA (Service Level Agreement):**

- Business contract with consequences
- Example: 99.95% uptime or money-back guarantee

### Four Golden Signals (Google SRE)

```
1. Latency       → How long requests take
2. Traffic       → How much demand on the system
3. Errors        → Rate of failed requests
4. Saturation    → How "full" the service is
```

### Healthcheck-Based SLIs

#### 1. Availability SLI

**Definition:**

```
Availability = (Successful health checks / Total health checks) * 100
```

**PromQL:**

```promql
# 30-day availability
(
  sum(increase(health_check_success_total[30d]))
  /
  sum(increase(health_check_total[30d]))
) * 100
```

**SLO Example:**

```yaml
slo:
  name: 'Service Availability'
  sli:
    metric: health_check_success_rate
  target: 99.9 # 99.9% availability
  window: 30d
```

#### 2. Latency SLI

**Definition:**

```
Latency SLI = Percentage of health checks completing < threshold
```

**PromQL:**

```promql
# % of health checks under 1 second
histogram_quantile(0.95, health_check_latency_bucket) < 1
```

**SLO Example:**

```yaml
slo:
  name: 'Health Check Latency'
  sli:
    metric: health_check_latency_p95
  target: 1.0 # 95% of checks < 1 second
  window: 7d
```

#### 3. Error Budget

**Definition:**

```
Error Budget = 1 - SLO
If SLO = 99.9%, Error Budget = 0.1% = 43.2 minutes/month
```

**PromQL for Burn Rate:**

```promql
# How fast are we consuming error budget?
(
  1 - (
    sum(rate(health_check_success_total[1h]))
    /
    sum(rate(health_check_total[1h]))
  )
) / (1 - 0.999)  # Divide by error budget (0.1%)
```

### Alerting on Error Budget Depletion

```yaml
groups:
  - name: slo_alerts
    rules:
      # Fast burn (2% budget in 1 hour)
      - alert: ErrorBudgetBurnRateFast
        expr: |
          (
            1 - (
              sum(rate(health_check_success_total[1h]))
              /
              sum(rate(health_check_total[1h]))
            )
          ) / 0.001 > 14.4
        labels:
          severity: critical
          slo: availability
        annotations:
          summary: 'Fast error budget burn detected'
          description:
            'At current rate, error budget will be exhausted in {{ $value |
            humanizeDuration }}'

      # Slow burn (5% budget in 6 hours)
      - alert: ErrorBudgetBurnRateSlow
        expr: |
          (
            1 - (
              sum(rate(health_check_success_total[6h]))
              /
              sum(rate(health_check_total[6h]))
            )
          ) / 0.001 > 6
        labels:
          severity: warning
          slo: availability
        annotations:
          summary: 'Slow error budget burn detected'
```

### SLO Tracking Dashboard

**Grafana JSON:**

```json
{
  "panels": [
    {
      "title": "30-Day Availability SLO",
      "type": "gauge",
      "targets": [
        {
          "expr": "(sum(increase(health_check_success_total[30d])) / sum(increase(health_check_total[30d]))) * 100"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "thresholds": {
            "steps": [
              { "value": 0, "color": "red" },
              { "value": 99.5, "color": "yellow" },
              { "value": 99.9, "color": "green" }
            ]
          },
          "max": 100,
          "min": 99
        }
      }
    },
    {
      "title": "Error Budget Remaining",
      "type": "stat",
      "targets": [
        {
          "expr": "(0.001 - (1 - (sum(increase(health_check_success_total[30d])) / sum(increase(health_check_total[30d]))))) * 100"
        }
      ]
    },
    {
      "title": "Time Until Budget Exhaustion",
      "type": "stat",
      "targets": [
        {
          "expr": "43200 * ((0.001 - (1 - (sum(increase(health_check_success_total[30d])) / sum(increase(health_check_total[30d]))))) / (1 - (sum(rate(health_check_success_total[1h])) / sum(rate(health_check_total[1h])))))"
        }
      ]
    }
  ]
}
```

### Implementing USE Method

**USE = Utilization, Saturation, Errors**

```promql
# Utilization: % of time health checks are running
rate(health_check_duration_seconds_sum[5m]) / rate(health_check_duration_seconds_count[5m])

# Saturation: Queue depth of pending health checks
health_check_queue_depth

# Errors: Error rate
rate(health_check_errors_total[5m])
```

### Implementing RED Method

**RED = Rate, Errors, Duration**

```promql
# Rate: Requests per second
rate(health_check_total[5m])

# Errors: Error rate
rate(health_check_failures_total[5m]) / rate(health_check_total[5m])

# Duration: Latency distribution
histogram_quantile(0.99, rate(health_check_duration_seconds_bucket[5m]))
```

---

## Incident Response Automation

### Automated Remediation Workflows

#### 1. Auto-Restart Unhealthy Containers

**Using Kontrol (https://github.com/kalisio/kontrol):**

```yaml
services:
  kontrol:
    image: kalisio/kontrol:latest
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      - HEALTHCHECK_INTERVAL=30s
      - AUTO_RESTART=true
      - MAX_RESTART_ATTEMPTS=3
      - RESTART_DELAY=60s
      - SLACK_WEBHOOK_URL=${SLACK_WEBHOOK}
```

**Custom Script:**

```bash
#!/bin/bash
# auto-heal.sh - Monitor and restart unhealthy containers

SLACK_WEBHOOK="https://hooks.slack.com/services/YOUR/WEBHOOK"

check_and_heal() {
  local container_id=$1
  local container_name=$2
  local health_status=$(docker inspect --format='{{.State.Health.Status}}' "$container_id")

  if [ "$health_status" == "unhealthy" ]; then
    echo "Container $container_name is unhealthy. Attempting restart..."

    # Send Slack notification
    curl -X POST "$SLACK_WEBHOOK" -H 'Content-Type: application/json' -d "{
      \"text\": \":warning: Container \`$container_name\` unhealthy. Restarting...\",
      \"attachments\": [{
        \"color\": \"warning\",
        \"fields\": [
          {\"title\": \"Container\", \"value\": \"$container_name\", \"short\": true},
          {\"title\": \"Action\", \"value\": \"Auto-restart\", \"short\": true}
        ]
      }]
    }"

    # Restart container
    docker restart "$container_id"

    # Wait and check if restart fixed the issue
    sleep 60
    new_status=$(docker inspect --format='{{.State.Health.Status}}' "$container_id")

    if [ "$new_status" == "healthy" ]; then
      curl -X POST "$SLACK_WEBHOOK" -H 'Content-Type: application/json' -d "{
        \"text\": \":white_check_mark: Container \`$container_name\` recovered successfully\",
        \"attachments\": [{\"color\": \"good\"}]
      }"
    else
      curl -X POST "$SLACK_WEBHOOK" -H 'Content-Type: application/json' -d "{
        \"text\": \":x: Container \`$container_name\` still unhealthy after restart. Manual intervention required.\",
        \"attachments\": [{\"color\": \"danger\"}]
      }"
    fi
  fi
}

# Monitor all containers with healthchecks
while true; do
  docker ps --format '{{.ID}} {{.Names}}' | while read container_id container_name; do
    check_and_heal "$container_id" "$container_name"
  done
  sleep 30
done
```

**Run as systemd service:**

```ini
# /etc/systemd/system/docker-auto-heal.service
[Unit]
Description=Docker Auto-Heal Service
After=docker.service
Requires=docker.service

[Service]
Type=simple
ExecStart=/usr/local/bin/auto-heal.sh
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

#### 2. Runbook Automation

**Prometheus Alert with Runbook:**

```yaml
- alert: ContainerUnhealthy
  expr: health_status{status="unhealthy"} == 0
  for: 2m
  labels:
    severity: warning
    runbook: 'https://runbooks.example.com/container-unhealthy'
  annotations:
    summary: 'Container {{ $labels.container_name }} is unhealthy'
    description: |
      Container {{ $labels.container_name }} has been unhealthy for 2 minutes.

      ## Automated Actions Taken:
      1. Healthcheck logs collected
      2. Container restarted (attempt 1 of 3)

      ## Next Steps:
      1. Check application logs: `docker logs {{ $labels.container_name }}`
      2. Verify dependencies (database, cache)
      3. If issue persists, escalate to on-call engineer

      ## Runbook: {{ .Labels.runbook }}
```

**Webhook Receiver for Automation:**

```python
# runbook-executor.py
from flask import Flask, request
import docker
import subprocess

app = Flask(__name__)
client = docker.from_env()

@app.route('/webhook', methods=['POST'])
def handle_alert():
    alert = request.json
    alertname = alert['commonLabels']['alertname']
    container_name = alert['commonLabels'].get('container_name')

    if alertname == 'ContainerUnhealthy':
        execute_runbook('container-unhealthy', container_name)

    return {'status': 'ok'}

def execute_runbook(runbook_name, container_name):
    if runbook_name == 'container-unhealthy':
        # Step 1: Collect logs
        container = client.containers.get(container_name)
        logs = container.logs(tail=100).decode('utf-8')

        # Step 2: Save logs for analysis
        with open(f'/var/log/incidents/{container_name}-{int(time.time())}.log', 'w') as f:
            f.write(logs)

        # Step 3: Attempt restart
        container.restart()

        # Step 4: Monitor for recovery
        time.sleep(60)
        container.reload()
        health = container.attrs['State']['Health']['Status']

        if health == 'healthy':
            send_slack_notification(f"✅ Container {container_name} recovered")
        else:
            send_pagerduty_alert(f"❌ Container {container_name} still unhealthy")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
```

#### 3. Chaos Engineering Integration

**Detect and recover from injected failures:**

```yaml
# chaos-test.yml
services:
  app:
    image: myapp:latest
    healthcheck:
      test: ['CMD', 'curl', '-f', 'http://localhost:8080/health']
      interval: 10s
      timeout: 5s
      retries: 2
    labels:
      - 'chaos.enabled=true'

  chaos-monkey:
    image: alexei-led/pumba:latest
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    command: |
      pumba --interval 5m
      kill --signal SIGTERM
      "re2:app"
```

**Monitor recovery time:**

```promql
# Time to recovery (seconds)
time() - health_status_change_timestamp{status="unhealthy"}

# Alert if recovery takes > 5 minutes
(time() - health_status_change_timestamp{status="unhealthy"}) > 300
```

---

## Production Configurations

### Complete Production Stack

This section provides battle-tested configurations for production environments.

#### 1. Web Application Example

**docker-compose.prod.yml:**

```yaml
version: '3.8'

services:
  # Nginx reverse proxy
  nginx:
    image: nginx:alpine
    ports:
      - '80:80'
      - '443:443'
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl:/etc/nginx/ssl:ro
    healthcheck:
      test:
        [
          'CMD',
          'wget',
          '--quiet',
          '--tries=1',
          '--spider',
          'http://localhost/health',
        ]
      interval: 30s
      timeout: 10s
      start_period: 10s
      retries: 3
    depends_on:
      app:
        condition: service_healthy
    restart: unless-stopped
    logging:
      driver: 'json-file'
      options:
        max-size: '10m'
        max-file: '3'

  # Node.js application
  app:
    image: myapp:${VERSION:-latest}
    environment:
      - NODE_ENV=production
      - DATABASE_URL=postgresql://user:pass@postgres:5432/db
      - REDIS_URL=redis://redis:6379
    healthcheck:
      test: ['CMD', 'node', 'healthcheck.js']
      interval: 30s
      timeout: 10s
      start_period: 60s # Long startup for DB migrations
      retries: 3
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped
    logging:
      driver: 'json-file'
      options:
        max-size: '10m'
        max-file: '5'
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
        reservations:
          cpus: '1'
          memory: 1G

  # PostgreSQL database
  postgres:
    image: postgres:15-alpine
    environment:
      - POSTGRES_DB=myapp
      - POSTGRES_USER=myapp
      - POSTGRES_PASSWORD_FILE=/run/secrets/db_password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ['CMD-SHELL', 'pg_isready -U myapp']
      interval: 10s
      timeout: 5s
      start_period: 10s
      retries: 5
    restart: unless-stopped
    secrets:
      - db_password
    logging:
      driver: 'json-file'
      options:
        max-size: '10m'
        max-file: '3'

  # Redis cache
  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data
    healthcheck:
      test: ['CMD', 'redis-cli', 'ping']
      interval: 10s
      timeout: 5s
      start_period: 5s
      retries: 3
    restart: unless-stopped
    logging:
      driver: 'json-file'
      options:
        max-size: '10m'
        max-file: '3'

volumes:
  postgres_data:
  redis_data:

secrets:
  db_password:
    file: ./secrets/db_password.txt
```

**healthcheck.js:**

```javascript
// healthcheck.js - Comprehensive health check for Node.js app
const http = require('http');
const { Client } = require('pg');
const redis = require('redis');

async function checkDatabase() {
  const client = new Client({
    connectionString: process.env.DATABASE_URL,
    connectionTimeoutMillis: 3000,
  });

  try {
    await client.connect();
    await client.query('SELECT 1');
    await client.end();
    return true;
  } catch (err) {
    console.error('Database check failed:', err.message);
    return false;
  }
}

async function checkRedis() {
  const client = redis.createClient({
    url: process.env.REDIS_URL,
    socket: { connectTimeout: 3000 },
  });

  try {
    await client.connect();
    await client.ping();
    await client.quit();
    return true;
  } catch (err) {
    console.error('Redis check failed:', err.message);
    return false;
  }
}

async function checkApplication() {
  return new Promise((resolve) => {
    http
      .get('http://localhost:3000/api/health', (res) => {
        resolve(res.statusCode === 200);
      })
      .on('error', (err) => {
        console.error('Application check failed:', err.message);
        resolve(false);
      });
  });
}

async function main() {
  const checks = await Promise.all([
    checkDatabase(),
    checkRedis(),
    checkApplication(),
  ]);

  const allHealthy = checks.every((result) => result);

  if (allHealthy) {
    console.log('All health checks passed');
    process.exit(0);
  } else {
    console.error('Some health checks failed');
    process.exit(1);
  }
}

main();
```

#### 2. Microservices Architecture

**Best practices for multiple services:**

```yaml
version: '3.8'

x-healthcheck-defaults: &healthcheck-defaults
  interval: 30s
  timeout: 10s
  retries: 3

x-logging-defaults: &logging-defaults
  driver: 'json-file'
  options:
    max-size: '10m'
    max-file: '3'

services:
  # API Gateway
  gateway:
    image: gateway:${VERSION}
    healthcheck:
      <<: *healthcheck-defaults
      test: ['CMD', 'curl', '-f', 'http://localhost:8080/health']
      start_period: 30s
    logging: *logging-defaults
    depends_on:
      auth-service:
        condition: service_healthy
      user-service:
        condition: service_healthy

  # Auth Service
  auth-service:
    image: auth-service:${VERSION}
    healthcheck:
      <<: *healthcheck-defaults
      test: ['CMD', 'curl', '-f', 'http://localhost:8081/health']
      start_period: 45s
    logging: *logging-defaults
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  # User Service
  user-service:
    image: user-service:${VERSION}
    healthcheck:
      <<: *healthcheck-defaults
      test: ['CMD', 'curl', '-f', 'http://localhost:8082/health']
      start_period: 45s
    logging: *logging-defaults
    depends_on:
      postgres:
        condition: service_healthy
```

#### 3. High-Availability Configuration

**For critical production systems:**

```yaml
version: '3.8'

services:
  app:
    image: myapp:${VERSION}
    deploy:
      mode: replicated
      replicas: 3
      restart_policy:
        condition: on-failure
        delay: 5s
        max_attempts: 3
        window: 120s
      update_config:
        parallelism: 1
        delay: 10s
        failure_action: rollback
        monitor: 60s
        order: start-first # Start new before stopping old
      rollback_config:
        parallelism: 1
        delay: 5s
        failure_action: pause
        monitor: 30s
    healthcheck:
      test: ['CMD', 'curl', '-f', 'http://localhost:8080/health']
      interval: 10s # More frequent checks
      timeout: 5s
      start_period: 120s # Longer grace for cluster formation
      retries: 2 # Fewer retries for faster failover
```

---

## Recommendations & Best Practices

### Critical Production Checklist

#### ✅ Must-Have

1. **Healthchecks on ALL services**
   - Including databases, caches, message queues
   - Even if not serving HTTP traffic

2. **Monitoring Stack**
   - Prometheus + Grafana OR ELK/Loki
   - AlertManager configured
   - At least one notification channel (Slack/email)

3. **Proper Timing Configuration**

   ```yaml
   interval: 30s # Standard for most services
   timeout: 10s # Must be < interval
   start_period: 60s # Adjust per service startup time
   retries: 3 # Standard threshold
   ```

4. **Logging Configuration**

   ```yaml
   logging:
     driver: 'json-file'
     options:
       max-size: '10m' # Prevent disk filling
       max-file: '3' # Keep reasonable history
   ```

5. **Resource Limits**
   ```yaml
   deploy:
     resources:
       limits:
         cpus: '2'
         memory: 2G
   ```

#### ⚠️ Common Pitfalls to Avoid

1. **DON'T use external ports in healthchecks**

   ```yaml
   # ❌ Wrong
   test: ["CMD", "curl", "-f", "http://localhost:3000/health"]  # External port
   ports:
     - "3000:8080"

   # ✅ Correct
   test: ["CMD", "curl", "-f", "http://localhost:8080/health"]  # Internal port
   ```

2. **DON'T skip start_period for slow services**

   ```yaml
   # ❌ Wrong - Service takes 2min to start
   healthcheck:
     interval: 30s
     retries: 3
     start_period: 0s  # Will fail 3 times before ready!

   # ✅ Correct
   healthcheck:
     interval: 30s
     retries: 3
     start_period: 120s  # Grace period for startup
   ```

3. **DON'T check downstream dependencies in liveness**

   ```bash
   # ❌ Wrong - Causes cascading failures
   if ! pg_isready; then exit 1; fi
   if ! redis-cli ping; then exit 1; fi
   curl -f http://localhost:8080/health

   # ✅ Correct - Only check this service
   curl -f http://localhost:8080/health
   ```

4. **DON'T forget to install healthcheck dependencies**

   ```dockerfile
   # ❌ Wrong - curl not in alpine
   FROM alpine:latest
   HEALTHCHECK CMD curl -f http://localhost/health

   # ✅ Correct
   FROM alpine:latest
   RUN apk add --no-cache curl
   HEALTHCHECK CMD curl -f http://localhost/health
   ```

5. **DON'T use Docker healthchecks in Kubernetes**

   ```yaml
   # ❌ Wrong - Kubernetes ignores Docker HEALTHCHECK
   apiVersion: v1
   kind: Pod
   spec:
     containers:
       - name: app
         image: myapp:latest  # Has HEALTHCHECK in Dockerfile

   # ✅ Correct - Use Kubernetes probes
   apiVersion: v1
   kind: Pod
   spec:
     containers:
       - name: app
         image: myapp:latest
         livenessProbe:
           httpGet:
             path: /health
             port: 8080
   ```

### Recommended Patterns by Service Type

#### Web Applications

```yaml
healthcheck:
  test: ['CMD', 'curl', '-f', 'http://localhost:8080/health']
  interval: 30s
  timeout: 10s
  start_period: 40s
  retries: 3
```

#### Databases (PostgreSQL)

```yaml
healthcheck:
  test: ['CMD-SHELL', 'pg_isready -U ${POSTGRES_USER}']
  interval: 10s
  timeout: 5s
  start_period: 10s
  retries: 5
```

#### Databases (MySQL)

```yaml
healthcheck:
  test:
    [
      'CMD',
      'mysqladmin',
      'ping',
      '-h',
      'localhost',
      '-u',
      'root',
      '-p${MYSQL_ROOT_PASSWORD}',
    ]
  interval: 10s
  timeout: 5s
  start_period: 30s
  retries: 5
```

#### Cache (Redis)

```yaml
healthcheck:
  test: ['CMD', 'redis-cli', 'ping']
  interval: 10s
  timeout: 5s
  start_period: 5s
  retries: 3
```

#### Message Queue (RabbitMQ)

```yaml
healthcheck:
  test: ['CMD', 'rabbitmq-diagnostics', '-q', 'ping']
  interval: 30s
  timeout: 10s
  start_period: 60s
  retries: 3
```

#### Reverse Proxy (Nginx)

```yaml
healthcheck:
  test:
    [
      'CMD',
      'wget',
      '--quiet',
      '--tries=1',
      '--spider',
      'http://localhost/health',
    ]
  interval: 30s
  timeout: 10s
  start_period: 10s
  retries: 3
```

### Monitoring Maturity Model

#### Level 1: Basic (Minimum for Production)

- ✅ Docker healthchecks on all services
- ✅ `docker ps` shows health status
- ✅ Basic logging to files
- ✅ Manual monitoring

#### Level 2: Standard (Recommended)

- ✅ Prometheus + Grafana
- ✅ Custom health exporter
- ✅ Basic dashboards
- ✅ Email/Slack alerts
- ✅ Log aggregation (Loki or ELK)

#### Level 3: Advanced (Enterprise)

- ✅ Comprehensive metrics (cAdvisor, Node Exporter)
- ✅ Pre-built + custom dashboards
- ✅ Multi-channel alerting (Slack, PagerDuty, email)
- ✅ SLO/SLI tracking
- ✅ Automated remediation
- ✅ Distributed tracing integration

#### Level 4: SRE-Grade (Mature Operations)

- ✅ Error budget tracking
- ✅ Chaos engineering integration
- ✅ Predictive alerts (anomaly detection)
- ✅ Automated runbooks
- ✅ Self-healing systems
- ✅ Capacity planning automation

---

## Summary & Key Takeaways

### The Reality of Docker Healthcheck Observability

**Current State (2024):**

- ✅ Docker healthchecks are **stable and production-ready**
- ❌ **No native Prometheus metrics** for healthcheck status
- ❌ **Limited logging** (4096 bytes, no pipeline integration)
- ⚠️ **Kubernetes ignores Docker healthchecks** entirely

### Required Solutions

To achieve production-grade observability, you MUST implement:

1. **Custom exporters** (gesellix/health-exporter or build your own)
2. **Log aggregation** (Loki or ELK) with structured logging
3. **Monitoring stack** (Prometheus + Grafana + AlertManager)
4. **Alert automation** (Kontrol or custom scripts)

### Quick Start Recommendations

**For small projects:**

```bash
# 1. Add healthchecks to docker-compose.yml
# 2. Use docker-healthcheck-alert for email notifications
# 3. Manually check `docker ps` for status
```

**For production systems:**

```bash
# 1. Deploy full monitoring stack (Prometheus, Grafana, Loki)
# 2. Use custom health exporter for metrics
# 3. Configure AlertManager with multiple channels
# 4. Set up log aggregation
# 5. Define SLOs and track error budgets
```

**For Kubernetes:**

```bash
# 1. IGNORE Docker HEALTHCHECK directive
# 2. Use Kubernetes liveness/readiness/startup probes
# 3. Integrate with native K8s monitoring (Prometheus Operator)
```

### Essential Reading

- Docker Healthcheck Docs:
  https://docs.docker.com/engine/reference/builder/#healthcheck
- Kubernetes Probes:
  https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/
- Google SRE Book: https://sre.google/sre-book/monitoring-distributed-systems/
- Prometheus Best Practices: https://prometheus.io/docs/practices/

---

**Report compiled from 12+ authoritative sources including official
documentation, production case studies, and community best practices.**

**Last Updated:** 2025-11-14
