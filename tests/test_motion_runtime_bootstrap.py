import json
import os
from pathlib import Path
import subprocess
import sys


def test_native_runtime_initializes_before_parallel_numerical_work():
    code = '''
import sys
from exercise_motion_pkg.runtime_bootstrap import initialize_cli_runtime
assert 'numpy' not in sys.modules
initialize_cli_runtime()
import faulthandler
import numpy as np
from concurrent.futures import ThreadPoolExecutor
import json
with ThreadPoolExecutor(max_workers=6) as pool:
    values = list(pool.map(lambda _: float(np.dot(np.ones((32, 32)), np.ones((32, 32)))[0, 0]), range(24)))
assert values == [32.0] * 24
assert faulthandler.is_enabled()
try:
    from threadpoolctl import threadpool_info
    pools = threadpool_info()
except ImportError:
    # The generator environment has NumPy but no threadpoolctl dependency.
    import ctypes
    from pathlib import Path
    pools = []
    for path in (Path(np.__file__).parent.parent / 'numpy.libs').glob('*openblas*.dll'):
        dll = ctypes.CDLL(str(path))
        pools.append({'internal_api': 'openblas', 'num_threads': dll.scipy_openblas_get_num_threads64_()})
print(json.dumps(pools))
'''
    env = dict(os.environ, OPENBLAS_NUM_THREADS="32")
    result = subprocess.run(
        [sys.executable, "-c", code], env=env,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
    pools = json.loads(result.stdout)
    blas = [pool for pool in pools if pool["internal_api"] == "openblas"]
    assert blas
    assert all(pool["num_threads"] == 1 for pool in blas)
