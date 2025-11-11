import { mergeConfig } from 'vitest/config';
import { sharedConfig } from './vitest.shared';

/**
 * Root Vitest configuration for the monorepo.
 *
 * Extends the shared configuration from vitest.shared.ts with root-specific settings:
 * - Test file patterns (include/exclude)
 * - CI-specific reporters (JUnit XML)
 * - Output file locations
 *
 * For package-level configs, import and extend sharedConfig in the same way.
 */
export default mergeConfig(sharedConfig, {
  test: {
    // Root-specific: Test file patterns across all packages
    include: [
      'packages/**/*.test.ts',
      'packages/**/*.spec.ts',
      'apps/**/*.test.ts',
      'apps/**/*.spec.ts',
      'services/**/*.test.ts',
      'services/**/*.spec.ts',
    ],

    // Root-specific: Exclude patterns for common directories
    exclude: [
      '**/node_modules/**',
      '**/dist/**',
      '**/build/**',
      '**/.{idea,git,cache,output,temp}/**',
    ],

    // Root-specific: Reporters
    // - CI: default + verbose + junit (for GitHub Actions test annotations)
    // - Local: default + verbose (for detailed test output)
    // Using inline format to keep reporter config together
    reporters: process.env['CI']
      ? ['default', 'verbose', ['junit', { outputFile: './coverage/junit.xml' }]]
      : ['default', 'verbose'],
  },
});
