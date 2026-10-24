"""Worker settings."""

from durations.parse import parse_duration

DURATION_KEYS = ("timeout", "retry_after", "heartbeat")


def load_settings(raw):
    """``raw`` settings (text values) with every duration key in seconds."""
    settings = dict(raw)
    for key in DURATION_KEYS:
        if key in settings:
            settings[key] = parse_duration(settings[key])
    return settings
