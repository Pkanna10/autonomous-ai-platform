/**
 * Docker Healthcheck Script for Node.js Application
 *
 * This script performs an HTTP health check against the application's /health endpoint.
 * Returns exit code 0 (healthy) or 1 (unhealthy) for Docker to interpret.
 *
 * For library packages (no HTTP server), performs a simple process check instead.
 *
 * Proposal #7: Native Node.js healthcheck (no curl/wget dependencies needed)
 *
 * Usage in Dockerfile:
 *   HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
 *     CMD node healthcheck.js
 */

const http = require('http');
const fs = require('fs');
const path = require('path');

// ==================================================================================
// Package Type Detection
// ==================================================================================
// Detect if this is a library package or a service
// Libraries: Export classes/functions (no HTTP server)
// Services: Run HTTP servers or long-lived processes

const pkgPath = path.join(__dirname, 'package.json');
let isService = false;

try {
  const pkgData = fs.readFileSync(pkgPath, 'utf8');
  const pkg = JSON.parse(pkgData);

  // Service indicators:
  // 1. Has a "start" script (services have npm start)
  // 2. Has HTTP framework dependencies (express, fastify, koa, etc.)
  // 3. Has explicit packageType field set to "service"
  isService = Boolean(
    pkg.packageType === 'service' ||
      pkg.scripts?.start ||
      pkg.dependencies?.express ||
      pkg.dependencies?.fastify ||
      pkg.dependencies?.koa ||
      pkg.dependencies?.hapi ||
      pkg.dependencies?.['@hapi/hapi']
  );

  console.log(`[Healthcheck] Package: ${pkg.name || 'unknown'}`);
  console.log(`[Healthcheck] Type: ${isService ? 'service' : 'library'}`);
  console.log(`[Healthcheck] PACKAGE_SCOPE: ${process.env.PACKAGE_SCOPE || 'not set'}`);
} catch (err) {
  console.error('[Healthcheck] ⚠️  Failed to read package.json:', err.message);
  console.error('[Healthcheck] Defaulting to library mode (simple process check)');
  isService = false;
}

// ==================================================================================
// Library Package Healthcheck (Simple Process Check)
// ==================================================================================
// For library packages, we just verify Node.js is running
// No HTTP server needed - the process being alive is sufficient

if (!isService) {
  console.log('[Healthcheck] ✅ Library package - process is healthy');
  console.log(`[Healthcheck] Node version: ${process.version}`);
  console.log(`[Healthcheck] Uptime: ${process.uptime().toFixed(2)}s`);
  console.log(
    `[Healthcheck] Memory: ${Math.round(process.memoryUsage().heapUsed / 1024 / 1024)}MB`
  );
  process.exit(0);
}

// ==================================================================================
// Service Package Healthcheck (HTTP Endpoint Check)
// ==================================================================================
// For services, perform HTTP health check on /health endpoint

console.log('[Healthcheck] Service package detected - checking HTTP endpoint');

const options = {
  host: process.env.HOST || 'localhost',
  port: process.env.PORT || 3000,
  path: process.env.HEALTH_PATH || '/health',
  method: 'GET',
  timeout: 5000, // 5 second timeout
};

const request = http.request(options, (res) => {
  console.log(`[Healthcheck] Status: ${res.statusCode}`);

  let data = '';
  res.on('data', (chunk) => {
    data += chunk;
  });

  res.on('end', () => {
    if (res.statusCode === 200) {
      try {
        const health = JSON.parse(data);
        console.log('[Healthcheck] Response:', JSON.stringify(health));

        // Check if response indicates healthy status
        if (health.status === 'healthy' || health.status === 'ok') {
          console.log('[Healthcheck] ✅ Application is healthy');
          process.exit(0); // Success
        } else {
          console.error('[Healthcheck] ❌ Application reports unhealthy status:', health.status);
          process.exit(1); // Unhealthy
        }
      } catch (err) {
        // If response isn't JSON, accept any 200 status
        console.log('[Healthcheck] ✅ Application responded with 200 (non-JSON response)');
        process.exit(0);
      }
    } else {
      console.error(`[Healthcheck] ❌ Unhealthy status code: ${res.statusCode}`);
      process.exit(1); // Unhealthy
    }
  });
});

request.on('error', (err) => {
  console.error('[Healthcheck] ❌ Request failed:', err.message);
  process.exit(1); // Unhealthy
});

request.on('timeout', () => {
  console.error('[Healthcheck] ❌ Request timeout');
  request.destroy();
  process.exit(1); // Unhealthy
});

request.end();
