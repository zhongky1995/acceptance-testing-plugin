"""Small real producer/consumer rules used only in the offline demo."""

def producer_accepts(value):
    return isinstance(value, list) and len(value) <= 3 and all(type(v) is int for v in value)


def consumer_accepts(value):
    return isinstance(value, list) and len(value) <= 2 and all(type(v) is int for v in value)
