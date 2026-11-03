"""Optional observation boundary; application code does not depend on an SDK."""

from contextlib import nullcontext


class NullObservation:
    def update(self, **attributes):
        pass


def no_observation(*, name: str, **attributes):
    return nullcontext(NullObservation())
