const config = {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'type-enum': [
      2,
      'always',
      [
        'feat', // New feature
        'fix', // Bug fix
        'docs', // Documentation
        'style', // Code style (formatting)
        'refactor', // Code refactoring
        'perf', // Performance improvements
        'test', // Tests
        'build', // Build system changes
        'ci', // CI/CD changes
        'chore', // Maintenance tasks
        'revert', // Revert commits
      ],
    ],
    'subject-case': [2, 'never', ['upper-case']],
    'header-max-length': [2, 'always', 72],
    'body-max-line-length': [2, 'always', 100],
    'footer-max-line-length': [2, 'always', 100],
  },
};

export default config;
