"""Initialize native numerical libraries before the CLI starts worker threads."""

from __future__ import annotations

import faulthandler
import os


def initialize_cli_runtime() -> None:
    # The pipeline already parallelizes independent CPU tasks. Nested OpenBLAS
    # pools oversubscribe them and have crashed during concurrent Windows startup.
    # Set this before importing NumPy; changing it afterwards is ineffective.
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    try:
        faulthandler.enable(all_threads=True)
    except (OSError, RuntimeError, ValueError):
        # Embedded callers may have no file-backed stderr.
        pass

    import numpy as np

    # Initialize the BLAS runtime on the calling thread, before source workers.
    np.dot(np.ones((2, 2)), np.ones((2, 2)))
