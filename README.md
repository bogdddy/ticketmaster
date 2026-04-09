# Scalable Concert Ticket Acquisition System

Distributed ticketing system implementing both direct (REST) and indirect (RabbitMQ) communication architectures.

## Quick Start

```bash
# Run benchmark: ./run_benchmarks.sh [direct|indirect] [numbered|unnumbered|contention] [workers]
./run_benchmarks.sh direct  unnumbered 5
./run_benchmarks.sh direct  numbered   5
./run_benchmarks.sh indirect unnumbered 5
./run_benchmarks.sh indirect numbered   5

# Generate plots 
pip install -r requirements-dev.txt
python plots/generate_plots.py

# View results and plots
ls results/
ls plots/
```

## Architecture

### Direct (REST)
```
Client → NGINX:80 → Worker:8000 → Redis:6379
```

### Indirect (RabbitMQ)
```
Client → RabbitMQ:5672 → Worker → Redis:6379
                                 ↓
                          Consumer → results/
```

## Project Structure

```
ticketing/
├── benchmarks/
│   ├── benchmark_numbered.txt          # Numbered-seat benchmark requests
│   ├── benchmark_unnumbered.txt        # Unnumbered-ticket benchmark requests
│   └── generate_contention_benchmark.py# Generate high-contention benchmark
├── client/
│   ├── client.py                       # Benchmark driver (direct + indirect)
│   ├── requirements.txt
│   └── Dockerfile
├── consumer/
│   ├── consumer.py                     # Reads ticket_results queue → JSONL
│   ├── requirements.txt
│   └── Dockerfile
├── worker/
│   ├── worker.py                       # FastAPI REST + RabbitMQ consumer
│   ├── requirements.txt
│   └── Dockerfile
├── docs/
│   ├── deploy.txt                     # Full deployment guide
│   └── specifications.txt             # Assignment requirements
├── plots/
│   └── generate_plots.py              # Generate PNG charts from results
├── results/                           # JSONL output files
├── docker-compose.yaml
├── nginx.conf
├── run_benchmarks.sh                  # Orchestrates a full benchmark run
└── requirements-dev.txt               # plot generation
```

## API Endpoints (Direct Mode)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/buy/unnumbered` | POST | Buy unnumbered ticket |
| `/buy/numbered/{seat_id}` | POST | Buy a specific numbered seat |
| `/stats` | GET | Get current ticket statistics |
| `/reset` | POST | Reset all counters and seat assignments |

## Benchmark Results

Results are saved to `results/benchmark_<mode>_<type>.jsonl` in JSONL format.

```json
{"mode": "direct", "ticket_type": "unnumbered", "total_requests": 20000,
 "successful": 20000, "failed": 0, "total_time_seconds": 33.1,
 "throughput_ops_per_second": 604.5, "client_workers": 50}
```

## Deployment

[docs/deploy.txt](docs/deploy.txt).
