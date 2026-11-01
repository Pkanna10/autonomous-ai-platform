"""Workload: ``python -m booklist.main``."""

from booklist.catalogue import Catalogue
from booklist.data import day
from booklist.shop import Shop


def main() -> None:
    titles, commands = day(2000, 3600)
    catalogue = Catalogue(titles)
    shop = Shop(catalogue, 5)
    listed = length = 0
    for number, command in enumerate(commands):
        found = shop.handle(command)
        if found is None:
            continue
        listed += len(found)
        length += sum(map(len, found))
        if number % 60 == 0:
            print(f"{command[1]}\t{','.join(found)}")
    print(f"titles\t{len(catalogue)}")
    print(f"listed\t{listed}")
    print(f"slug length\t{length}")


if __name__ == "__main__":
    main()
