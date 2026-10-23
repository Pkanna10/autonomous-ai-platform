"""Workload: ``python -m topicmerge.main``."""

from topicmerge.data import posts
from topicmerge.merge import posts_per_board, topic_counts, unique_topics


def main() -> None:
    forum = posts(14000, 3200)
    counts = topic_counts(forum)
    topics = unique_topics(forum)
    print(f"topics\t{len(topics)}")
    for topic in topics:
        print(f"{topic}\t{counts[topic]}")
    for board, total in posts_per_board(forum).items():
        print(f"{board}\t{total}")


if __name__ == "__main__":
    main()
