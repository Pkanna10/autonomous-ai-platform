"""Tests for ``topicmerge`` (stdlib ``unittest``)."""

import unittest

from topicmerge.data import Post, posts
from topicmerge.merge import posts_per_board, topic_counts, unique_topics


class MergeTests(unittest.TestCase):
    def test_each_topic_once(self) -> None:
        forum = [Post(0, "a", ("x", "y")), Post(1, "b", ("y", "z", "y"))]
        topics = unique_topics(forum)
        self.assertEqual(len(topics), 3)
        self.assertEqual(set(topics), {"x", "y", "z"})
        self.assertEqual(unique_topics([]), [])

    def test_counts_and_boards(self) -> None:
        forum = [Post(0, "b", ("x", "x")), Post(1, "a", ("x",)), Post(2, "b", ())]
        self.assertEqual(topic_counts(forum), {"x": 2})
        self.assertEqual(posts_per_board(forum), {"a": 1, "b": 2})

    def test_generated_posts(self) -> None:
        forum = posts(200, 50)
        self.assertEqual(forum, posts(200, 50))
        self.assertEqual(set(unique_topics(forum)), set(topic_counts(forum)))


if __name__ == "__main__":
    unittest.main()
