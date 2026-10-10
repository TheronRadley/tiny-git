# Performance Benchmarks

`tiny-git` ships an automated benchmark suite at [`benchmarks/run_benchmarks.py`](../benchmarks/run_benchmarks.py). Its purpose is architectural, not competitive: it exists to catch **quadratic filesystem scanning** — the classic failure mode of educational VCS implementations that re-walk the working tree or re-hash every object per operation.

```bash
python benchmarks/run_benchmarks.py
```

---

## Measurement Conditions

Numbers without conditions are decoration. These are the exact conditions for the table below:

| Condition | Value |
| :--- | :--- |
| Date | 2026-10-10 |
| Host | Containerised VM, 2 vCPU |
| CPU | Intel(R) Xeon(R) Processor @ 2.60 GHz |
| Memory | 3.8 GiB |
| Python | CPython 3.11.2 |
| OS | Linux (Debian-based container) |
| Filesystem | Overlay/container scratch volume |
| Runs per size | **1** (single run — see caveat below) |
| Timing | `time.perf_counter()` around each operation |
| Workload | `file_00000.txt` … `file_{N-1}.txt`, each ~22 bytes of text |

> **Caveat.** These are single-run wall-clock timings on a shared, noisy container — not a median of N runs on dedicated hardware. Treat them as *order-of-magnitude* evidence of scaling behaviour, not as reproducible absolute latencies. Absolute numbers will differ substantially on your machine; the ratios should not.

The 10,000-file row was measured separately by importing `benchmark_size(10000)` directly, since the script's default sizes are `[100, 1000, 2500]`.

---

## Measured Execution Times (ms)

| Operation | 100 files | 1,000 files | 2,500 files | 10,000 files | Scaling |
| :--- | ---: | ---: | ---: | ---: | :--- |
| `init` | 3.99 | 8.70 | 5.04 | 4.42 | `O(1)` — independent of file count |
| `add .` | 90.29 | 887.41 | 2,669.32 | 10,061.98 | `O(N)` — 10.06× for 10× files |
| `status` (staged) | 15.04 | 191.55 | 335.88 | 1,309.38 | `O(N)` |
| `status` (clean) | 13.34 | 167.39 | 343.13 | 1,206.10 | `O(N)` |
| `commit` | 3.38 | 8.66 | 15.06 | 57.78 | `O(N)` — tree construction only; blobs already stored |
| `diff` (clean tree) | 17.82 | 152.38 | 451.99 | 1,592.55 | `O(N)` — 10.45× for 10× files |
| `checkout` | 21.06 | 159.35 | 498.75 | 1,660.28 | `O(N)` — 10.42× for 10× files |
| `fsck` | 13.14 | 124.00 | 266.40 | 1,133.55 | `O(N)` — 9.14× for 10× files |

**Reading the table.** The rightmost column compares the 10,000-file time against the 1,000-file time. A linear algorithm should show ~10×; every operation lands between 9× and 10.5×. `init` stays flat because it writes four small files regardless of repository contents. Nothing here is quadratic — a quadratic `add` would have shown ~100×, i.e. roughly 9 seconds becoming 90.

`add .` dominates because it is the only operation that reads every working-tree file from disk and hashes it. That is the obvious target for the planned stat cache (see below).

---

## Why `add` and `status` Re-hash Everything

`status` and `diff` currently hash each working-tree file to compare it against the index, even when nothing changed. `IndexEntry` in [`src/tinygit/index.py`](../src/tinygit/index.py) already carries `stat_size` and `stat_mtime` fields, but they are not yet used to short-circuit the hash.

The planned optimisation: when a file's `(mtime, size)` matches the recorded stat data, trust the stored `object_id` and skip the read-and-hash entirely. This is exactly what real Git does. It should turn `status` on a clean tree from `O(total bytes)` into `O(N stat calls)`.

Re-run this suite after landing that change and record the new numbers here, with fresh conditions.

---

## Adding a Data Point

```python
from run_benchmarks import benchmark_size

results = benchmark_size(5000)   # 5,000 files
for op, ms in results.items():
    print(f"{op:<15}: {ms:>9.2f} ms")
```

If you contribute numbers, record the full conditions block above with them. A benchmark table without its hardware and Python version attached is not reproducible and will rot into a lie within a year.
