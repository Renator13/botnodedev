#!/usr/bin/env python3
"""Write-path stress test — POST /v1/tasks/create (escrow + ledger)."""

import time
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import httpx

API = "http://localhost:8000"
DURATION = 10
LEVELS = [1, 2, 4, 8, 16, 32, 64]


@dataclass
class R:
    c: int
    n: int = 0
    err: int = 0
    lat: list = field(default_factory=list)
    dur: float = 0

    @property
    def tps(self): return self.n / self.dur if self.dur else 0
    @property
    def err_pct(self): return self.err / self.n * 100 if self.n else 0
    def pct(self, p):
        if not self.lat: return 0
        s = sorted(self.lat)
        return s[min(int(len(s)*p), len(s)-1)] * 1000


def setup():
    """Create test buyers + seller + skill."""
    buyers = []
    for _ in range(8):
        r = httpx.post(f"{API}/v1/sandbox/nodes", json={"alias": "wr"}, timeout=30)
        buyers.append(r.json()["api_key"])
    seller = httpx.post(f"{API}/v1/sandbox/nodes", json={"alias": "ws"}, timeout=30).json()
    r = httpx.post(f"{API}/v1/marketplace/publish",
        headers={"X-API-KEY": seller["api_key"], "Content-Type": "application/json"},
        json={"type": "SKILL_OFFER", "label": f"stress-{int(time.time())}", "price_tck": 0.10, "metadata": {}},
        timeout=30)
    skill_id = r.json()["skill_id"]
    return buyers, skill_id


def run(buyers, skill_id, conc):
    result = R(c=conc)
    stop = time.monotonic() + DURATION
    idx = [0]

    def worker():
        client = httpx.Client(timeout=15)
        ok = err = 0
        lat = []
        while time.monotonic() < stop:
            key = buyers[idx[0] % len(buyers)]
            idx[0] += 1
            t0 = time.monotonic()
            try:
                r = client.post(f"{API}/v1/tasks/create",
                    headers={"X-API-KEY": key, "Content-Type": "application/json"},
                    json={"skill_id": skill_id, "input_data": {"t": "x"}})
                e = time.monotonic() - t0
                if r.status_code == 200: ok += 1
                else: err += 1
                lat.append(e)
            except Exception:
                err += 1
                lat.append(time.monotonic() - t0)
        client.close()
        return ok, err, lat

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=conc) as pool:
        for ok, err, lat in [f.result() for f in [pool.submit(worker) for _ in range(conc)]]:
            result.n += ok + err
            result.err += err
            result.lat.extend(lat)
    result.dur = time.monotonic() - t0
    return result


def main():
    print("BotNode WRITE Stress Test")
    print(f"Endpoint: POST /v1/tasks/create (escrow + ledger + commit)")
    import os
    print(f"Machine: {os.cpu_count()} CPUs, Docker API + PostgreSQL 16")
    print(f"Duration: {DURATION}s per level\n")

    print("Setting up...")
    buyers, skill_id = setup()
    print(f"  8 buyers, 1 skill ({skill_id[:16]}...)\n")

    print(f"{'Conc':>6} {'Reqs':>8} {'TPS':>8} {'Err%':>7} {'p50ms':>8} {'p95ms':>8} {'p99ms':>8}")
    print(f"{'-'*6:>6} {'-'*8:>8} {'-'*8:>8} {'-'*7:>7} {'-'*8:>8} {'-'*8:>8} {'-'*8:>8}")

    peak_tps = 0
    peak_c = 0
    for c in LEVELS:
        r = run(buyers, skill_id, c)
        if r.tps > peak_tps:
            peak_tps = r.tps
            peak_c = c
        ep = f"{r.err_pct:.1f}%"
        status = ""
        if r.err_pct > 10:
            status = " << DEGRADED"
        elif r.pct(0.99) > 5000:
            status = " << LATENCY"
        print(f"{r.c:>6} {r.n:>8} {r.tps:>8.1f} {ep:>7} {r.pct(0.5):>8.1f} {r.pct(0.95):>8.1f} {r.pct(0.99):>8.1f}{status}")
        if r.err_pct > 10 or r.pct(0.99) > 5000:
            break

    print(f"\nPEAK WRITE THROUGHPUT: {peak_tps:.1f} TPS @ concurrency {peak_c}")
    print(f"(Each write = escrow lock + double-entry ledger + SELECT FOR UPDATE + COMMIT)")


if __name__ == "__main__":
    main()
