"""A text report of a latency log: one sample in milliseconds per line."""

from latencystats.stats import percentile, summary


def parse_samples(text):
    samples = []
    for raw in text.splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            samples.append(float(line))
    return samples


def render(text, extra=()):
    """The summary of the log in ``text``, plus each percentile in ``extra``."""
    samples = parse_samples(text)
    lines = [f"{name}: {value:.1f} ms" for name, value in summary(samples).items()]
    for pct in extra:
        lines.append(f"p{pct:g}: {percentile(samples, pct):.1f} ms")
    return "\n".join(lines)
