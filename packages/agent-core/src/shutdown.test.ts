/**
 * Comprehensive test suite for graceful shutdown handler
 * Target: 90%+ code coverage
 * Tests: Signal handling, timeouts, cleanup, error recovery
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { Server } from 'http';
import { setupGracefulShutdown, cleanupHelpers } from './shutdown';

describe('setupGracefulShutdown', () => {
  let mockServer: Server;
  let consoleErrorSpy: ReturnType<typeof vi.spyOn>;
  let processExitSpy: ReturnType<typeof vi.spyOn>;
  let processOnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    // Create mock server
    mockServer = {
      close: vi.fn((callback?: (err?: Error) => void) => {
        if (callback) {
          // Simulate async close
          setTimeout(() => callback(), 10);
        }
      }),
    } as unknown as Server;

    // Spy on console.error for log assertions
    consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    // Spy on process.exit to prevent actual exit
    processExitSpy = vi.spyOn(process, 'exit').mockImplementation(() => undefined as never);

    // Spy on process.on to track signal handlers
    processOnSpy = vi.spyOn(process, 'on').mockImplementation(() => process);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.clearAllTimers();
  });

  describe('Signal Handler Registration', () => {
    it('should register SIGTERM and SIGINT handlers by default', () => {
      // ACT
      setupGracefulShutdown(mockServer);

      // ASSERT
      expect(processOnSpy).toHaveBeenCalledWith('SIGTERM', expect.any(Function));
      expect(processOnSpy).toHaveBeenCalledWith('SIGINT', expect.any(Function));
    });

    it('should register custom signals when provided', () => {
      // ARRANGE
      const customSignals: NodeJS.Signals[] = ['SIGUSR1', 'SIGUSR2'];

      // ACT
      setupGracefulShutdown(mockServer, undefined, { signals: customSignals });

      // ASSERT
      expect(processOnSpy).toHaveBeenCalledWith('SIGUSR1', expect.any(Function));
      expect(processOnSpy).toHaveBeenCalledWith('SIGUSR2', expect.any(Function));
      expect(processOnSpy).not.toHaveBeenCalledWith('SIGTERM', expect.any(Function));
    });

    it('should log registration message when logging enabled', () => {
      // ACT
      setupGracefulShutdown(mockServer, undefined, { logging: true });

      // ASSERT
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('Graceful shutdown registered')
      );
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('SIGTERM, SIGINT')
      );
    });

    it('should not log when logging disabled', () => {
      // ACT
      setupGracefulShutdown(mockServer, undefined, { logging: false });

      // ASSERT
      expect(consoleErrorSpy).not.toHaveBeenCalled();
    });
  });

  describe('Graceful Shutdown Flow', () => {
    it('should close server and exit with code 0 on SIGTERM', async () => {
      // ARRANGE
      setupGracefulShutdown(mockServer);
      const signalHandler = (processOnSpy.mock.calls.find(
        (call) => call[0] === 'SIGTERM'
      )?.[1] as () => void) || (() => {});

      // ACT
      signalHandler();
      await new Promise((resolve) => setTimeout(resolve, 50));

      // ASSERT
      expect(mockServer.close).toHaveBeenCalledOnce();
      expect(processExitSpy).toHaveBeenCalledWith(0);
    });

    it('should execute cleanup function before exit', async () => {
      // ARRANGE
      const cleanup = vi.fn().mockResolvedValue(undefined);
      setupGracefulShutdown(mockServer, cleanup);
      const signalHandler = (processOnSpy.mock.calls.find(
        (call) => call[0] === 'SIGTERM'
      )?.[1] as () => void) || (() => {});

      // ACT
      signalHandler();
      await new Promise((resolve) => setTimeout(resolve, 50));

      // ASSERT
      expect(cleanup).toHaveBeenCalledOnce();
      expect(mockServer.close).toHaveBeenCalled();
      expect(processExitSpy).toHaveBeenCalledWith(0);
    });

    it('should log shutdown steps when logging enabled', async () => {
      // ARRANGE
      const cleanup = vi.fn().mockResolvedValue(undefined);
      setupGracefulShutdown(mockServer, cleanup, { logging: true });
      const signalHandler = (processOnSpy.mock.calls.find(
        (call) => call[0] === 'SIGTERM'
      )?.[1] as () => void) || (() => {});

      // ACT
      signalHandler();
      await new Promise((resolve) => setTimeout(resolve, 50));

      // ASSERT
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('Received SIGTERM')
      );
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('Closing HTTP server')
      );
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('Running custom cleanup')
      );
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('Graceful shutdown completed')
      );
    });

    it('should prevent multiple simultaneous shutdowns', async () => {
      // ARRANGE
      const cleanup = vi.fn().mockResolvedValue(undefined);
      setupGracefulShutdown(mockServer, cleanup, { logging: true });
      const signalHandler = (processOnSpy.mock.calls.find(
        (call) => call[0] === 'SIGTERM'
      )?.[1] as () => void) || (() => {});

      // ACT - Trigger shutdown twice rapidly
      signalHandler();
      signalHandler(); // Second call should be ignored
      await new Promise((resolve) => setTimeout(resolve, 50));

      // ASSERT
      expect(mockServer.close).toHaveBeenCalledOnce(); // Not twice
      expect(cleanup).toHaveBeenCalledOnce(); // Not twice
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('Shutdown already in progress')
      );
    });
  });

  describe('Timeout Handling', () => {
    it('should force exit if shutdown exceeds timeout', async () => {
      // ARRANGE - Cleanup takes 2 seconds, timeout is 100ms
      const slowCleanup = vi.fn(
        () => new Promise((resolve) => setTimeout(resolve, 2000))
      );
      setupGracefulShutdown(mockServer, slowCleanup, {
        timeout: 100,
        logging: true,
      });
      const signalHandler = (processOnSpy.mock.calls.find(
        (call) => call[0] === 'SIGTERM'
      )?.[1] as () => void) || (() => {});

      // ACT
      signalHandler();
      await new Promise((resolve) => setTimeout(resolve, 150));

      // ASSERT
      expect(processExitSpy).toHaveBeenCalledWith(1); // Force exit with error code
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('Shutdown timeout after 100ms')
      );
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('Forcing immediate shutdown')
      );
    });

    it('should complete gracefully if within timeout', async () => {
      // ARRANGE - Cleanup takes 10ms, timeout is 1000ms
      const fastCleanup = vi.fn(
        () => new Promise((resolve) => setTimeout(resolve, 10))
      );
      setupGracefulShutdown(mockServer, fastCleanup, { timeout: 1000 });
      const signalHandler = (processOnSpy.mock.calls.find(
        (call) => call[0] === 'SIGTERM'
      )?.[1] as () => void) || (() => {});

      // ACT
      signalHandler();
      await new Promise((resolve) => setTimeout(resolve, 100));

      // ASSERT
      expect(processExitSpy).toHaveBeenCalledWith(0); // Graceful exit
      expect(fastCleanup).toHaveBeenCalledOnce();
    });
  });

  describe('Error Handling', () => {
    it('should exit with code 1 if server.close fails', async () => {
      // ARRANGE - Server close throws error
      const errorServer = {
        close: vi.fn((callback?: (err?: Error) => void) => {
          if (callback) {
            setTimeout(() => callback(new Error('Server close failed')), 10);
          }
        }),
      } as unknown as Server;

      setupGracefulShutdown(errorServer, undefined, { logging: true });
      const signalHandler = (processOnSpy.mock.calls.find(
        (call) => call[0] === 'SIGTERM'
      )?.[1] as () => void) || (() => {});

      // ACT
      signalHandler();
      await new Promise((resolve) => setTimeout(resolve, 50));

      // ASSERT
      expect(processExitSpy).toHaveBeenCalledWith(1);
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('Graceful shutdown failed')
      );
    });

    it('should exit with code 1 if cleanup throws error', async () => {
      // ARRANGE - Cleanup throws error
      const failingCleanup = vi.fn().mockRejectedValue(new Error('Cleanup failed'));
      setupGracefulShutdown(mockServer, failingCleanup, { logging: true });
      const signalHandler = (processOnSpy.mock.calls.find(
        (call) => call[0] === 'SIGTERM'
      )?.[1] as () => void) || (() => {});

      // ACT
      signalHandler();
      await new Promise((resolve) => setTimeout(resolve, 50));

      // ASSERT
      expect(processExitSpy).toHaveBeenCalledWith(1);
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('Graceful shutdown failed: Cleanup failed')
      );
    });

    it('should handle non-Error exceptions', async () => {
      // ARRANGE - Cleanup throws non-Error object
      const failingCleanup = vi.fn().mockRejectedValue('String error');
      setupGracefulShutdown(mockServer, failingCleanup, { logging: true });
      const signalHandler = (processOnSpy.mock.calls.find(
        (call) => call[0] === 'SIGTERM'
      )?.[1] as () => void) || (() => {});

      // ACT
      signalHandler();
      await new Promise((resolve) => setTimeout(resolve, 50));

      // ASSERT
      expect(processExitSpy).toHaveBeenCalledWith(1);
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('Unknown error')
      );
    });
  });

  describe('Cleanup without async', () => {
    it('should handle synchronous cleanup functions', async () => {
      // ARRANGE - Synchronous cleanup (no promise)
      const syncCleanup = vi.fn();
      setupGracefulShutdown(mockServer, syncCleanup);
      const signalHandler = (processOnSpy.mock.calls.find(
        (call) => call[0] === 'SIGTERM'
      )?.[1] as () => void) || (() => {});

      // ACT
      signalHandler();
      await new Promise((resolve) => setTimeout(resolve, 50));

      // ASSERT
      expect(syncCleanup).toHaveBeenCalledOnce();
      expect(processExitSpy).toHaveBeenCalledWith(0);
    });

    it('should work without cleanup function', async () => {
      // ARRANGE - No cleanup provided
      setupGracefulShutdown(mockServer);
      const signalHandler = (processOnSpy.mock.calls.find(
        (call) => call[0] === 'SIGTERM'
      )?.[1] as () => void) || (() => {});

      // ACT
      signalHandler();
      await new Promise((resolve) => setTimeout(resolve, 50));

      // ASSERT
      expect(mockServer.close).toHaveBeenCalledOnce();
      expect(processExitSpy).toHaveBeenCalledWith(0);
    });
  });
});

describe('cleanupHelpers', () => {
  let consoleErrorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('postgres helper', () => {
    it('should create cleanup function that closes PostgreSQL client', async () => {
      // ARRANGE
      const mockPgClient = {
        end: vi.fn().mockResolvedValue(undefined),
      };
      const cleanup = cleanupHelpers.postgres(mockPgClient);

      // ACT
      await cleanup();

      // ASSERT
      expect(mockPgClient.end).toHaveBeenCalledOnce();
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('Closing PostgreSQL connection')
      );
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('PostgreSQL connection closed')
      );
    });

    it('should handle PostgreSQL client close errors', async () => {
      // ARRANGE
      const mockPgClient = {
        end: vi.fn().mockRejectedValue(new Error('PG close failed')),
      };
      const cleanup = cleanupHelpers.postgres(mockPgClient);

      // ACT & ASSERT
      await expect(cleanup()).rejects.toThrow('PG close failed');
      expect(mockPgClient.end).toHaveBeenCalledOnce();
    });
  });

  describe('redis helper', () => {
    it('should create cleanup function that closes Redis client', async () => {
      // ARRANGE
      const mockRedisClient = {
        quit: vi.fn().mockResolvedValue(undefined),
      };
      const cleanup = cleanupHelpers.redis(mockRedisClient);

      // ACT
      await cleanup();

      // ASSERT
      expect(mockRedisClient.quit).toHaveBeenCalledOnce();
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('Closing Redis connection')
      );
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('Redis connection closed')
      );
    });

    it('should handle Redis client quit errors', async () => {
      // ARRANGE
      const mockRedisClient = {
        quit: vi.fn().mockRejectedValue(new Error('Redis quit failed')),
      };
      const cleanup = cleanupHelpers.redis(mockRedisClient);

      // ACT & ASSERT
      await expect(cleanup()).rejects.toThrow('Redis quit failed');
      expect(mockRedisClient.quit).toHaveBeenCalledOnce();
    });
  });

  describe('combine helper', () => {
    it('should execute multiple cleanup functions in sequence', async () => {
      // ARRANGE
      const cleanup1 = vi.fn().mockResolvedValue(undefined);
      const cleanup2 = vi.fn().mockResolvedValue(undefined);
      const cleanup3 = vi.fn().mockResolvedValue(undefined);
      const combined = cleanupHelpers.combine(cleanup1, cleanup2, cleanup3);

      // ACT
      await combined();

      // ASSERT
      expect(cleanup1).toHaveBeenCalledOnce();
      expect(cleanup2).toHaveBeenCalledOnce();
      expect(cleanup3).toHaveBeenCalledOnce();

      // Verify sequential execution (each completes before next starts)
      const order = [cleanup1, cleanup2, cleanup3].map((fn) => fn.mock.invocationCallOrder[0]);
      expect(order[0]).toBeLessThan(order[1]);
      expect(order[1]).toBeLessThan(order[2]);
    });

    it('should stop on first cleanup error', async () => {
      // ARRANGE
      const cleanup1 = vi.fn().mockResolvedValue(undefined);
      const cleanup2 = vi.fn().mockRejectedValue(new Error('Cleanup 2 failed'));
      const cleanup3 = vi.fn().mockResolvedValue(undefined);
      const combined = cleanupHelpers.combine(cleanup1, cleanup2, cleanup3);

      // ACT & ASSERT
      await expect(combined()).rejects.toThrow('Cleanup 2 failed');
      expect(cleanup1).toHaveBeenCalledOnce();
      expect(cleanup2).toHaveBeenCalledOnce();
      expect(cleanup3).not.toHaveBeenCalled(); // Should not reach cleanup3
    });

    it('should work with synchronous cleanup functions', async () => {
      // ARRANGE
      const cleanup1 = vi.fn();
      const cleanup2 = vi.fn();
      const combined = cleanupHelpers.combine(cleanup1, cleanup2);

      // ACT
      await combined();

      // ASSERT
      expect(cleanup1).toHaveBeenCalledOnce();
      expect(cleanup2).toHaveBeenCalledOnce();
    });

    it('should work with empty cleanup list', async () => {
      // ARRANGE
      const combined = cleanupHelpers.combine();

      // ACT & ASSERT
      await expect(combined()).resolves.toBeUndefined();
    });

    it('should work with real PostgreSQL and Redis clients combined', async () => {
      // ARRANGE - Simulates real-world usage
      const mockPgClient = { end: vi.fn().mockResolvedValue(undefined) };
      const mockRedisClient = { quit: vi.fn().mockResolvedValue(undefined) };

      const combined = cleanupHelpers.combine(
        cleanupHelpers.postgres(mockPgClient),
        cleanupHelpers.redis(mockRedisClient)
      );

      // ACT
      await combined();

      // ASSERT
      expect(mockPgClient.end).toHaveBeenCalledOnce();
      expect(mockRedisClient.quit).toHaveBeenCalledOnce();
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('PostgreSQL')
      );
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('Redis')
      );
    });
  });
});
