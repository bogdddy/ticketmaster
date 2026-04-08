"""
Ticket worker service. Runs in two modes:
  direct   — FastAPI HTTP server; receives purchase requests via REST and responds synchronously.
  indirect — RabbitMQ consumer; receives purchase requests from the ticket_requests queue
             and publishes results to ticket_results (or a per-request reply queue).
Consistency is enforced through atomic Redis operations (INCR for unnumbered, SETNX for numbered).
"""

import os
import json
import logging
import threading
import pika
import redis
from datetime import datetime
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

# --------------------------
# Configuration
# --------------------------
RABBITMQ_HOST = os.environ.get("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = int(os.environ.get("RABBITMQ_PORT", 5672))
RABBITMQ_USER = os.environ.get("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.environ.get("RABBITMQ_PASS", "guest")
QUEUE_NAME = "ticket_requests"
RESULT_QUEUE = "ticket_results"

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))

MODE = os.environ.get("MODE", "direct")  # "direct" or "indirect"
PORT = int(os.environ.get("PORT", 8000))

TOTAL_UNNUMBERED = 20000  # Tickets standing
TOTAL_NUMBERED = 20000    # Seats 1..20000

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# --------------------------
# Redis Connection
# --------------------------
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

# --------------------------
# RabbitMQ Connection (for indirect mode and result publishing)
# --------------------------
connection = None
channel = None

def get_rabbitmq_channel():
    """Get or create RabbitMQ channel."""
    global connection, channel
    if channel is None:
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
        parameters = pika.ConnectionParameters(host=RABBITMQ_HOST, port=RABBITMQ_PORT, credentials=credentials)
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        channel.queue_declare(queue=QUEUE_NAME, durable=True)
        channel.queue_declare(queue=RESULT_QUEUE, durable=True)
    return channel

# --------------------------
# Ticket Processing Logic
# --------------------------
def process_unnumbered(client_id: str, request_id: str) -> bool:
    """Process unnumbered ticket purchase. Returns True if successful."""
    sold = r.incr("unnumbered_sold")
    if sold <= TOTAL_UNNUMBERED:
        logger.info(f"[UNNUMBERED] SUCCESS: {client_id} req:{request_id} (sold={sold})")
        return True
    else:
        r.decr("unnumbered_sold")
        logger.info(f"[UNNUMBERED] FAILED: {client_id} req:{request_id} (sold limit reached)")
        return False

def process_numbered(seat_id: int, client_id: str, request_id: str) -> bool:
    """Process numbered seat purchase. Returns True if successful."""
    key = f"seat:{seat_id}"
    success = r.setnx(key, client_id)
    if success:
        r.incr("numbered_sold")
        logger.info(f"[NUMBERED] SUCCESS: {client_id} req:{request_id} seat:{seat_id}")
    else:
        logger.info(f"[NUMBERED] FAILED: {client_id} req:{request_id} seat:{seat_id} already sold")
    return success

def publish_result(request_id: str, client_id: str, seat_id, success: bool, reply_to: str = None):
    """Publish result. If reply_to is set (AMQP reply-queue pattern), send there;
    otherwise send to the default RESULT_QUEUE for the consumer service."""
    result = {
        "request_id": request_id,
        "client_id": client_id,
        "seat_id": seat_id,
        "success": success,
        "timestamp": datetime.utcnow().isoformat()
    }
    try:
        ch = get_rabbitmq_channel()
        ch.basic_publish(
            exchange="",
            routing_key=reply_to if reply_to else RESULT_QUEUE,
            body=json.dumps(result),
            properties=pika.BasicProperties(delivery_mode=2)
        )
    except Exception as e:
        logger.error(f"Failed to publish result: {e}")

# --------------------------
# FastAPI Application (Direct Mode)
# --------------------------
app = FastAPI(title="Ticket Worker", version="1.0")

class BuyRequest(BaseModel):
    client_id: str
    request_id: str

class StatsResponse(BaseModel):
    unnumbered_sold: int
    numbered_sold: int
    unnumbered_remaining: int
    numbered_remaining: int

@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "healthy", "mode": MODE}

@app.post("/buy/unnumbered")
def buy_unnumbered(req: BuyRequest):
    """Buy an unnumbered ticket (direct REST endpoint)."""
    success = process_unnumbered(req.client_id, req.request_id)
    publish_result(req.request_id, req.client_id, None, success)
    return {"success": success, "client_id": req.client_id, "request_id": req.request_id}

@app.post("/buy/numbered/{seat_id}")
def buy_numbered(seat_id: int, req: BuyRequest):
    """Buy a specific numbered seat (direct REST endpoint)."""
    if seat_id < 1 or seat_id > TOTAL_NUMBERED:
        raise HTTPException(status_code=400, detail=f"Seat ID must be between 1 and {TOTAL_NUMBERED}")
    success = process_numbered(seat_id, req.client_id, req.request_id)
    publish_result(req.request_id, req.client_id, seat_id, success)
    return {"success": success, "client_id": req.client_id, "request_id": req.request_id, "seat_id": seat_id}

@app.get("/stats", response_model=StatsResponse)
def get_stats():
    """Get current ticket statistics."""
    unnumbered_sold = int(r.get("unnumbered_sold") or 0)
    numbered_sold = int(r.get("numbered_sold") or 0)
    return StatsResponse(
        unnumbered_sold=unnumbered_sold,
        numbered_sold=numbered_sold,
        unnumbered_remaining=max(0, TOTAL_UNNUMBERED - unnumbered_sold),
        numbered_remaining=max(0, TOTAL_NUMBERED - numbered_sold)
    )

@app.post("/reset")
def reset():
    """Reset all ticket counters and seat assignments."""
    # Reset counters
    r.set("unnumbered_sold", 0)
    r.set("numbered_sold", 0)

    # Delete all seat keys
    keys = r.keys("seat:*")
    if keys:
        r.delete(*keys)

    logger.info("System reset: all counters cleared, all seats available")
    return {"status": "reset", "unnumbered_sold": 0, "numbered_sold": 0}

# --------------------------
# RabbitMQ Consumer (Indirect Mode)
# --------------------------
def rabbitmq_callback(ch, method, properties, body):
    """Callback for RabbitMQ message processing."""
    try:
        msg = json.loads(body)
        type_ = msg.get("type")
        client_id = msg.get("client_id")
        request_id = msg.get("request_id")
        seat_id = msg.get("seat_id")
        reply_to = properties.reply_to if properties else None

        if type_ == "unnumbered":
            success = process_unnumbered(client_id, request_id)
        elif type_ == "numbered":
            success = process_numbered(seat_id, client_id, request_id)
        else:
            success = False
            logger.warning(f"Unknown message type: {type_}")

        publish_result(request_id, client_id, seat_id, success, reply_to=reply_to)
    except Exception as e:
        logger.error(f"Error processing message: {e}")
    finally:
        ch.basic_ack(delivery_tag=method.delivery_tag)

def run_indirect_mode():
    """Run as RabbitMQ consumer (indirect mode)."""
    logger.info("Worker started in INDIRECT mode (RabbitMQ consumer)")

    ch = get_rabbitmq_channel()
    ch.basic_qos(prefetch_count=1)
    ch.basic_consume(queue=QUEUE_NAME, on_message_callback=rabbitmq_callback)

    try:
        ch.start_consuming()
    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
        ch.stop_consuming()
        if connection:
            connection.close()

def run_direct_mode():
    """Run as FastAPI HTTP server (direct mode)."""
    logger.info(f"Worker started in DIRECT mode (HTTP server on port {PORT})")
    uvicorn.run(app, host="0.0.0.0", port=PORT)

# --------------------------
# Main Entry Point
# --------------------------
if __name__ == "__main__":
    # Initialize counters if not exist
    r.setnx("unnumbered_sold", 0)
    r.setnx("numbered_sold", 0)

    if MODE == "indirect":
        run_indirect_mode()
    else:
        run_direct_mode()