"""OSS corpus benchmark: pypdf builds a 100-page document in memory (each page
with its own font dictionaries carrying 224-entry width tables, link, text,
square, highlight and polygon annotations whose values are arrays and nested
dictionaries, a nested outline, metadata, page labels), writes it, reads it
back, and merges it into a new document three times (twice whole, once a
page range) plus one ``clone_from`` copy, as a PDF merging tool does; the
merged document is written and read back for the digest.

Copied into the cloned repository as ``benchmarks/bench_pypdf.py``.
Deterministic: a fixed seed, no clock, no network, in-memory streams only;
prints a digest of the merged document's content (pages, annotations,
outline, labels, metadata), not of the bytes.
"""

from __future__ import annotations

import hashlib
import random
from io import BytesIO
from pathlib import Path
from typing import Any

import pypdf
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Highlight, Link, Polygon, Rectangle, Text
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NumberObject,
    RectangleObject,
)

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "pypdf" / "__init__.py"
PAGES = 100
WORDS = ("engine", "trial", "judge", "verdict", "noise", "branch", "profile", "cache")
GLYPH_WIDTHS = (250, 278, 333, 389, 500, 556, 611, 667, 722, 778, 833, 944)


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(pypdf.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(f"pypdf imported from {pypdf.__file__}, not {PACKAGE_INIT}")


def _font(name: str, rng: random.Random) -> DictionaryObject:
    """A simple font with the width table every such font carries."""
    widths = ArrayObject(
        [NumberObject(rng.choice(GLYPH_WIDTHS)) for _ in range(32, 256)]
    )
    return DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/TrueType"),
            NameObject("/BaseFont"): NameObject(f"/{name}"),
            NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
            NameObject("/FirstChar"): NumberObject(32),
            NameObject("/LastChar"): NumberObject(255),
            NameObject("/Widths"): widths,
        }
    )


def _source(rng: random.Random) -> bytes:
    writer = PdfWriter()
    for index in range(PAGES):
        page = writer.add_blank_page(width=612, height=792)
        fonts = DictionaryObject(
            {
                NameObject("/F1"): _font("Helvetica", rng),
                NameObject("/F2"): _font("Courier-Bold", rng),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): fonts,
                NameObject("/ProcSet"): ArrayObject(
                    [NameObject("/PDF"), NameObject("/Text")]
                ),
            }
        )
        page.cropbox = RectangleObject((10, 10, 602, 782))
        for k in range(rng.randint(3, 7)):
            y = 700 - 60 * k
            kind = (index + k) % 5
            if kind == 0:
                annotation = Link(
                    rect=(72, y, 300, y + 20),
                    target_page_index=rng.randrange(PAGES),
                    border=[0, 0, 1],
                )
            elif kind == 1:
                annotation = Link(
                    rect=(72, y, 300, y + 20),
                    url=f"https://example.org/{rng.choice(WORDS)}",
                )
            elif kind == 2:
                annotation = Text(
                    rect=(320, y, 340, y + 20),
                    text=f"{rng.choice(WORDS)} note {index}.{k}",
                    open=k % 2 == 0,
                )
            elif kind == 3:
                annotation = Highlight(
                    rect=(72, y, 300, y + 20),
                    quad_points=ArrayObject(
                        [
                            FloatObject(v)
                            for v in (72, y + 20, 300, y + 20, 72, y, 300, y)
                        ]
                    ),
                    highlight_color=rng.choice(("ff0000", "00ff00", "ffff00")),
                )
            else:
                annotation = Polygon(
                    vertices=[(72, y), (120, y + 30), (170, y), (120, y - 30)]
                )
            writer.add_annotation(page_number=index, annotation=annotation)
        if index % 4 == 0:
            writer.add_annotation(
                page_number=index,
                annotation=Rectangle(
                    rect=(400, 600, 500, 700), interior_color="ccccff"
                ),
            )
    chapter = None
    for index in range(0, PAGES, 10):
        chapter = writer.add_outline_item(
            f"Chapter {index // 10}", index, color=(0.1, 0.2, 0.3)
        )
        for sub in range(1, 4):
            writer.add_outline_item(
                f"Section {index // 10}.{sub}",
                min(index + sub * 2, PAGES - 1),
                parent=chapter,
                italic=True,
            )
    writer.add_metadata(
        {
            "/Title": "Merge sample",
            "/Author": "Benchmark",
            "/Subject": "cloning",
            "/Keywords": "a, b, c",
        }
    )
    writer.set_page_label(0, 4, style="/r")
    writer.set_page_label(5, 49, style="/D", prefix="A-")
    writer.set_page_label(50, 89, style="/D", start=100)
    writer.set_page_label(90, PAGES - 1, style="/A")
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _value(obj: object, key: str, default: object = None) -> object:
    """``obj[key]`` resolved through any indirect reference, or ``default``."""
    value = obj.get(key, default) if hasattr(obj, "get") else default
    return value.get_object() if hasattr(value, "get_object") else value


def _describe(reader: PdfReader, digest: Any) -> int:
    annotations = 0
    for number, page in enumerate(reader.pages):
        digest.update(f"page {number} {page.mediabox} {page.cropbox}\n".encode())
        fonts = _value(_value(page, "/Resources", {}), "/Font", {})
        for name in sorted(fonts):
            font = _value(fonts, name, {})
            widths = _value(font, "/Widths", [])
            digest.update(f"  font {name} {len(widths)} {sum(widths)}\n".encode())
        for ref in _value(page, "/Annots", []):
            annot = ref.get_object()
            annotations += 1
            dest = _value(annot, "/Dest")
            target = (
                reader.get_page_number(dest[0].get_object()) if dest is not None else -1
            )
            uri = _value(_value(annot, "/A", {}), "/URI", "")
            digest.update(
                f"  {_value(annot, '/Subtype')} {_value(annot, '/Rect')} "
                f"{_value(annot, '/Contents', '')} {list(_value(annot, '/QuadPoints', []))} "
                f"{list(_value(annot, '/Vertices', []))} {list(_value(annot, '/C', []))} "
                f"{target} {uri}\n".encode()
            )

    def outline(items: list, depth: int) -> None:
        for item in items:
            if isinstance(item, list):
                outline(item, depth + 1)
            else:
                digest.update(
                    f"outline {depth} {item.title} {reader.get_destination_page_number(item)}\n".encode()
                )

    outline(reader.outline, 0)
    digest.update(",".join(reader.page_labels).encode())
    metadata = reader.metadata
    digest.update(f"{metadata.title} {metadata.author} {metadata.subject}\n".encode())
    return annotations


def main() -> None:
    _checked()
    source = _source(random.Random(67))
    reader = PdfReader(BytesIO(source))
    merged = PdfWriter()
    merged.append(reader)
    merged.append(reader, pages=(10, 50))
    merged.append(reader, outline_item="Second copy", import_outline=True)
    copy = PdfWriter(clone_from=reader)
    out = BytesIO()
    merged.write(out)
    digest = hashlib.sha256()
    annotations = _describe(PdfReader(BytesIO(out.getvalue())), digest)
    digest.update(f"copy pages={len(copy.pages)}\n".encode())
    print(
        f"pypdf source_bytes={len(source)} merged_pages={len(merged.pages)} "
        f"annotations={annotations} sha256={digest.hexdigest()}"
    )


if __name__ == "__main__":
    main()
