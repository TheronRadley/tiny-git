"""Benchmarking suite for Tiny Git core operations.

Measures execution time (ms) for add, status, commit, checkout, diff, and
fsck across repositories scaled to 100, 1000, and 2500 files to detect
architectural bottlenecks or quadratic filesystem scanning.
"""

import shutil
import tempfile
import time
from pathlib import Path

from tinygit.repository import Repository


def benchmark_size(num_files: int) -> dict[str, float]:
    temp_dir = Path(tempfile.mkdtemp(prefix=f"tinygit_bench_{num_files}_"))
    try:
        results = {}

        # 1. Init
        t0 = time.perf_counter()
        repo = Repository.init(temp_dir)
        results["init"] = (time.perf_counter() - t0) * 1000.0

        # 2. Create files
        for i in range(num_files):
            (temp_dir / f"file_{i:05d}.txt").write_text(f"content for file {i}\n", encoding="utf-8")

        # 3. Add all
        t0 = time.perf_counter()
        repo.add(["."])
        results["add_all"] = (time.perf_counter() - t0) * 1000.0

        # 4. Status (staged)
        t0 = time.perf_counter()
        _ = repo.status()
        results["status_staged"] = (time.perf_counter() - t0) * 1000.0

        # 5. Commit
        t0 = time.perf_counter()
        _ = repo.commit("Initial benchmark commit")
        results["commit"] = (time.perf_counter() - t0) * 1000.0

        # 6. Status (clean)
        t0 = time.perf_counter()
        _ = repo.status()
        results["status_clean"] = (time.perf_counter() - t0) * 1000.0

        # 7. Diff
        t0 = time.perf_counter()
        _ = repo.diff()
        results["diff_clean"] = (time.perf_counter() - t0) * 1000.0

        # 8. Branch & Checkout
        repo.branch("feat")
        t0 = time.perf_counter()
        repo.checkout("feat")
        results["checkout"] = (time.perf_counter() - t0) * 1000.0

        # 9. Fsck
        t0 = time.perf_counter()
        res = repo.fsck()
        assert res.is_healthy()
        results["fsck"] = (time.perf_counter() - t0) * 1000.0

        return results
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def main():
    print("=== Tiny Git Core Operation Benchmarks ===")
    sizes = [100, 1000, 2500]
    for n in sizes:
        print(f"\n--- Benchmark: {n} files ---")
        res = benchmark_size(n)
        for op, ms in res.items():
            print(f"  {op:<15}: {ms:>8.2f} ms")


if __name__ == "__main__":
    main()
