"""Merging topic labels across posts."""

from topicmerge.data import Post


def unique_topics(posts: list[Post]) -> list[str]:
    """Every topic once, in the order it was first used."""
    seen: list[str] = []
    for post in posts:
        for topic in post.topics:
            if topic not in seen:
                seen.append(topic)
    return seen


def topic_counts(posts: list[Post]) -> dict[str, int]:
    """How many posts carry each topic (a post counts once per topic)."""
    counts: dict[str, int] = {}
    for post in posts:
        for topic in set(post.topics):
            counts[topic] = counts.get(topic, 0) + 1
    return counts


def posts_per_board(posts: list[Post]) -> dict[str, int]:
    """Posts per board, boards in sorted order."""
    counts: dict[str, int] = {}
    for post in posts:
        counts[post.board] = counts.get(post.board, 0) + 1
    return dict(sorted(counts.items()))
