"""OSS corpus v2 benchmark: pyasn1 builds 900 records of a nested ASN.1
schema (a sequence of integers, strings, booleans, an enumeration, an
object identifier, an optional field and a sequence-of), DER-encodes them,
decodes them back against the schema and BER-decodes them schemaless.

Copied into the cloned repository as ``benchmarks/bench_pyasn1.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest. The
codecs are imported and the schema defined in ``main`` (after
``_checked``), never at import.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import pyasn1

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "pyasn1" / "__init__.py"
RECORDS = 900


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(pyasn1.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(f"pyasn1 imported from {pyasn1.__file__}, not {PACKAGE_INIT}")


def _schema() -> tuple[type, type]:
    from pyasn1.type import char, namedtype, namedval, univ

    class Status(univ.Enumerated):
        namedValues = namedval.NamedValues(  # noqa: N815 (the pyasn1 API)
            ("open", 0), ("paid", 1), ("shipped", 2)
        )

    class Line(univ.Sequence):
        componentType = namedtype.NamedTypes(  # noqa: N815
            namedtype.NamedType("sku", char.UTF8String()),
            namedtype.NamedType("quantity", univ.Integer()),
            namedtype.NamedType("price", univ.Integer()),
        )

    class Lines(univ.SequenceOf):
        componentType = Line()  # noqa: N815

    class Record(univ.Sequence):
        componentType = namedtype.NamedTypes(  # noqa: N815
            namedtype.NamedType("number", univ.Integer()),
            namedtype.NamedType("customer", char.UTF8String()),
            namedtype.NamedType("status", Status()),
            namedtype.NamedType("flagged", univ.Boolean()),
            namedtype.NamedType("kind", univ.ObjectIdentifier()),
            namedtype.NamedType("payload", univ.OctetString()),
            namedtype.OptionalNamedType("note", char.PrintableString()),
            namedtype.NamedType("lines", Lines()),
        )

    return Record, Line


def _record(rng: random.Random, n: int, record_type: type, line_type: type) -> object:
    record = record_type()
    record["number"] = n * 7919 - 1_000_000
    record["customer"] = f"customer-{n % 97}-é中"
    record["status"] = n % 3
    record["flagged"] = rng.random() < 0.3
    record["kind"] = (1, 3, 6, 1, 4, 1, rng.randint(1, 60000), n % 50)
    record["payload"] = bytes(rng.randrange(256) for _ in range(rng.randint(8, 64)))
    if n % 4 == 0:
        record["note"] = f"note {n}"
    for k in range(rng.randint(2, 6)):
        line = line_type()
        line["sku"] = f"sku-{(n + k) % 500:04d}"
        line["quantity"] = rng.randint(1, 40)
        line["price"] = rng.randint(1, 10**9)
        record["lines"].append(line)
    return record


def main() -> None:
    _checked()
    from pyasn1.codec.ber import decoder as ber_decoder
    from pyasn1.codec.der import decoder as der_decoder
    from pyasn1.codec.der import encoder as der_encoder

    record_type, line_type = _schema()
    rng = random.Random(53)
    digest = hashlib.sha256()
    for n in range(RECORDS):
        encoded = der_encoder.encode(_record(rng, n, record_type, line_type))
        decoded, rest = der_decoder.decode(encoded, asn1Spec=record_type())
        if rest or der_encoder.encode(decoded) != encoded:
            raise SystemExit(f"record {n} did not round-trip")
        loose, _ = ber_decoder.decode(encoded)
        digest.update(encoded + loose.prettyPrint().encode())
    print(f"pyasn1 records={RECORDS} sha256={digest.hexdigest()}")


if __name__ == "__main__":
    main()
