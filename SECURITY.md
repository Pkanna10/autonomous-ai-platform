# Security Scanning & Best Practices

This document outlines the security infrastructure for the Autonomous AI
Platform, including automated scanning tools, vulnerability management
workflows, and security best practices.

---

## 📋 Table of Contents

1. [Security Tools Overview](#security-tools-overview)
2. [Local Security Scanning](#local-security-scanning)
3. [CI/CD Security Workflows](#cicd-security-workflows)
4. [Vulnerability Management](#vulnerability-management)
5. [Docker Image Security](#docker-image-security)
6. [Dependency Management](#dependency-management)
7. [Security Best Practices](#security-best-practices)
8. [Incident Response](#incident-response)

---

## 🔒 Security Tools Overview

| Tool            | Purpose                            | Frequency                 | Cost | Automation |
| --------------- | ---------------------------------- | ------------------------- | ---- | ---------- |
| **pnpm audit**  | Built-in npm vulnerability scanner | Every commit (pre-commit) | FREE | Automated  |
| **OSV-Scanner** | Google's vulnerability database    | Weekly + PR               | FREE | Automated  |
| **Trivy**       | Container & IaC security scanner   | Weekly + PR               | FREE | Automated  |
| **Dependabot**  | Automated dependency updates       | Weekly                    | FREE | Automated  |
| **Renovate**    | Advanced dependency updates        | Weekly                    | FREE | Automated  |
| **Commitlint**  | Commit message validation          | Every commit              | FREE | Automated  |
| **ESLint**      | Code quality & security linting    | Every commit              | FREE | Automated  |

---

## 💻 Local Security Scanning

### Quick Commands

```bash
# Run all security scans
pnpm security

# Individual scans
pnpm security:audit      # npm audit (fast, built-in)
pnpm security:scan       # Comprehensive scan (Trivy, OSV-Scanner, gitleaks)
pnpm security:docker     # Docker image security scan
pnpm security:trivy      # Full Trivy scan with detailed report
pnpm security:osv        # OSV-Scanner (Google's vulnerability database)

# Fix vulnerabilities automatically
pnpm security:fix        # Auto-fix patchable vulnerabilities
```

### Pre-Commit Security Checks

Automated security checks run before every commit:

1. **ESLint** - Catches security anti-patterns
2. **TypeScript** - Type safety prevents runtime errors
3. **Prettier** - Consistent code formatting
4. **Vitest** - 90%+ test coverage enforced

### Manual Comprehensive Scan

Run before pushing to production:

```bash
# Full security audit (takes 2-5 minutes)
bash scripts/security-scan.sh

# Docker-specific security check
bash scripts/docker-security-scan.sh

# Trivy with enhanced reporting
bash scripts/trivy-scan-full.sh
```

**Output Location:** `./trivy-reports/`

---

## 🤖 CI/CD Security Workflows

### GitHub Actions Workflows

#### 1. CI Workflow (`.github/workflows/ci.yml`)

Runs on every push and PR:

- TypeScript type checking, linting, testing
- Python linting (Ruff), formatting (Black), type checking (Mypy)
- npm audit for known vulnerabilities
- Trivy configuration scanning

#### 2. Security Workflow (`.github/workflows/security.yml`)

Runs weekly (Monday 9am UTC) and on PR:

- **OSV-Scanner** - Google's comprehensive vulnerability database (FREE)
- **npm Audit** - Built-in npm vulnerability scanner (FREE)
- **License Compliance Check** - OSS license verification (FREE)

#### 3. Dependabot (`.github/dependabot.yml`)

Automated dependency updates:

- **npm Dependencies** - Weekly updates for all packages
- **Docker Images** - Weekly updates for container images
- **GitHub Actions** - Weekly updates for workflow dependencies
- Runs every Monday at 3am PT with automated grouping

#### 4. Trivy Docker Security

Runs on every push/PR with enhanced reporting:

- Scans HIGH/CRITICAL separately from MEDIUM/LOW
- Generates detailed summary with badges
- Uploads artifacts for 30-day retention
- Fails build on CRITICAL/HIGH vulnerabilities

---

## 🚨 Vulnerability Management

### Severity Levels

| Severity     | Response Time     | Action                             |
| ------------ | ----------------- | ---------------------------------- |
| **CRITICAL** | Immediate (< 24h) | Block deployment, emergency patch  |
| **HIGH**     | 1 week            | Scheduled fix in next sprint       |
| **MEDIUM**   | 1 month           | Include in regular updates         |
| **LOW**      | 3 months          | Informational, fix when convenient |

### Vulnerability Response Workflow

1. **Detection:**
   - Automated: OSV-Scanner, Dependabot, Renovate, GitHub Security Alerts
   - Manual: Security scan reports, penetration testing

2. **Assessment:**

   ```bash
   # View details
   cat trivy-reports/trivy-summary-latest.md

   # Check OSV-Scanner results
   pnpm security:osv

   # Check npm audit
   pnpm audit --audit-level=high
   ```

3. **Remediation:**

   ```bash
   # Auto-fix (if available)
   pnpm security:fix

   # Manual updates
   pnpm update <package>@latest

   # Verify fix
   pnpm test && pnpm security:audit
   ```

4. **Verification:**
   - Run full test suite: `pnpm test`
   - Run security scan: `pnpm security:scan`
   - Manual verification in staging environment

5. **Documentation:**
   - Document exceptions in SECURITY.md (if false positive)
   - Add to changelog
   - Create GitHub Security Advisory (if critical)

### Exception Handling

For false positives or accepted risks, document in project documentation
(SECURITY.md):

```markdown
## Known Issues (Accepted Risks)

### CVE-2024-XXXXX (minimist)

- **Severity**: LOW reason: 'Dev dependency only, not exploitable in our use
  case' expires: '2025-12-31T00:00:00.000Z'
```

---

## 🐳 Docker Image Security

### Scanning Docker Images

```bash
# Scan all docker-compose images
pnpm security:docker

# Scan specific image
trivy image pgvector/pgvector:pg15

# Get JSON report for analysis
trivy image --format json --output postgres-scan.json pgvector/pgvector:pg15
```

### Docker Security Best Practices

1. **Use Official Images:**
   - ✅ `pgvector/pgvector:pg15` (official PostgreSQL + extension)
   - ✅ `redis:7-alpine` (official Redis, minimal Alpine variant)
   - ✅ `qdrant/qdrant:latest` (official Qdrant)

2. **Pin Versions:**
   - Avoid `latest` tag in production
   - Use specific version tags: `postgres:15.3-alpine`

3. **Minimize Attack Surface:**
   - Use Alpine-based images when possible
   - Remove unnecessary packages
   - Run as non-root user

4. **Regular Updates:**
   - Renovate automatically updates Docker images
   - Review and merge Renovate PRs weekly

### Docker Compose Security

```yaml
# Good practices in docker-compose.dev.yml
services:
  postgres:
    image: pgvector/pgvector:pg15 # Specific version
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-dev} # From .env
    networks:
      - backend # Isolated network
    restart: unless-stopped # Auto-restart on failure
```

---

## 📦 Dependency Management

### Automated Dependency Updates (Renovate)

Renovate runs weekly (Monday 3am PT) and:

- Creates grouped PRs for related dependencies
- Auto-merges security patches after 3 days
- Prioritizes security updates (runs any time)
- Monitors Docker images for updates

**Dashboard:** See `Issues` tab for "🔄 Dependency Updates Dashboard"

### Manual Dependency Updates

```bash
# Check for outdated packages
pnpm outdated

# Update all to latest (caution: breaking changes)
pnpm update --latest

# Update specific package
pnpm update <package>@latest

# Update Python dependencies
cd services/python_agents
pip list --outdated
pip install --upgrade <package>
```

### Dependency Review Checklist

Before merging dependency updates:

- [ ] Review changelog for breaking changes
- [ ] Check security advisories
- [ ] Run full test suite: `pnpm test`
- [ ] Verify build: `pnpm build`
- [ ] Test in local development environment
- [ ] Review license compatibility

---

## 🛡️ Security Best Practices

### Code Security

1. **No Secrets in Code:**
   - Use `.env` files (excluded from git)
   - Use environment variables
   - Never commit API keys, passwords, tokens

2. **Input Validation:**
   - Validate all user inputs
   - Use TypeScript types for compile-time safety
   - Sanitize data before database queries

3. **Secure Dependencies:**
   - Review new dependencies before adding
   - Prefer well-maintained packages (high star count, recent updates)
   - Check security advisories

4. **Error Handling:**
   - Never expose internal errors to users
   - Log errors for debugging
   - Use custom error classes

### Infrastructure Security

1. **Least Privilege:**
   - Database users have minimal permissions
   - Docker containers run as non-root
   - API keys scoped to specific services

2. **Network Isolation:**
   - Docker networks isolate services
   - Firewall rules restrict access
   - TLS/SSL for all external communication

3. **Secrets Management:**
   - Use HashiCorp Vault (production)
   - GitHub Secrets for CI/CD
   - `.env` for local development only

4. **Monitoring & Logging:**
   - Log all authentication attempts
   - Monitor for suspicious activity
   - Set up alerts for security events

### Development Workflow Security

1. **Branch Protection:**
   - Require PR reviews
   - Require status checks to pass
   - No force pushes to main/master

2. **Code Review:**
   - Security-focused code reviews
   - Check for SQL injection, XSS, CSRF
   - Verify proper error handling

3. **Testing:**
   - 90%+ test coverage mandatory
   - Security-specific test cases
   - Penetration testing for critical features

---

## 🚑 Incident Response

### Security Incident Procedure

1. **Identify:**
   - Security alert from Snyk/GitHub
   - User report
   - Automated monitoring alert

2. **Assess:**
   - Severity classification (CRITICAL/HIGH/MEDIUM/LOW)
   - Impact analysis (data breach, service disruption)
   - Scope determination

3. **Contain:**
   - Isolate affected systems
   - Revoke compromised credentials
   - Block malicious traffic

4. **Remediate:**
   - Apply security patches
   - Update vulnerable dependencies
   - Fix security vulnerabilities

5. **Recover:**
   - Restore from backups (if needed)
   - Verify system integrity
   - Resume normal operations

6. **Document:**
   - Incident report
   - Root cause analysis
   - Lessons learned

### Emergency Contacts

- **Project Maintainer:** [GitHub @username]
- **Security Email:** security@your-domain.com (if applicable)
- **GitHub Security Advisory:** Use "Security" tab to report privately

### Reporting Security Vulnerabilities

**DO NOT** create public GitHub issues for security vulnerabilities.

**Instead:**

1. Use GitHub Security Advisories (private disclosure)
2. Email: security@your-domain.com
3. Provide: Description, reproduction steps, impact assessment

**Response Time:** Within 48 hours for acknowledgment

---

## 📚 Additional Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Snyk Vulnerability Database](https://security.snyk.io/)
- [GitHub Security Advisories](https://github.com/advisories)
- [Trivy Documentation](https://aquasecurity.github.io/trivy/)
- [Node.js Security Best Practices](https://nodejs.org/en/docs/guides/security/)
- [Docker Security Best Practices](https://docs.docker.com/engine/security/)

---

**Last Updated:** 2025-11-04 **Version:** 1.0.0
