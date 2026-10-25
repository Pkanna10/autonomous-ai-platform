"""The second live OSS library set (Window 0, the technique-list re-test).

The OSS discovery A/B (``discovery_oss.py``) on ``oss.OSS_CORPUS`` tied:
blind 11/20, playbook-matched 11/20, discordant b = 2, c = 2. More real
libraries is the cheapest way to add evidence, so ``OSS_CORPUS_V2`` is a
second, disjoint set of eight pure-Python, CPU-bound libraries with the
same manifest shape, the same checks and the same clone path as the first:
``tests/fixtures/oss_v2`` holds ``manifest.json`` (parsed by
``oss.parse_manifest``, strictly) and one workload per library.

``OssRepoV2`` is ``oss.OssRepo`` with one difference: its workload lives in
this set's own ``workloads/`` folder. Everything else (``clone_pinned``,
``prepare_repo``, ``start_oss_loop`` and the production ``GitPolicy``)
is ``oss.py``'s, unchanged: nothing upstream is vendored here either.

Chosen 2026-10-24 from the candidates the Lead listed, each cloned at its
pin and checked the way ``test_oss_guards`` checks the first set (workload
0.5 to 2 s, deterministic, tests green in the engine's child environment,
no submodule or LFS, ``discovery_oss.clone_problems`` empty, no hypothesis
target the ``process_spawn`` rule flags). Left out, and why:

- chardet 7.7.0: ``chardet/__init__.py`` imports ``chardet._version``,
  which only a build writes, so it does not import from a checkout;
- pygments 2.21.0: a tracked example file defines a non-ASCII class name
  (``Käse``), past the bounds ``discovery_oss`` assumes;
- python-dateutil 3.0.0 and html5lib 1.1: they need ``six`` (html5lib also
  ``webencodings``), a runtime dependency outside the stdlib;
- wcwidth 0.9.3, lark 1.3.1 (and jmespath 1.1.0): a ``.gitmodules`` file,
  which the clone (and preflight) refuses;
- babel 2.18.0: its locale data is generated from CLDR at build time;
- mpmath 1.4.1: a build-written ``_version`` module, as chardet;
- hpack 4.2.0: its test conftest needs ``hypothesis``, which leaves only 26
  tests runnable, too thin a judge for its encoder and decoder.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Final

from .conftest import TESTS_DIR
from .oss import OssRepo, parse_manifest

OSS_V2_DIR: Final = TESTS_DIR / "fixtures" / "oss_v2"
MANIFEST_V2: Final = OSS_V2_DIR / "manifest.json"
WORKLOADS_V2_DIR: Final = OSS_V2_DIR / "workloads"
V2_REPOS: Final = 8


@dataclass(frozen=True)
class OssRepoV2(OssRepo):
    """A library of the second set: its workload is in ``WORKLOADS_V2_DIR``."""

    @property
    def workload_source(self) -> Path:
        return WORKLOADS_V2_DIR / f"{self.name}.py"


def as_v2(repo: OssRepo) -> OssRepoV2:
    """``repo``'s fields as an ``OssRepoV2``."""
    return OssRepoV2(**{f.name: getattr(repo, f.name) for f in fields(OssRepo)})


def parse_manifest_v2(
    data: object, workloads: Path = WORKLOADS_V2_DIR
) -> tuple[OssRepoV2, ...]:
    """The second set, validated as strictly as the first (``oss.parse_manifest``)."""
    return tuple(as_v2(repo) for repo in parse_manifest(data, workloads))


OSS_CORPUS_V2: Final = parse_manifest_v2(
    json.loads(MANIFEST_V2.read_text(encoding="utf-8"))
)
