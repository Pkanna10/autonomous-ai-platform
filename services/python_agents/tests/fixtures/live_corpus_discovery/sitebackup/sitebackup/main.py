"""Workload: ``python -m sitebackup.main``."""

from sitebackup.backup import archive, fingerprint
from sitebackup.site import render


def main() -> None:
    site = render(130)
    for section, pages in site.items():
        print(f"{section}\t{len(pages)}\t{sum(map(len, pages))}")
    data = archive(site)
    print(f"archive\t{len(data)}\t{fingerprint(data)}")


if __name__ == "__main__":
    main()
