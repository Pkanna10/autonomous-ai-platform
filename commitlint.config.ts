import type { UserConfig } from '@commitlint/types';

const config: UserConfig = {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'type-enum': [2, 'always', ['feat', 'fix', 'docs', 'style', 'refactor', 'test', 'chore']],
    'subject-case': [2, 'never', ['upper-case']],
    'header-max-length': [2, 'always', 72],
  },
};

export default config;
