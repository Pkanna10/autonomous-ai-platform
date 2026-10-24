"""Units of mass."""

# How many of each unit make one kilogram.
PER_KG = {"kg": 1, "g": 1000, "mg": 1_000_000, "t": 0.001}


def to_kg(quantity, unit):
    """``quantity`` of ``unit`` (kg, g, mg or t) in kilograms."""
    return quantity * PER_KG[unit]
