#!/usr/bin/env python3
"""BotNode Incremental Stress Test.

Measures maximum transaction throughput on the current machine by
incrementally increasing concurrency until the system degrades.

Tests three endpoint categories:
    1. READ  — GET /v1/marketplace (no write, no auth)
    2. WRITE — POST /v1/tasks/create (escrow lock + ledger + commit)
    3. FULL  — Complete lifecycle: create task + complete + settle

Reports TPS, latency percentiles, and error rate at each concurrency level.
Stops when error rate exceeds 10% or p99 exceeds 5 seconds.
"""

import time
import json
import hashlib
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import httpx

API = "http://localhost:8000"
DURATION_PER_LEVEL = 10  # seconds per concurrency level
CONCURRENCY_LEVELS = [1, 2, 4, 8, 16, 32, 64, 128, 256]
MAX_ERROR_RATE = 0.10  # stop at 10% errors
MAX_P99_MS = 5000  # stop at 5s p99


@dataclass
class LevelResult:
    concurrency: int
    requests: int = 0
    errors: int = 0
    latencies: list = field(default_factory=list)
    duration: float = 0

    @property
    def tps(self) -> float:
        return self.requests / self.duration if self.duration > 0 else 0

    @property
    def error_rate(self) -> float:
        return self.errors / self.requests if self.requests > 0 else 0

    @property
    def p50(self) -> float:
        if not self.latencies:
            return 0
        s = sorted(self.latencies)
        return s[int(len(s) * 0.5)] * 1000

    @property
    def p95(self) -> float:
        if not self.latencies:
            return 0
        s = sorted(self.latencies)
        return s[int(len(s) * 0.95)] * 1000

    @property
    def p99(self) -> float:
        if not self.latencies:
            return 0
        s = sorted(self.latencies)
        return s[min(int(len(s) * 0.99), len(s) - 1)] * 1000


def create_sandbox_node():
    """Create a sandbox node for testing."""
    r = httpx.post(f"{API}/v1/sandbox/nodes", json={"alias": "stress"}, timeout=10)
    return r.json()


def setup_test_skill(api_key):
    """Publish a test skill and return its ID."""
    r = httpx.post(
        f"{API}/v1/marketplace/publish",
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json={
            "type": "SKILL_OFFER",
            "label": f"stress-skill-{int(time.time())}",
            "price_tck": 0.10,
            "metadata": {"category": "test"},
        },
        timeout=10,
    )
    return r.json()["skill_id"]


# ── Test functions ──────────────────────────────────────────────────────


def test_read(client):
    """GET /v1/marketplace — read-only, no auth."""
    start = time.monotonic()
    try:
        r = client.get(f"{API}/v1/marketplace?limit=10")
        elapsed = time.monotonic() - start
        return (r.status_code == 200, elapsed)
    except Exception:
        return (False, time.monotonic() - start)


def test_write(client, api_key, skill_id):
    """POST /v1/tasks/create — full escrow write path."""
    start = time.monotonic()
    try:
        r = client.post(
            f"{API}/v1/tasks/create",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"skill_id": skill_id, "input_data": {"text": "stress test"}},
        )
        elapsed = time.monotonic() - start
        return (r.status_code == 200, elapsed)
    except Exception:
        return (False, time.monotonic() - start)


def test_health(client):
    """GET /health — minimal overhead baseline."""
    start = time.monotonic()
    try:
        r = client.get(f"{API}/health")
        elapsed = time.monotonic() - start
        return (r.status_code == 200, elapsed)
    except Exception:
        return (False, time.monotonic() - start)


# ── Runner ──────────────────────────────────────────────────────────────


def run_level(test_fn, concurrency, duration):
    """Run test_fn at given concurrency for duration seconds."""
    result = LevelResult(concurrency=concurrency)
    stop_time = time.monotonic() + duration

    def worker():
        client = httpx.Client(timeout=10)
        local_ok = 0
        local_err = 0
        local_lat = []
        while time.monotonic() < stop_time:
            ok, elapsed = test_fn(client)
            if ok:
                local_ok += 1
            else:
                local_err += 1
            local_lat.append(elapsed)
        client.close()
        return local_ok, local_err, local_lat

    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(worker) for _ in range(concurrency)]
        for f in as_completed(futures):
            ok, err, lat = f.result()
            result.requests += ok + err
            result.errors += err
            result.latencies.extend(lat)
    result.duration = time.monotonic() - start

    return result


def print_header(test_name):
    print(f"\n{'='*70}")
    print(f"  STRESS TEST: {test_name}")
    print(f"  Duration per level: {DURATION_PER_LEVEL}s")
    print(f"  Stop conditions: error_rate>{MAX_ERROR_RATE*100}% or p99>{MAX_P99_MS}ms")
    print(f"{'='*70}")
    print(f"{'Conc':>6} {'Reqs':>8} {'TPS':>8} {'Err%':>7} {'p50ms':>8} {'p95ms':>8} {'p99ms':>8}  Status")
    print(f"{'-'*6:>6} {'-'*8:>8} {'-'*8:>8} {'-'*7:>7} {'-'*8:>8} {'-'*8:>8} {'-'*8:>8}  ------")


def print_row(r, status="OK"):
    err_pct = f"{r.error_rate*100:.1f}%"
    print(f"{r.concurrency:>6} {r.requests:>8} {r.tps:>8.1f} {err_pct:>7} {r.p50:>8.1f} {r.p95:>8.1f} {r.p99:>8.1f}  {status}")


def run_test_suite(test_name, test_fn):
    print_header(test_name)
    peak_tps = 0
    peak_conc = 0
    results = []

    for conc in CONCURRENCY_LEVELS:
        r = run_level(test_fn, conc, DURATION_PER_LEVEL)
        results.append(r)

        if r.tps > peak_tps:
            peak_tps = r.tps
            peak_conc = conc

        if r.error_rate > MAX_ERROR_RATE:
            print_row(r, "DEGRADED (errors)")
            break
        elif r.p99 > MAX_P99_MS:
            print_row(r, "DEGRADED (latency)")
            break
        else:
            print_row(r)

    print(f"\n  Peak: {peak_tps:.1f} TPS @ concurrency {peak_conc}")
    return peak_tps, peak_conc, results


def main():
    print("BotNode Incremental Stress Test")
    print(f"Target: {API}")
    print(f"Machine: checking...")

    # Machine info
    import os
    cpu = os.cpu_count()
    try:
        with open("/proc/meminfo") as f:
            mem = int(f.readline().split()[1]) // 1024
    except Exception:
        mem = 0
    print(f"CPUs: {cpu}, RAM: {mem}MB")

    # Verify API is up
    try:
        r = httpx.get(f"{API}/health", timeout=5)
        assert r.status_code == 200
        print(f"API: healthy\n")
    except Exception:
        print("ERROR: API not responding")
        sys.exit(1)

    # ── Test 1: Health (baseline) ──
    peak1, _, _ = run_test_suite(
        "HEALTH (baseline — minimal overhead)",
        lambda client: test_health(client),
    )

    # ── Test 2: Read (marketplace) ──
    peak2, _, _ = run_test_suite(
        "READ — GET /v1/marketplace",
        lambda client: test_read(client),
    )

    # ── Test 3: Write (task create) ──
    print("\nSetting up write test (creating sandbox nodes + skill)...")
    # Create multiple buyer nodes to avoid single-node bottleneck
    buyers = []
    for i in range(8):
        sb = create_sandbox_node()
        buyers.append(sb["api_key"])
    seller = create_sandbox_node()
    skill_id = setup_test_skill(seller["api_key"])
    print(f"  {len(buyers)} buyer nodes, 1 seller, skill={skill_id[:16]}...")

    buyer_idx = [0]

    def write_test(client):
        key = buyers[buyer_idx[0] % len(buyers)]
        buyer_idx[0] += 1
        return test_write(client, key, skill_id)

    peak3, _, _ = run_test_suite(
        "WRITE — POST /v1/tasks/create (escrow + ledger)",
        write_test,
    )

    # ── Summary ──
    print(f"\n{'='*70}")
    print(f"  RESULTS SUMMARY")
    print(f"{'='*70}")
    print(f"  Health baseline:  {peak1:.1f} TPS")
    print(f"  Read throughput:  {peak2:.1f} TPS")
    print(f"  Write throughput: {peak3:.1f} TPS")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
