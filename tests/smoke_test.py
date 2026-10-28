"""Smoke test headless-friendly untuk tcp_benchmark_gui.py.

Menjalankan dua benchmark simulasi (reno & bbr) lalu mengekspor CSV
dengan dialog yang di-monkeypatch, sehingga bisa dijalankan otomatis.

    python3 tests/smoke_test.py
"""

import csv
import os
import sys
import tempfile
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tcp_benchmark_gui import CongestionControlBenchmarkGUI  # noqa: E402
from tkinter import filedialog, messagebox  # noqa: E402

SEQUENCE = ["reno", "bbr"]
DURATION = 5
TMP_CSV = os.path.join(tempfile.gettempdir(), "tcp_cc_smoke.csv")

results = []
errors = []


def run_next(root, app):
    if not SEQUENCE:
        finish(root, app)
        return
    algo = SEQUENCE.pop(0)
    app.algo_var.set(algo)
    app.duration_var.set(DURATION)
    app.start_benchmark()
    wait_for_done(root, app, algo)


def wait_for_done(root, app, algo):
    def poll():
        if app.is_running:
            root.after(100, poll)
            return
        data = app.history_data.get(algo.upper())
        if not data:
            errors.append(f"{algo}: tidak ada data histori")
        else:
            if len(data["time"]) != DURATION:
                errors.append(f"{algo}: {len(data['time'])} sampel, harusnya {DURATION}")
            if not all(v >= 0 for v in data["thr"]):
                errors.append(f"{algo}: throughput negatif")
            results.append((algo, len(data["time"])))
        run_next(root, app)

    root.after(100, poll)


def finish(root, app):
    rows = app.tree.get_children()
    if len(rows) != 2:
        errors.append(f"tabel analisis berisi {len(rows)} baris, harusnya 2")

    # Monkeypatch dialog supaya export berjalan otomatis
    filedialog.asksaveasfilename = lambda **kwargs: TMP_CSV
    messagebox.showinfo = lambda *a, **k: None
    messagebox.showwarning = lambda *a, **k: None
    messagebox.showerror = lambda *a, **k: None

    app.export_csv()
    if not os.path.exists(TMP_CSV):
        errors.append("file CSV tidak dibuat")
    else:
        with open(TMP_CSV, newline="", encoding="utf-8") as fh:
            content = list(csv.reader(fh))
        if len(content) != 1 + 2 * DURATION:
            errors.append(f"CSV berisi {len(content)} baris, harusnya {1 + 2 * DURATION}")
        else:
            os.remove(TMP_CSV)

    root.quit()
    root.destroy()


def main():
    root = tk.Tk()
    app = CongestionControlBenchmarkGUI(root)
    root.after(300, lambda: run_next(root, app))
    root.mainloop()

    print("Hasil benchmark:", results)
    if errors:
        print("GAGAL:")
        for err in errors:
            print("  -", err)
        sys.exit(1)
    print("OK: simulasi, grafik, tabel analisis, dan export CSV berjalan.")


if __name__ == "__main__":
    main()
