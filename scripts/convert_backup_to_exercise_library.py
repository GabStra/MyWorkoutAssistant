"""Convert an AppBackup to the current exercise library using semantic matching."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workout_generator_pkg.backup_migration import main

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('\nCancelled. Completed mapping batches are saved; rerun the same command to resume.')
        raise SystemExit(130)
