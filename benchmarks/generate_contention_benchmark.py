#!/usr/bin/env python3
"""
Generate a high-contention numbered benchmark file.
Additional requirement 2: 80% of requests target 5% of seats (seats 1-1000).
Remaining 20% are spread uniformly across all 20000 seats.
"""

import random
import os

TOTAL_REQUESTS = 25000   # enough to exhaust all 20000 seats
TOTAL_SEATS = 20000
HOT_SEATS = 1000         # 5% of seats = hotspot zone
HOT_RATIO = 0.80         # 80% of requests target the hot zone
OUTPUT_FILE = os.environ.get("OUTPUT_FILE", "benchmarks/benchmark_contention.txt")

random.seed(42)

lines = []
for i in range(TOTAL_REQUESTS):
    client_id = f"c{(i % 500) + 1}"
    request_id = f"r{i + 1}"
    if random.random() < HOT_RATIO:
        seat_id = random.randint(1, HOT_SEATS)
    else:
        seat_id = random.randint(1, TOTAL_SEATS)
    lines.append(f"BUY {client_id} {seat_id} {request_id}")

os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
with open(OUTPUT_FILE, "w") as f:
    f.write(f"# High-contention benchmark: {HOT_RATIO*100:.0f}% of requests target seats 1-{HOT_SEATS}\n")
    f.write("\n".join(lines) + "\n")

print(f"Generated {len(lines)} requests -> {OUTPUT_FILE}")
print(f"  Hot zone:  seats 1-{HOT_SEATS} ({HOT_RATIO*100:.0f}% of traffic)")
print(f"  Cold zone: seats 1-{TOTAL_SEATS} ({(1-HOT_RATIO)*100:.0f}% of traffic)")
