"""Making the runtime say what it did.

Three things were being recorded and none of them arrived.

The synthesis agent writes `logger.info` every time it refuses a sentence, and
uvicorn does not configure application loggers — so INFO was dropped at the
root and the log held nothing. Every synthesised sentence was being rejected
for a week and the only way to find out was to call the module by hand. A
check that fails silently is a check nobody is running.

Nothing here decides anything. It is the instrument, not the mechanism, and a
failure to observe must never become a failure to answer.
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import contextmanager
from time import perf_counter

#: Everything this product logs hangs under one name, so a deployment can raise
#: or silence the whole runtime with one setting.
ROOT = "tradeflow"

#: Where the level comes from. Named rather than hard-coded because the reason
#: this module exists is that a default swallowed something that mattered.
LEVEL_VAR = "TRADEFLOW_LOG_LEVEL"


def listen(stream: object | None = None) -> logging.Logger:
    """Attach a handler to the runtime's logger, once.

    Called at import of the web app rather than left to the operator: the
    failure this prevents is invisible, and an instrument that has to be
    switched on is off on the day it was needed.
    """
    logger = logging.getLogger(ROOT)
    logger.setLevel(os.environ.get(LEVEL_VAR, "INFO").upper())
    if not logger.handlers:
        handler = logging.StreamHandler(stream or sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s | %(message)s")
        )
        logger.addHandler(handler)
    # uvicorn's own root handler would print each line a second time.
    logger.propagate = False
    return logger


@contextmanager
def took(record: dict[str, float], name: str):
    """Record how long something took, whether or not it succeeded.

    A worker that failed after five seconds and one that failed immediately are
    different problems, and the report kept only the failure. Timing is written
    in a `finally` for that reason.
    """
    started = perf_counter()
    try:
        yield
    finally:
        record[name] = round(perf_counter() - started, 3)
