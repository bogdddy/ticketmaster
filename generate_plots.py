#!/usr/bin/env python3
"""
Generate performance plots from benchmark results.
Reads JSONL results and generates comparison charts.
"""

import os
import json
import glob
from datetime import datetime
import matplotlib.pyplot as plt
import pandas as pd

# Configuration
RESULTS_DIR = os.environ.get("RESULTS_DIR", "./results")
PLOTS_DIR = os.environ.get("PLOTS_DIR", "./plots")


def load_results():
    """Load all JSONL result files from results directory."""
    results = []
    for filepath in glob.glob(os.path.join(RESULTS_DIR, "*.jsonl")):
        with open(filepath, 'r') as f:
            for line in f:
                if line.strip():
                    try:
                        results.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    return results


def create_dataframe(results):
    """Convert results to pandas DataFrame."""
    if not results:
        print("No results found")
        return None

    df = pd.DataFrame(results)
    return df


def plot_throughput_vs_workers(df, output_dir):
    """Plot throughput vs number of workers for each mode/type combination."""
    if df is None or df.empty:
        return

    fig, ax = plt.subplots(figsize=(10, 6))

    # Group by mode and type
    for (mode, ticket_type), group in df.groupby(['mode', 'ticket_type']):
        label = f"{mode.upper()} - {ticket_type}"
        sorted_group = group.sort_values('client_workers')
        ax.plot(sorted_group['client_workers'],
                sorted_group['throughput_ops_per_second'],
                marker='o', label=label)

    ax.set_xlabel('Number of Client Workers')
    ax.set_ylabel('Throughput (ops/sec)')
    ax.set_title('Throughput vs Client Workers')
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'throughput_vs_workers.png'), dpi=150)
    plt.close()
    print(f"Saved: throughput_vs_workers.png")


def plot_mode_comparison(df, output_dir):
    """Compare direct vs indirect modes."""
    if df is None or df.empty:
        return

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # Throughput comparison
    ax1 = axes[0]
    modes = ['direct', 'indirect']
    x = range(len(modes))
    throughput_means = []
    throughput_stds = []

    for mode in modes:
        mode_df = df[df['mode'] == mode]
        if not mode_df.empty:
            throughput_means.append(mode_df['throughput_ops_per_second'].mean())
            throughput_stds.append(mode_df['throughput_ops_per_second'].std())
        else:
            throughput_means.append(0)
            throughput_stds.append(0)

    ax1.bar(x, throughput_means, yerr=throughput_stds, capsize=5, color=['#3498db', '#e74c3c'])
    ax1.set_xticks(x)
    ax1.set_xticklabels([m.upper() for m in modes])
    ax1.set_ylabel('Throughput (ops/sec)')
    ax1.set_title('Average Throughput by Mode')
    ax1.grid(True, alpha=0.3, axis='y')

    # Success rate comparison
    ax2 = axes[1]
    success_rates = []
    for mode in modes:
        mode_df = df[df['mode'] == mode]
        if not mode_df.empty:
            total = mode_df['total_requests'].sum()
            successful = mode_df['successful'].sum()
            success_rates.append((successful / total * 100) if total > 0 else 0)
        else:
            success_rates.append(0)

    ax2.bar(x, success_rates, color=['#3498db', '#e74c3c'])
    ax2.set_xticks(x)
    ax2.set_xticklabels([m.upper() for m in modes])
    ax2.set_ylabel('Success Rate (%)')
    ax2.set_title('Success Rate by Mode')
    ax2.set_ylim(0, 105)
    ax2.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'mode_comparison.png'), dpi=150)
    plt.close()
    print(f"Saved: mode_comparison.png")


def plot_type_comparison(df, output_dir):
    """Compare numbered vs unnumbered ticket types."""
    if df is None or df.empty:
        return

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # Throughput by ticket type
    ax1 = axes[0]
    types = ['numbered', 'unnumbered']
    x = range(len(types))

    throughput_by_type = []
    for t in types:
        type_df = df[df['ticket_type'] == t]
        if not type_df.empty:
            throughput_by_type.append(type_df['throughput_ops_per_second'].mean())
        else:
            throughput_by_type.append(0)

    ax1.bar(x, throughput_by_type, color=['#2ecc71', '#9b59b6'])
    ax1.set_xticks(x)
    ax1.set_xticklabels([t.upper() for t in types])
    ax1.set_ylabel('Throughput (ops/sec)')
    ax1.set_title('Average Throughput by Ticket Type')
    ax1.grid(True, alpha=0.3, axis='y')

    # Processing time comparison
    ax2 = axes[1]
    time_by_type = []
    for t in types:
        type_df = df[df['ticket_type'] == t]
        if not type_df.empty:
            time_by_type.append(type_df['total_time_seconds'].mean())
        else:
            time_by_type.append(0)

    ax2.bar(x, time_by_type, color=['#2ecc71', '#9b59b6'])
    ax2.set_xticks(x)
    ax2.set_xticklabels([t.upper() for t in types])
    ax2.set_ylabel('Total Time (seconds)')
    ax2.set_title('Average Processing Time by Ticket Type')
    ax2.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'type_comparison.png'), dpi=150)
    plt.close()
    print(f"Saved: type_comparison.png")


def plot_summary(df, output_dir):
    """Generate summary table plot."""
    if df is None or df.empty:
        return

    fig, ax = plt.subplots(figsize=(12, len(df) * 0.5 + 2))
    ax.axis('off')

    # Prepare summary data
    summary_cols = ['mode', 'ticket_type', 'client_workers', 'total_requests',
                    'successful', 'failed', 'throughput_ops_per_second', 'total_time_seconds']
    summary_df = df[summary_cols].round(2)

    table = ax.table(cellText=summary_df.values,
                     colLabels=summary_cols,
                     cellLoc='center',
                     loc='center')
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.2, 1.5)

    plt.title('Benchmark Results Summary', fontsize=14, fontweight='bold', pad=20)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'summary_table.png'), dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: summary_table.png")


def generate_plots():
    """Main function to generate all plots."""
    print(f"Loading results from: {RESULTS_DIR}")
    print(f"Output directory: {PLOTS_DIR}")

    # Ensure output directory exists
    os.makedirs(PLOTS_DIR, exist_ok=True)

    # Load and process results
    results = load_results()
    if not results:
        print("No results found. Run benchmarks first.")
        return

    df = create_dataframe(results)
    if df is None:
        return

    print(f"Loaded {len(df)} benchmark result(s)")
    print(f"Columns: {list(df.columns)}")

    # Generate plots
    plot_throughput_vs_workers(df, PLOTS_DIR)
    plot_mode_comparison(df, PLOTS_DIR)
    plot_type_comparison(df, PLOTS_DIR)
    plot_summary(df, PLOTS_DIR)

    # Save raw data
    df.to_csv(os.path.join(PLOTS_DIR, 'results.csv'), index=False)
    print(f"Saved: results.csv")

    print("\nPlot generation complete!")


if __name__ == "__main__":
    generate_plots()