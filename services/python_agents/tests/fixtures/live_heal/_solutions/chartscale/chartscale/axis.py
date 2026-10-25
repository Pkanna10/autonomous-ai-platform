"""Map data values to pixel heights and back for a bar chart."""


def scale_factor(max_value, height):
    """Pixels per data unit, so that ``max_value`` fills ``height`` pixels."""
    if max_value <= 0:
        raise ValueError("max_value must be positive")
    return height / max_value


def bar_heights(values, height):
    """The pixel height of each value's bar."""
    factor = scale_factor(max(values), height)
    return [round(value * factor) for value in values]


def pixel_to_value(pixel, factor):
    return pixel / factor


def axis_ticks(max_value, height, ticks=4):
    """The data value at each of ``ticks + 1`` evenly spaced tick marks."""
    factor = scale_factor(max_value, height)
    step = height / ticks
    labels = []
    for tick in range(ticks + 1):
        labels.append(round(pixel_to_value(tick * step, factor), 2))
    return labels
