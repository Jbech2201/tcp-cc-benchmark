"""Demo: jalankan keempat algoritma berurutan lalu biarkan jendela terbuka.

    python3 tests/demo_all.py [durasi] [jeda_akhir_detik]
"""

import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tcp_benchmark_gui import CongestionControlBenchmarkGUI  # noqa: E402

DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 10
HOLD = int(sys.argv[2]) if len(sys.argv) > 2 else 30
QUEUE = ["reno", "cubic", "bbr", "vegas"]

root = tk.Tk()
app = CongestionControlBenchmarkGUI(root)


def next_algo():
    if not QUEUE:
        app._set_analysis_text(
            "Perbandingan 4 algoritma selesai. "
            "Baris hijau di tabel = RTT terkecil, throughput tertinggi ada di kolom Thr(Mbps)."
        )
        root.after(HOLD * 1000, lambda: (root.quit(), root.destroy()))
        return
    algo = QUEUE.pop(0)
    app.algo_var.set(algo)
    app.duration_var.set(DURATION)
    app.start_benchmark()
    root.after(200, wait)


def wait():
    if app.is_running:
        root.after(200, wait)
    else:
        root.after(300, next_algo)


root.after(500, next_algo)
root.mainloop()
