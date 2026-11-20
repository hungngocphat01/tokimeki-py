"""Functions submitted in tests (importable as tests.helpers / helpers)."""


def square(arg):
    return {"x": arg["x"], "square": arg["x"] ** 2}


def boom(arg):
    raise ValueError(f"bad x {arg['x']}")


def nothing(arg):
    return None


def unserializable(arg):
    return {1, 2}
