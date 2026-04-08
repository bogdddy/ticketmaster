#!/usr/bin/env python3
"""
Benchmark client for ticket acquisition system.
Supports both direct (REST) and indirect (RabbitMQ) communication modes.

Indirect-mode result counting strategy:
  Fire-and-forget publishing is fast, but success/fail is only known after
  workers process each message.  After publishing, we poll the ticket_requests
  queue until it drains, then read the authoritative counters from Redis.
"""

import os
import json
import logging
import time
import threading
import requests
import pika
import redis as redis_lib
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue

# --------------------------
# Configuration
# --------------------------
MODE           = os.environ.get("MODE", "direct")
API_URL        = os.environ.get("API_URL", "http://nginx:80")
RABBITMQ_HOST  = os.environ.get("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT  = int(os.environ.get("RABBITMQ_PORT", 5672))
RABBITMQ_USER  = os.environ.get("RABBITMQ_USER", "guest")
RABBITMQ_PASS  = os.environ.get("RABBITMQ_PASS", "guest")
REDIS_HOST     = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT     = int(os.environ.get("REDIS_PORT", 6379))
BENCHMARK_FILE = os.environ.get("BENCHMARK_FILE", "/app/benchmark.txt")
TICKET_TYPE    = os.environ.get("TICKET_TYPE", "unnumbered")
CLIENT_WORKERS = int(os.environ.get("CLIENT_WORKERS", 5))
RESULTS_FILE   = os.environ.get("RESULTS_FILE", "/app/results/benchmark_results.jsonl")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

stats = {"total_requests": 0, "successful": 0, "failed": 0,
         "start_time": None, "end_time": None}
stats_lock = threading.Lock()

# --------------------------
# RabbitMQ helpers
# --------------------------
def _make_pika_params():
    return pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        credentials=pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS),
        heartbeat=60,
    )

# --------------------------
# Channel pool (indirect publish phase)
# pika.BlockingConnection is NOT thread-safe — pre-create a fixed pool of
# (connection, channel) pairs sequentially, stored in a thread-safe Queue.
# --------------------------
_channel_pool: Queue = Queue()
POOL_SIZE = min(CLIENT_WORKERS, 20)

def init_channel_pool():
    for _ in range(POOL_SIZE):
        conn = pika.BlockingConnection(_make_pika_params())
        ch   = conn.channel()
        ch.queue_declare(queue="ticket_requests", durable=True)
        _channel_pool.put((conn, ch))
    logger.info(f"RabbitMQ channel pool ready ({POOL_SIZE} connections)")

def close_channel_pool():
    while not _channel_pool.empty():
        try:
            conn, _ = _channel_pool.get_nowait()
            if conn.is_open:
                conn.close()
        except Exception:
            pass

# --------------------------
# Indirect-mode result verification
# --------------------------
def wait_for_queue_drain(timeout: int = 300):
    """Block until ticket_requests queue is empty (all messages processed)."""
    conn = pika.BlockingConnection(_make_pika_params())
    ch   = conn.channel()
    try:
        deadline = time.time() + timeout
        while time.time() < deadline:
            res       = ch.queue_declare(queue="ticket_requests", durable=True, passive=True)
            remaining = res.method.message_count
            if remaining == 0:
                logger.info("Queue drained — all messages processed by workers")
                return
            logger.info(f"Waiting for workers: {remaining} messages remaining...")
            time.sleep(1)
        logger.warning("Timeout waiting for queue to drain — results may be incomplete")
    finally:
        conn.close()

def read_redis_counts() -> dict:
    """Read the authoritative ticket counters directly from Redis."""
    r = redis_lib.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    return {
        "unnumbered_sold": int(r.get("unnumbered_sold") or 0),
        "numbered_sold":   int(r.get("numbered_sold")   or 0),
    }

# --------------------------
# Request functions
# --------------------------
def send_direct_unnumbered(client_id: str, request_id: str) -> dict:
    try:
        resp = requests.post(f"{API_URL}/buy/unnumbered",
                             json={"client_id": client_id, "request_id": request_id},
                             timeout=30)
        return resp.json()
    except Exception as e:
        logger.error(f"Direct request failed: {e}")
        return {"success": False, "error": str(e)}

def send_direct_numbered(client_id: str, seat_id: int, request_id: str) -> dict:
    try:
        resp = requests.post(f"{API_URL}/buy/numbered/{seat_id}",
                             json={"client_id": client_id, "request_id": request_id},
                             timeout=30)
        return resp.json()
    except Exception as e:
        logger.error(f"Direct request failed: {e}")
        return {"success": False, "error": str(e)}

def send_indirect_unnumbered(client_id: str, request_id: str) -> dict:
    conn, ch = _channel_pool.get()
    try:
        ch.basic_publish(
            exchange="", routing_key="ticket_requests",
            body=json.dumps({"type": "unnumbered",
                             "client_id": client_id, "request_id": request_id}),
            properties=pika.BasicProperties(delivery_mode=2),
        )
        return {"queued": True}
    except Exception as e:
        logger.error(f"Indirect publish failed: {e}")
        return {"queued": False, "error": str(e)}
    finally:
        _channel_pool.put((conn, ch))

def send_indirect_numbered(client_id: str, seat_id: int, request_id: str) -> dict:
    conn, ch = _channel_pool.get()
    try:
        ch.basic_publish(
            exchange="", routing_key="ticket_requests",
            body=json.dumps({"type": "numbered", "seat_id": seat_id,
                             "client_id": client_id, "request_id": request_id}),
            properties=pika.BasicProperties(delivery_mode=2),
        )
        return {"queued": True}
    except Exception as e:
        logger.error(f"Indirect publish failed: {e}")
        return {"queued": False, "error": str(e)}
    finally:
        _channel_pool.put((conn, ch))

# --------------------------
# Benchmark processing
# --------------------------
def parse_line(line: str):
    parts = line.strip().split()
    if not parts or parts[0] != "BUY":
        return None
    if len(parts) == 4:
        return ("numbered",   parts[1], int(parts[2]), parts[3])
    if len(parts) == 3:
        return ("unnumbered", parts[1], parts[2])
    return None

def process_request(line_data):
    """Send one request. Direct mode counts success immediately from the HTTP
    response. Indirect mode only fires-and-forgets; counts come from Redis
    after the queue drains."""
    if line_data is None:
        return None

    with stats_lock:
        stats["total_requests"] += 1

    if MODE == "direct":
        if line_data[0] == "unnumbered":
            result  = send_direct_unnumbered(line_data[1], line_data[2])
        else:
            result  = send_direct_numbered(line_data[1], line_data[2], line_data[3])
        success = result.get("success", False)
        with stats_lock:
            if success:
                stats["successful"] += 1
            else:
                stats["failed"] += 1
    else:
        if line_data[0] == "unnumbered":
            result  = send_indirect_unnumbered(line_data[1], line_data[2])
        else:
            result  = send_indirect_numbered(line_data[1], line_data[2], line_data[3])
        success = result.get("queued", False)

    return {"line_data": line_data, "success": success}

def run_benchmark():
    logger.info(f"Starting benchmark: MODE={MODE}, TYPE={TICKET_TYPE}, WORKERS={CLIENT_WORKERS}")
    logger.info(f"Benchmark file: {BENCHMARK_FILE}")

    if MODE == "indirect":
        init_channel_pool()

    requests_list = []
    with open(BENCHMARK_FILE) as f:
        for line in f:
            parsed = parse_line(line)
            if parsed:
                requests_list.append(parsed)
    logger.info(f"Loaded {len(requests_list)} requests")

    with stats_lock:
        stats.update({"total_requests": 0, "successful": 0, "failed": 0,
                      "start_time": time.time(), "end_time": None})

    # Phase 1 — send / publish all requests
    with ThreadPoolExecutor(max_workers=CLIENT_WORKERS) as executor:
        futures = [executor.submit(process_request, r) for r in requests_list]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                logger.error(f"Request error: {e}")

    if MODE == "indirect":
        # Phase 2 — wait for workers to finish, then read authoritative counts
        close_channel_pool()
        wait_for_queue_drain()

        redis_counts = read_redis_counts()
        key = "unnumbered_sold" if TICKET_TYPE == "unnumbered" else "numbered_sold"
        successful = min(redis_counts[key], stats["total_requests"])
        with stats_lock:
            stats["successful"] = successful
            stats["failed"]     = stats["total_requests"] - successful

    with stats_lock:
        stats["end_time"] = time.time()

    total_time = stats["end_time"] - stats["start_time"]
    throughput  = stats["total_requests"] / total_time if total_time > 0 else 0

    summary = {
        "mode": MODE, "ticket_type": TICKET_TYPE,
        "total_requests": stats["total_requests"],
        "successful":     stats["successful"],
        "failed":         stats["failed"],
        "total_time_seconds":       round(total_time, 2),
        "throughput_ops_per_second": round(throughput, 2),
        "client_workers": CLIENT_WORKERS,
        "timestamp": datetime.utcnow().isoformat(),
    }

    logger.info("=" * 60)
    logger.info("BENCHMARK RESULTS")
    logger.info("=" * 60)
    for k, v in summary.items():
        logger.info(f"  {k}: {v}")
    logger.info("=" * 60)

    os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)
    with open(RESULTS_FILE, "a") as f:
        f.write(json.dumps(summary) + "\n")
    logger.info(f"Results saved to {RESULTS_FILE}")

if __name__ == "__main__":
    logger.info("Waiting for services to be ready...")
    time.sleep(5)
    run_benchmark()
