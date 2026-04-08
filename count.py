#!/usr/bin/env python3
"""
Count seat statistics from benchmark_numbered.txt.
Prints: total requests, unique seats, and seats that appear more than once.
"""

import sys
from collections import Counter

FILE = sys.argv[1] if len(sys.argv) > 1 else "benchmarks/benchmark_numbered.txt"

seat_counts: Counter = Counter()

with open(FILE) as f:
    for line in f:
        parts = line.strip().split()
        if len(parts) == 4 and parts[0] == "BUY":
            seat_counts[int(parts[2])] += 1

total_requests = sum(seat_counts.values())
unique_seats   = len(seat_counts)
repeated       = {seat: count for seat, count in seat_counts.items() if count > 1}

print(f"File:              {FILE}")
print(f"Total BUY lines:   {total_requests}")
print(f"Unique seat IDs:   {unique_seats}")
print(f"Seats requested once:         {unique_seats - len(repeated)}")
print(f"Seats requested >1 time:      {len(repeated)}")
if repeated:
    top = sorted(repeated.items(), key=lambda x: -x[1])[:10]
    print(f"Top contested seats (seat: count):")
    for seat, count in top:
        print(f"  seat {seat:>6}: {count} requests")
