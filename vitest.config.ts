import { defineConfig } from 'vitest/config';
import path from 'path';

export default defineConfig({
  test: {
    // Test environment
    environment: 'node',

    // Test file patterns
    include: [
      'packages/**/*.test.ts',
      'packages/**/*.spec.ts',
      'apps/**/*.test.ts',
      'apps/**/*.spec.ts',
      'services/**/*.test.ts',
      'services/**/*.spec.ts',
    ],

    // Exclude patterns
    exclude: [
      '**/node_modules/**',
      '**/dist/**',
      '**/build/**',
      '**/.{idea,git,cache,output,temp}/**',
    ],

    // Coverage configuration (CLAUDE.md: 90%+ requirement)
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html', 'lcov'],

      // 90%+ coverage thresholds (MANDATORY per CLAUDE.md)
      thresholds: {
        lines: 90,
        functions: 90,
        branches: 90,
        statements: 90,
      },

      // Include all source files
      include: [
        'packages/*/src/**/*.ts',
        'apps/*/src/**/*.ts',
        'services/*/src/**/*.ts',
      ],

      // Exclude non-production code
      exclude: [
        '**/*.test.ts',
        '**/*.spec.ts',
        '**/*.d.ts',
        '**/node_modules/**',
        '**/dist/**',
        '**/test/**',
        '**/tests/**',
        '**/*.config.ts',
        '**/test-setup.ts',
        '**/index.ts',
      ],
    },

    // Global setup
    globals: true,

    // Test timeout (2 minutes as per CLAUDE.md)
    testTimeout: 120000,

    // Hook timeouts
    hookTimeout: 60000,

    // Reporters (add JUnit for CI environments)
    reporters: process.env.CI ? ['default', 'verbose', 'junit'] : ['default', 'verbose'],

    // Output files for reporters
    outputFile: {
      junit: './coverage/junit.xml',
    },

    // Watch mode
    watch: false,

    // Parallel execution
    pool: 'threads',
  },

  // Resolve aliases for monorepo packages
  resolve: {
    alias: {
      '@autonomous-ai/agent-core': path.resolve(__dirname, './packages/agent-core/src'),
      '@autonomous-ai/research-engine': path.resolve(__dirname, './packages/research-engine/src'),
      '@autonomous-ai/execution-engine': path.resolve(__dirname, './packages/execution-engine/src'),
    },
  },
});
