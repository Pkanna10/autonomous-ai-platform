"""Pages of a result list."""


class PageError(LookupError):
    pass


def page_count(total, per_page):
    """How many pages ``total`` results fill, ``per_page`` to a page. An
    empty result still has one (empty) page, shown as "Page 1 of 1"."""
    if per_page < 1:
        raise ValueError("per_page must be at least 1")
    return total // per_page + 1


def get_page(items, page, per_page):
    """The items on page ``page`` (1-based). Only the first page may be
    empty (an empty result); any other empty page is an error."""
    count = page_count(len(items), per_page)
    if not 1 <= page <= count:
        raise PageError(f"page {page} is out of range (1..{count})")
    start = (page - 1) * per_page
    chunk = items[start : start + per_page]
    if not chunk and page != 1:
        raise PageError(f"page {page} of {count} is empty")
    return chunk
