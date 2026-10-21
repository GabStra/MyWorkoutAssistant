"""Publish JSON checkpoints without truncating the previous saved file."""
import json
import os
import tempfile
import time
from pathlib import Path


def write_json_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=f'.{path.name}.', suffix='.tmp', delete=False) as output:
            temporary = Path(output.name)
            json.dump(data, output, indent=2, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
        for attempt in range(6):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                # Windows readers can briefly deny replacement of a completed checkpoint.
                time.sleep(0.05 * 2 ** attempt)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
