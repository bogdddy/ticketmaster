# Scalable Concert Ticket Acquisition System

Distributed ticketing system implementing both direct (REST) and indirect (RabbitMQ) communication architectures.

## Quick Start

```bash
# Run benchmark: ./run_benchmarks.sh [direct|indirect] [numbered|unnumbered] [workers]
./run_benchmarks.sh direct unnumbered 50
./run_benchmarks.sh direct numbered 50
./run_benchmarks.sh indirect unnumbered 50
./run_benchmarks.sh indirect numbered 50

# Generate plots
pip install -r requirements-dev.txt
python generate_plots.py

# View results
ls -la plots/
```

## Architecture

### Direct (REST)
```
Client → NGINX:80 → Worker:8000 → Redis:6379
```

### Indirect (RabbitMQ)
```
Client → RabbitMQ:5672 → Worker → Redis:6379
```

## Project Structure

```
ticketing/
├── worker/
│   ├── main.py           # FastAPI app + RabbitMQ consumer
│   ├── requirements.txt
│   └── Dockerfile
├── client/
│   ├── client.py         # Benchmark runner
│   ├── requirements.txt
│   └── Dockerfile
├── docker-compose.yml
├── nginx.conf
├── run_benchmarks.sh     # Run any of 4 combinations
├── generate_plots.py     # Generate performance plots
└── benchmark_*.txt       # Benchmark files
```

## Environment Variables

### Worker
| Variable | Default | Description |
|----------|---------|-------------|
| REDIS_HOST | localhost | Redis hostname |
| RABBITMQ_HOST | localhost | RabbitMQ hostname |
| MODE | direct | `direct` or `indirect` |
| PORT | 8000 | FastAPI port |

### Client
| Variable | Default | Description |
|----------|---------|-------------|
| API_URL | http://localhost:80 | Worker/NGINX URL |
| MODE | direct | `direct` or `indirect` |
| CLIENT_WORKERS | 50 | Concurrent client threads |

## API Endpoints (Direct Mode)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/buy/unnumbered` | POST | Buy unnumbered ticket |
| `/buy/numbered/{seat_id}` | POST | Buy numbered ticket |
| `/stats` | GET | Get statistics |
| `/reset` | POST | Reset system |

## Benchmark Results

Results are saved to `results/results.jsonl` in JSONL format.
Plots are generated in `plots/` directory.
