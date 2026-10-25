import unittest

from eventbus.dispatch import publish
from eventbus.registry import handlers_for, on


@on("ping")
def ping(payload):
    return f"pong {payload}"


class BusTest(unittest.TestCase):
    def test_publish_runs_the_handler(self):
        self.assertEqual(publish("ping", 1), ["pong 1"])

    def test_handlers_are_listed(self):
        self.assertEqual(handlers_for("ping"), [ping])


if __name__ == "__main__":
    unittest.main()
