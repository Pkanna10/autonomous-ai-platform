import typescriptEslint from '@typescript-eslint/eslint-plugin';
import typescriptParser from '@typescript-eslint/parser';
import prettier from 'eslint-plugin-prettier';
import prettierConfig from 'eslint-config-prettier';
import simpleImportSort from 'eslint-plugin-simple-import-sort';
import eslintPluginImport from 'eslint-plugin-import';

export default [
  // Ignore patterns
  {
    ignores: [
      'node_modules/**',
      '**/dist/**',
      '**/build/**',
      '**/coverage/**',
      'documentation_guide/**',
      '**/*.d.ts',
      // Root-level config files (not part of TypeScript project)
      'vitest.config.ts',
      'commitlint.config.ts',
      'eslint.config.js',
      // Note: Package-level configs in src/ are still linted
      // Shell scripts (not TypeScript/JavaScript)
      'scripts/**',
      // Security scan reports
      'trivy-reports/**',
      // Python cache directories
      '**/.mypy_cache/**',
      '**/.ruff_cache/**',
      '**/.tox/**',
      '**/.pytest_cache/**',
      '**/__pycache__/**',
      '**/.cache/**', // UV package manager cache
      '**/htmlcov/**', // Python coverage HTML reports
      // Infrastructure scripts (standalone utilities for Docker)
      'infrastructure/docker/**/*.js',
    ],
  },

  // Base configuration for all files
  {
    files: ['**/*.ts', '**/*.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      parser: typescriptParser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
      globals: {
        console: 'readonly',
        process: 'readonly',
        Buffer: 'readonly',
        __dirname: 'readonly',
        __filename: 'readonly',
        module: 'readonly',
        require: 'readonly',
        exports: 'writable',
      },
    },
    plugins: {
      '@typescript-eslint': typescriptEslint,
      prettier: prettier,
      'simple-import-sort': simpleImportSort,
      import: eslintPluginImport,
    },
    rules: {
      // ========================================
      // TypeScript Rules (STRICT - CLAUDE.md)
      // ========================================

      // NO 'any' types allowed (CRITICAL requirement)
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/no-unsafe-assignment': 'error',
      '@typescript-eslint/no-unsafe-member-access': 'error',
      '@typescript-eslint/no-unsafe-call': 'error',
      '@typescript-eslint/no-unsafe-return': 'error',
      '@typescript-eslint/no-unsafe-argument': 'error',

      // Explicit types required
      '@typescript-eslint/explicit-function-return-type': [
        'error',
        {
          allowExpressions: false,
          allowTypedFunctionExpressions: true,
          allowHigherOrderFunctions: true,
        },
      ],
      '@typescript-eslint/explicit-module-boundary-types': 'error',

      // Type safety
      '@typescript-eslint/strict-boolean-expressions': 'error',
      '@typescript-eslint/no-unnecessary-condition': 'error',
      '@typescript-eslint/no-unnecessary-type-assertion': 'error',
      '@typescript-eslint/prefer-nullish-coalescing': 'error',
      '@typescript-eslint/prefer-optional-chain': 'error',

      // Best practices
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
        },
      ],
      '@typescript-eslint/no-floating-promises': 'error',
      '@typescript-eslint/await-thenable': 'error',
      '@typescript-eslint/no-misused-promises': 'error',
      '@typescript-eslint/promise-function-async': 'error',

      // Code quality
      '@typescript-eslint/prefer-readonly': 'error',
      '@typescript-eslint/consistent-type-definitions': ['error', 'interface'],
      '@typescript-eslint/consistent-type-imports': [
        'error',
        {
          prefer: 'type-imports',
          disallowTypeAnnotations: false,
        },
      ],

      // Naming conventions
      '@typescript-eslint/naming-convention': [
        'error',
        {
          selector: 'default',
          format: ['camelCase'],
          leadingUnderscore: 'allow',
          trailingUnderscore: 'forbid',
        },
        {
          selector: 'variable',
          format: ['camelCase', 'UPPER_CASE'],
          leadingUnderscore: 'allow',
        },
        {
          selector: 'typeLike',
          format: ['PascalCase'],
        },
        {
          selector: 'enumMember',
          format: ['UPPER_CASE'],
        },
        {
          selector: 'interface',
          format: ['PascalCase'],
          custom: {
            regex: '^I[A-Z]',
            match: false, // Don't use "I" prefix for interfaces
          },
        },
      ],

      // ========================================
      // General JavaScript Rules
      // ========================================
      'no-console': ['warn', { allow: ['warn', 'error'] }],
      'no-debugger': 'error',
      'no-alert': 'error',
      'prefer-const': 'error',
      'no-var': 'error',
      eqeqeq: ['error', 'always'],
      curly: ['error', 'all'],
      'no-throw-literal': 'error',

      // ========================================
      // Prettier Integration
      // ========================================
      'prettier/prettier': 'error',

      ...prettierConfig.rules,

      // ========================================
      // Import Sorting (eslint-plugin-simple-import-sort)
      // ========================================
      'simple-import-sort/imports': [
        'error',
        {
          groups: [
            // Side effect imports (polyfills, global styles)
            ['^\\u0000'],

            // Node.js built-ins with node: prefix
            ['^node:'],

            // External packages (npm/pnpm)
            ['^@?\\w'],

            // Internal monorepo packages (@autonomous-ai/*)
            ['^@autonomous-ai/'],

            // Parent imports (../)
            ['^\\.\\.(?!/?$)', '^\\.\\./?$'],

            // Sibling imports (./)
            ['^\\./(?=.*/)(?!/?$)', '^\\.(?!/?$)', '^\\./?$'],

            // Style imports (CSS/SCSS)
            ['^.+\\.s?css$'],
          ],
        },
      ],
      'simple-import-sort/exports': 'error',

      // Disable conflicting rules
      'sort-imports': 'off',

      // ========================================
      // Import Hygiene (eslint-plugin-import)
      // ========================================
      'import/first': 'error',
      'import/newline-after-import': 'error',
      'import/no-duplicates': 'error',
    },
  },

  // Override for test files - disable type-aware rules
  // Test files are excluded from tsconfig to prevent compilation but still need linting
  {
    files: ['**/*.test.ts', '**/*.spec.ts'],
    languageOptions: {
      parser: typescriptParser,
      parserOptions: {
        // Explicitly disable projectService for test files
        projectService: false,
        project: null,
        ecmaVersion: 2022,
        sourceType: 'module',
      },
    },
    rules: {
      // Disable ALL type-aware rules for test files (require type information)
      '@typescript-eslint/no-unsafe-assignment': 'off',
      '@typescript-eslint/no-unsafe-member-access': 'off',
      '@typescript-eslint/no-unsafe-call': 'off',
      '@typescript-eslint/no-unsafe-return': 'off',
      '@typescript-eslint/no-unsafe-argument': 'off',
      '@typescript-eslint/strict-boolean-expressions': 'off',
      '@typescript-eslint/no-unnecessary-condition': 'off',
      '@typescript-eslint/no-unnecessary-type-assertion': 'off',
      '@typescript-eslint/prefer-nullish-coalescing': 'off',
      '@typescript-eslint/prefer-optional-chain': 'off',
      '@typescript-eslint/no-floating-promises': 'off',
      '@typescript-eslint/await-thenable': 'off',
      '@typescript-eslint/no-misused-promises': 'off',
      '@typescript-eslint/promise-function-async': 'off',
      '@typescript-eslint/prefer-readonly': 'off',
      '@typescript-eslint/naming-convention': 'off',
      // Keep basic syntax rules enabled (don't require type info)
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/explicit-function-return-type': 'off', // Too strict for tests
      '@typescript-eslint/explicit-module-boundary-types': 'off', // Too strict for tests
    },
  },
];
