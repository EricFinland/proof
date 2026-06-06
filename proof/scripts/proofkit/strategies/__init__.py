REGISTRY = {}


def register(name):
    def deco(fn):
        REGISTRY[name] = fn
        return fn
    return deco


def get(name):
    return REGISTRY.get(name)


def load_all():
    from . import tests, exitcode, command, http, repro, filecheck  # noqa: F401
