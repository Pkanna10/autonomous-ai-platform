import { defineConfig } from 'vitest/config';
import path from 'path';

/**
 * Shared Vitest configuration for the monorepo.
 *
 * This configuration is used by both the root vitest.config.ts and
 * individual package-level configs to ensure consistency across the monorepo.
 *
 * Key features:
 * - 90%+ coverage thresholds (MANDATORY per CLAUDE.md TDD requirements)
 * - Node environment for backend testing
 * - Package aliases for cross-package imports
 * - JUnit reporter for CI integration
 */
export const sharedConfig = defineConfig({
  test: {
    // Test environment - Node.js for backend services
    environment: 'node',

    // Global setup - enables global test APIs (describe, it, expect, etc.)
    globals: true,

    // Test timeout: 2 minutes (per CLAUDE.md)
    testTimeout: 120000,

    // Hook timeouts: 1 minute
    hookTimeout: 60000,

    // Coverage configuration (v8 provider - fastest for TypeScript)
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html', 'lcov'],

      // MANDATORY 90%+ coverage thresholds (CLAUDE.md requirement)
      thresholds: {
        lines: 90,
        functions: 90,
        branches: 90,
        statements: 90,
      },

      // Include all source files for accurate coverage reporting
      include: ['packages/*/src/**/*.ts', 'apps/*/src/**/*.ts', 'services/*/src/**/*.ts'],

      // Exclude non-production code from coverage
      exclude: [
        '**/*.test.ts',
        '**/*.spec.ts',
        '**/*.d.ts',
        '**/node_modules/**',
        '**/dist/**',
        '**/build/**',
        '**/test/**',
        '**/tests/**',
        '**/*.config.ts',
        '**/test-setup.ts',
        '**/index.ts', // Barrel exports typically just re-export
      ],
    },

    // Parallel execution for faster test runs
    pool: 'threads',

    // Disable watch mode by default (enable manually with --watch)
    watch: false,

    // Reporters configuration
    // Note: Root config overrides this for CI-specific JUnit output
    reporters: ['default', 'verbose'],
  },

  // Resolve aliases for monorepo packages
  // This allows tests to import from other packages using clean paths
  resolve: {
    /* eslint-disable @typescript-eslint/naming-convention -- Package names use kebab-case with @ scope */
    alias: {
      '@autonomous-ai/agent-core': path.resolve(__dirname, './packages/agent-core/src'),
      '@autonomous-ai/research-engine': path.resolve(__dirname, './packages/research-engine/src'),
      '@autonomous-ai/execution-engine': path.resolve(__dirname, './packages/execution-engine/src'),
    },
    /* eslint-enable @typescript-eslint/naming-convention */
  },
});
