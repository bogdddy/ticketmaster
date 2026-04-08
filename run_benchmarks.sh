#!/bin/bash
# run_benchmarks.sh
# Orchestrate benchmark runs for the ticket acquisition system
# Usage: ./run_benchmarks.sh [mode] [type] [workers]
#   mode: direct | indirect (default: direct)
#   type: numbered | unnumbered (default: unnumbered)
#   workers: number of worker replicas (default: 1)

set -e

# --------------------------
# Configuration
# --------------------------
MODE=${1:-direct}
TYPE=${2:-unnumbered}
WORKERS=${3:-1}
RESULTS_DIR="./results"
BENCHMARK_FILE="benchmark_${TYPE}.txt"

# Validate arguments
if [[ "$MODE" != "direct" && "$MODE" != "indirect" ]]; then
    echo "Error: MODE must be 'direct' or 'indirect'"
    echo "Usage: $0 [direct|indirect] [numbered|unnumbered] [workers]"
    exit 1
fi

if [[ "$TYPE" != "numbered" && "$TYPE" != "unnumbered" && "$TYPE" != "contention" ]]; then
    echo "Error: TYPE must be 'numbered', 'unnumbered', or 'contention'"
    echo "Usage: $0 [direct|indirect] [numbered|unnumbered|contention] [workers]"
    echo "Note: generate benchmarks/benchmark_contention.txt first with: python generate_contention_benchmark.py"
    exit 1
fi

echo "=========================================="
echo "BENCHMARK CONFIGURATION"
echo "=========================================="
echo "Mode:       $MODE"
echo "Type:       $TYPE"
echo "Workers:    $WORKERS"
echo "Benchmark:  $BENCHMARK_FILE"
echo "=========================================="

# --------------------------
# Cleanup Previous Results
# --------------------------
echo "[1/6] Cleaning up previous results..."
mkdir -p $RESULTS_DIR
rm -f $RESULTS_DIR/*.jsonl

# --------------------------
# Start Infrastructure
# --------------------------
echo "[2/6] Starting infrastructure (RabbitMQ, Redis)..."
docker-compose up -d rabbitmq redis

# Wait for services to be healthy
echo "Waiting for RabbitMQ..."
sleep 10
until docker-compose exec -T rabbitmq rabbitmq-diagnostics -q ping > /dev/null 2>&1; do
    echo "  RabbitMQ not ready, waiting..."
    sleep 2
done

echo "Waiting for Redis..."
until docker-compose exec -T redis redis-cli ping > /dev/null 2>&1; do
    echo "  Redis not ready, waiting..."
    sleep 2
done

# --------------------------
# Reset System State
# --------------------------
echo "[3/6] Resetting system state..."
# Reset Redis counters
docker-compose exec -T redis redis-cli SET unnumbered_sold 0 > /dev/null
docker-compose exec -T redis redis-cli SET numbered_sold 0 > /dev/null
# Delete all seat keys
docker-compose exec -T redis redis-cli KEYS "seat:*" | xargs -r docker-compose exec -T redis redis-cli DEL > /dev/null 2>&1 || true

# --------------------------
# Start Workers
# --------------------------
echo "[4/6] Starting $WORKERS worker(s) in $MODE mode..."

if [[ "$MODE" == "direct" ]]; then
    # Stop indirect workers if running
    docker-compose stop worker-indirect 2>/dev/null || true
    # Scale direct workers
    docker-compose up -d --build --scale worker-direct=$WORKERS worker-direct
    # Wait for workers to be ready
    sleep 5
else
    # Stop direct workers if running
    docker-compose stop worker-direct 2>/dev/null || true
    # Scale indirect workers
    docker-compose up -d --build --scale worker-indirect=$WORKERS worker-indirect
    # Wait for workers to be ready
    sleep 5
fi

# Start results consumer
docker-compose up -d consumer

# --------------------------
# Run Benchmark
# --------------------------
echo "[5/6] Running benchmark..."

if [[ "$MODE" == "direct" ]]; then
    docker-compose run --rm --build \
        -e MODE=direct \
        -e TICKET_TYPE=$TYPE \
        -e BENCHMARK_FILE=/app/benchmarks/benchmark_${TYPE}.txt \
        -e CLIENT_WORKERS=${CLIENT_WORKERS:-5} \
        -e RESULTS_FILE=/app/results/benchmark_${MODE}_${TYPE}.jsonl \
        client-direct
else
    docker-compose run --rm --build \
        -e MODE=indirect \
        -e TICKET_TYPE=$TYPE \
        -e BENCHMARK_FILE=/app/benchmarks/benchmark_${TYPE}.txt \
        -e CLIENT_WORKERS=${CLIENT_WORKERS:-5} \
        -e RESULTS_FILE=/app/results/benchmark_${MODE}_${TYPE}.jsonl \
        client-indirect
fi

# --------------------------
# Collect Results
# --------------------------
echo "[6/6] Collecting results..."

# Wait for consumer to finish processing
sleep 5

# Show summary
echo ""
echo "=========================================="
echo "BENCHMARK COMPLETE"
echo "=========================================="
echo "Mode:       $MODE"
echo "Type:       $TYPE"
echo "Workers:    $WORKERS"
echo ""

if [[ -f "$RESULTS_DIR/benchmark_${MODE}_${TYPE}.jsonl" ]]; then
    echo "Results:"
    cat $RESULTS_DIR/benchmark_${MODE}_${TYPE}.jsonl
else
    echo "Warning: No results file found"
fi

echo ""
echo "Detailed results saved to: $RESULTS_DIR/"
echo "=========================================="