/**
 * Graceful Shutdown Handler for Node.js Applications
 *
 * Proposal #11: Proper signal handling for Docker containers
 * Ensures clean shutdown when receiving SIGTERM/SIGINT signals
 *
 * Benefits:
 * - Prevents data loss by completing in-flight requests
 * - Closes database connections gracefully
 * - Drains queues before exit
 * - Prevents zombie processes in Docker
 *
 * Usage:
 * ```typescript
 * import { setupGracefulShutdown } from './shutdown';
 *
 * const server = app.listen(3000);
 * setupGracefulShutdown(server, async () => {
 *   await db.disconnect();
 *   await redis.quit();
 * });
 * ```
 */

import type { Server } from 'http';

interface ShutdownOptions {
  /**
   * Maximum time to wait for graceful shutdown (milliseconds)
   * Default: 30000 (30 seconds)
   */
  timeout?: number;

  /**
   * Signals to listen for
   * Default: ['SIGTERM', 'SIGINT']
   */
  signals?: NodeJS.Signals[];

  /**
   * Whether to log shutdown events
   * Default: true
   */
  logging?: boolean;
}

type CleanupFunction = () => Promise<void> | void;

/**
 * Setup graceful shutdown for HTTP server with custom cleanup
 *
 * @param server - HTTP server instance
 * @param cleanup - Async function to run cleanup tasks (close DB, etc.)
 * @param options - Shutdown configuration options
 */
export function setupGracefulShutdown(
  server: Server,
  cleanup?: CleanupFunction,
  options: ShutdownOptions = {}
): void {
  const { timeout = 30000, signals = ['SIGTERM', 'SIGINT'], logging = true } = options;

  let isShuttingDown = false;

  const log = (message: string): void => {
    if (logging) {
      console.error(`[Shutdown] ${message}`);
    }
  };

  const shutdown = async (signal: string): Promise<void> => {
    // Prevent multiple shutdown attempts
    if (isShuttingDown) {
      log('Shutdown already in progress, ignoring signal');
      return;
    }

    isShuttingDown = true;
    log(`Received ${signal}, starting graceful shutdown...`);

    // Create timeout promise
    const timeoutPromise = new Promise<never>((_, reject): void => {
      setTimeout((): void => {
        reject(new Error(`Shutdown timeout after ${timeout}ms`));
      }, timeout);
    });

    try {
      // Race between graceful shutdown and timeout
      await Promise.race([
        (async (): Promise<void> => {
          // 1. Stop accepting new connections
          log('Closing HTTP server (no new connections)...');
          await new Promise<void>((resolve, reject): void => {
            server.close((err): void => {
              if (err) {
                reject(err);
              } else {
                resolve();
              }
            });
          });
          log('HTTP server closed');

          // 2. Run custom cleanup (database, redis, etc.)
          if (cleanup) {
            log('Running custom cleanup tasks...');
            await cleanup();
            log('Cleanup tasks completed');
          }

          // 3. Wait a bit for in-flight requests to complete
          log('Waiting for in-flight requests to complete...');
          await new Promise<void>((resolve): void => {
            setTimeout(resolve, 1000);
          });
        })(),
        timeoutPromise,
      ]);

      log('Graceful shutdown completed successfully');
      process.exit(0);
    } catch (error) {
      if (error instanceof Error) {
        log(`Graceful shutdown failed: ${error.message}`);
      } else {
        log('Graceful shutdown failed: Unknown error');
      }

      // Force exit if graceful shutdown fails
      log('Forcing immediate shutdown...');
      process.exit(1);
    }
  };

  // Register signal handlers
  signals.forEach((signal) => {
    process.on(signal, () => {
      void shutdown(signal);
    });
  });

  log(`Graceful shutdown registered for signals: ${signals.join(', ')} (timeout: ${timeout}ms)`);
}

/**
 * Cleanup function factory for common resources
 * Use these helpers to create cleanup functions for setupGracefulShutdown
 */
export const cleanupHelpers = {
  /**
   * Create cleanup function for PostgreSQL client
   */
  postgres: (client: { end: () => Promise<void> }): CleanupFunction => {
    return async (): Promise<void> => {
      console.error('[Cleanup] Closing PostgreSQL connection...');
      await client.end();
      console.error('[Cleanup] PostgreSQL connection closed');
    };
  },

  /**
   * Create cleanup function for Redis client
   */
  redis: (client: { quit: () => Promise<void> }): CleanupFunction => {
    return async (): Promise<void> => {
      console.error('[Cleanup] Closing Redis connection...');
      await client.quit();
      console.error('[Cleanup] Redis connection closed');
    };
  },

  /**
   * Combine multiple cleanup functions
   */
  combine: (...cleanups: CleanupFunction[]): CleanupFunction => {
    return async (): Promise<void> => {
      for (const cleanup of cleanups) {
        await cleanup();
      }
    };
  },
};

/**
 * Example usage:
 *
 * ```typescript
 * import express from 'express';
 * import { Client } from 'pg';
 * import { createClient } from 'redis';
 * import { setupGracefulShutdown, cleanupHelpers } from './shutdown';
 *
 * const app = express();
 * const pgClient = new Client({ ... });
 * const redisClient = createClient({ ... });
 *
 * // Setup routes
 * app.get('/health', (req, res) => res.json({ status: 'healthy' }));
 *
 * // Start server
 * const server = app.listen(3000, () => {
 *   console.log('Server listening on port 3000');
 * });
 *
 * // Setup graceful shutdown with cleanup
 * setupGracefulShutdown(
 *   server,
 *   cleanupHelpers.combine(
 *     cleanupHelpers.postgres(pgClient),
 *     cleanupHelpers.redis(redisClient)
 *   ),
 *   { timeout: 30000 }
 * );
 * ```
 */
