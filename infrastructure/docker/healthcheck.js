/**
 * Docker Healthcheck Script for Node.js Application
 *
 * This script performs an HTTP health check against the application's /health endpoint.
 * Returns exit code 0 (healthy) or 1 (unhealthy) for Docker to interpret.
 *
 * Proposal #7: Native Node.js healthcheck (no curl/wget dependencies needed)
 *
 * Usage in Dockerfile:
 *   HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
 *     CMD node healthcheck.js
 */

const http = require('http');

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
