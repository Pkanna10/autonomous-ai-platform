"""The pager under a result list."""

from pagekit.pages import get_page, page_count


def links(total, per_page):
    """The page numbers the pager links to."""
    return list(range(1, page_count(total, per_page) + 1))


def render(items, page, per_page):
    """One page as text: a heading, then one line per item."""
    chunk = get_page(items, page, per_page)
    heading = f"Page {page} of {page_count(len(items), per_page)}"
    return "\n".join([heading, *map(str, chunk)])
