"""Workload: ``python -m logarchive.main``."""

import zlib

from logarchive.archive import pack
from logarchive.data import day_log


def main() -> None:
    log = day_log(280000)
    archive, checkpoints = pack(log)
    for number, size in enumerate(checkpoints, 1):
        print(f"checkpoint {number}\t{size}")
    print(f"archive\t{len(log)}\t{len(archive)}")
    print(f"crc32\t{zlib.crc32(archive):08x}\tadler32\t{zlib.adler32(log):08x}")


if __name__ == "__main__":
    main()
