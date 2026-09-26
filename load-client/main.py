#!/usr/bin/env python3
"""
Distributed load client for the ticket seller.
Runs multiple worker processes, each firing concurrent async requests.
Proves throughput ceiling is the seller, not the client.

Usage:
  uv run main.py --target http://localhost:8002 --tickets 100 \
    --requests 50000 --concurrency 200 --workers 4 \
    --duplicate-ratio 0.1

  # Run against cluster:
  uv run main.py --target http://localhost:8003 --tickets 100 \
    --requests 50000 --concurrency 200 --workers 8
"""

import asyncio
import math
import multiprocessing
import random
import string
import time
from dataclasses import dataclass, field, asdict
from multiprocessing import Queue, Process
from typing import Optional

import click
import aiohttp
import uvloop
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()


def gen_id(n: int = 12) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


@dataclass
class WorkerResult:
    worker_id: int
    total: int = 0
    successes: int = 0
    sold_out: int = 0
    errors: int = 0
    response_times: list[float] = field(default_factory=list)
    # (request_id, ticket) for every response — used to verify idempotency
    # across the whole run, not just within one worker's own requests.
    request_results: list[tuple[str, Optional[int]]] = field(default_factory=list)
    duration_ms: float = 0.0


@dataclass
class InvariantResult:
    name: str
    passed: bool
    detail: str


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = int(len(sorted_vals) * p / 100)
    return sorted_vals[min(idx, len(sorted_vals) - 1)]


async def worker_main(
    worker_id: int,
    target: str,
    pairs: list[tuple[str, str, bool]],
    concurrency: int,
    result_queue: Queue,
):
    result = WorkerResult(worker_id=worker_id)
    start = time.monotonic()

    connector = aiohttp.TCPConnector(limit=concurrency, limit_per_host=concurrency)
    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        for i in range(0, len(pairs), concurrency):
            batch = pairs[i : i + concurrency]

            async def fire(user_id: str, request_id: str) -> tuple[int, float, Optional[int], bool]:
                t0 = time.monotonic()
                try:
                    async with session.post(
                        f"{target}/buy",
                        json={"user_id": user_id, "request_id": request_id},
                    ) as resp:
                        data = await resp.json()
                        elapsed = (time.monotonic() - t0) * 1000
                        ticket = data.get("ticket")
                        sold_out = bool(data.get("sold_out") or data.get("waitlisted"))
                        return resp.status, elapsed, ticket, sold_out
                except Exception:
                    elapsed = (time.monotonic() - t0) * 1000
                    return 0, elapsed, None, False

            tasks = [fire(uid, rid) for uid, rid, _ in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for (uid, rid, _), br in zip(batch, batch_results):
                if isinstance(br, Exception):
                    result.errors += 1
                    continue
                status, elapsed, ticket, sold_out = br
                result.total += 1
                result.response_times.append(elapsed)
                result.request_results.append((rid, ticket))
                if status == 0:
                    result.errors += 1
                elif ticket is not None:
                    result.successes += 1
                elif sold_out:
                    result.sold_out += 1
                else:
                    result.errors += 1

    result.duration_ms = (time.monotonic() - start) * 1000
    result_queue.put(asdict(result))


def run_worker(worker_id, target, pairs, concurrency, result_queue):
    uvloop.install()
    asyncio.run(worker_main(worker_id, target, pairs, concurrency, result_queue))


def build_pairs(
    total_requests: int,
    duplicate_ratio: float,
    user_pool_size: int,
) -> list[tuple[str, str, bool]]:
    user_pool = [f"user_{i}" for i in range(user_pool_size)]
    unique_count = int(total_requests * (1 - duplicate_ratio))
    unique_ids = [gen_id() for _ in range(unique_count)]

    pairs: list[tuple[str, str, bool]] = []
    for i in range(total_requests):
        user_id = random.choice(user_pool)
        if i < unique_count:
            pairs.append((user_id, unique_ids[i], False))
        else:
            pairs.append((user_id, random.choice(unique_ids), True))

    random.shuffle(pairs)
    return pairs


async def verify_invariants(
    target: str,
    ticket_count: int,
    all_results: list[WorkerResult],
) -> list[InvariantResult]:
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{target}/status") as resp:
            status = await resp.json()

    ticket_nums = [t["ticket"] for t in status["tickets"]]
    sold = status["sold"]

    invariants = []

    # 1. No oversell
    invariants.append(InvariantResult(
        name="No Oversell",
        passed=sold <= ticket_count,
        detail=f"Sold {sold} of {ticket_count} available",
    ))

    # 2. No double issue
    num_set = set(ticket_nums)
    dupes = len(ticket_nums) - len(num_set)
    invariants.append(InvariantResult(
        name="No Double Issue",
        passed=dupes == 0,
        detail="All ticket numbers unique" if dupes == 0 else f"{dupes} duplicate ticket number(s)",
    ))

    # 3. Count matches
    invariants.append(InvariantResult(
        name="Count Matches",
        passed=sold == len(ticket_nums),
        detail=f"/status.sold={sold} tickets array length={len(ticket_nums)}",
    ))

    # 4. Idempotency — for every request_id we sent, every response we got
    # back for it (including replays across workers) must carry the same
    # ticket number. This checks actual per-request consistency rather
    # than just bounding the total count.
    by_request_id: dict[str, set[int]] = {}
    for r in all_results:
        for rid, ticket in r.request_results:
            if ticket is None:
                continue
            by_request_id.setdefault(rid, set()).add(ticket)

    violations = {rid: tickets for rid, tickets in by_request_id.items() if len(tickets) > 1}
    invariants.append(InvariantResult(
        name="Idempotency Held",
        passed=len(violations) == 0,
        detail=(
            "Every replayed request_id returned a consistent ticket number"
            if not violations
            else f"{len(violations)} request_id(s) returned different ticket numbers across calls"
        ),
    ))

    return invariants


@click.command()
@click.option("--target", default="http://localhost:8002", help="Seller base URL")
@click.option("--tickets", default=100, help="Ticket count to reset to")
@click.option("--requests", "total_requests", default=10000, help="Total buy requests")
@click.option("--concurrency", default=100, help="Concurrent requests per worker")
@click.option("--workers", default=4, help="Number of worker processes")
@click.option("--duplicate-ratio", default=0.1, help="Fraction of requests that replay a request_id")
@click.option("--user-pool", default=200, help="Number of distinct user IDs")
@click.option("--reset/--no-reset", default=True, help="Reset seller before run")
@click.option("--slow-inject", is_flag=True, help="Inject 200ms datastore delay 3s into the run")
def main(target, tickets, total_requests, concurrency, workers, duplicate_ratio, user_pool, reset, slow_inject):
    console.rule("[bold]Ticket Load Client")
    console.print(f"Target:      {target}")
    console.print(f"Tickets:     {tickets}")
    console.print(f"Requests:    {total_requests}")
    console.print(f"Concurrency: {concurrency} per worker x {workers} workers = {concurrency * workers} total")
    console.print(f"Duplication: {duplicate_ratio * 100:.0f}%")
    console.print()

    if reset:
        import urllib.request
        import json as _json
        req = urllib.request.Request(
            f"{target}/reset",
            data=_json.dumps({"ticket_count": tickets}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req)
        console.print("[green]OK reset complete[/green]")

    if slow_inject:
        import urllib.request
        req = urllib.request.Request(
            f"{target}/debug/slow?seconds=10&delay_ms=200",
            method="POST",
        )
        try:
            urllib.request.urlopen(req)
            console.print("[yellow]Slow injection active: +200ms delay for 10s[/yellow]")
        except Exception as e:
            console.print(f"[red]Could not inject slow delay: {e}[/red]")

    # Build and partition pairs
    pairs = build_pairs(total_requests, duplicate_ratio, user_pool)
    chunk_size = math.ceil(len(pairs) / workers)
    chunks = [pairs[i : i + chunk_size] for i in range(0, len(pairs), chunk_size)]

    result_queue: Queue = multiprocessing.Queue()
    processes = []

    console.print(f"\n[bold]Firing {total_requests:,} requests across {workers} worker processes...[/bold]\n")
    wall_start = time.monotonic()

    for i, chunk in enumerate(chunks):
        p = Process(
            target=run_worker,
            args=(i, target, chunk, concurrency, result_queue),
        )
        p.start()
        processes.append(p)

    for p in processes:
        p.join()

    wall_elapsed_ms = (time.monotonic() - wall_start) * 1000

    # Collect results
    raw_results = []
    while not result_queue.empty():
        raw_results.append(result_queue.get())

    all_results = [WorkerResult(**r) for r in raw_results]

    total = sum(r.total for r in all_results)
    successes = sum(r.successes for r in all_results)
    sold_out = sum(r.sold_out for r in all_results)
    errors = sum(r.errors for r in all_results)
    all_times = [t for r in all_results for t in r.response_times]
    rps = round((total / wall_elapsed_ms) * 1000, 1) if wall_elapsed_ms else 0
    p50 = round(percentile(all_times, 50), 1)
    p99 = round(percentile(all_times, 99), 1)
    min_t = round(min(all_times), 1) if all_times else 0
    max_t = round(max(all_times), 1) if all_times else 0

    # Per-worker breakdown
    console.rule("Per-Worker Results")
    worker_table = Table(box=box.SIMPLE)
    worker_table.add_column("Worker")
    worker_table.add_column("Requests", justify="right")
    worker_table.add_column("Tickets", justify="right")
    worker_table.add_column("Sold Out", justify="right")
    worker_table.add_column("Errors", justify="right")
    worker_table.add_column("RPS", justify="right")
    worker_table.add_column("P99 ms", justify="right")

    for r in sorted(all_results, key=lambda x: x.worker_id):
        w_rps = round((r.total / r.duration_ms) * 1000, 1) if r.duration_ms else 0
        w_p99 = round(percentile(r.response_times, 99), 1)
        worker_table.add_row(
            str(r.worker_id),
            str(r.total),
            str(r.successes),
            str(r.sold_out),
            str(r.errors),
            str(w_rps),
            str(w_p99),
        )

    console.print(worker_table)

    # Aggregate metrics
    console.rule("Aggregate Metrics")
    metrics_table = Table(box=box.SIMPLE, show_header=False)
    metrics_table.add_column("Metric")
    metrics_table.add_column("Value", justify="right")

    for label, value in [
        ("Total Requests", f"{total:,}"),
        ("Tickets Issued", str(successes)),
        ("Sold Out / Waitlisted Responses", str(sold_out)),
        ("Errors", str(errors)),
        ("Wall-clock Duration", f"{wall_elapsed_ms / 1000:.2f}s"),
        ("Requests / Second", f"{rps:,}"),
        ("Median Response Time", f"{p50} ms"),
        ("P99 Response Time", f"{p99} ms"),
        ("Min Response Time", f"{min_t} ms"),
        ("Max Response Time", f"{max_t} ms"),
    ]:
        metrics_table.add_row(label, value)

    console.print(metrics_table)

    # Invariant check
    console.rule("Invariant Check")
    invariants = asyncio.run(verify_invariants(target, tickets, all_results))

    inv_table = Table(box=box.SIMPLE)
    inv_table.add_column("Invariant")
    inv_table.add_column("Result")
    inv_table.add_column("Detail")

    all_passed = True
    for inv in invariants:
        all_passed = all_passed and inv.passed
        result_str = "[green]PASS[/green]" if inv.passed else "[red]FAIL[/red]"
        inv_table.add_row(inv.name, result_str, inv.detail)

    console.print(inv_table)

    verdict = "[bold green]ALL INVARIANTS PASSED[/bold green]" if all_passed else "[bold red]INVARIANTS VIOLATED[/bold red]"
    console.print(Panel(verdict, expand=False))

    # Bottleneck hint
    console.rule("Bottleneck Analysis")
    if p99 > 500:
        console.print("[yellow]P99 > 500ms: seller is saturated. Bottleneck is likely the application layer or Redis.[/yellow]")
    elif p99 > 100:
        console.print("[yellow]P99 > 100ms: moderate pressure. Try increasing workers or concurrency to find the ceiling.[/yellow]")
    else:
        console.print("[green]P99 < 100ms: seller is handling load well. The client is likely the limiting factor if RPS seems low.[/green]")

    if total and errors > total * 0.05:
        console.print(f"[red]Error rate {errors/total*100:.1f}%: check seller logs for 5xx responses.[/red]")


if __name__ == "__main__":
    main()
