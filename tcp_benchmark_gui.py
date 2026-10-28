#!/usr/bin/env python3
"""
TCP Congestion Control Benchmark & Analyzer
===========================================

Aplikasi GUI untuk membandingkan perilaku algoritma TCP Congestion Control
(reno, cubic, bbr, vegas) dalam dua mode:

1. Simulasi  : model matematis tiap algoritma, jalan di semua OS tanpa root.
2. Real      : benchmark jaringan asli memakai iperf3 (Linux).

Jalankan:  python3 tcp_benchmark_gui.py
"""

import csv
import json
import shutil
import subprocess
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

import matplotlib
import numpy as np

matplotlib.use("TkAgg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg  # noqa: E402

ALGORITHMS = ["reno", "cubic", "bbr", "vegas"]
COLORS = {"RENO": "#e84118", "CUBIC": "#0097e6", "BBR": "#4cd137", "VEGAS": "#9c88ff"}
MARKERS = {"thr": "o", "rtt": "s", "cwnd": "^"}

SIMULATION_STEP = 0.3  # 0,3 detik nyata = 1 detik simulasi


class CongestionControlBenchmarkGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("TCP Congestion Control Benchmark & Analyzer")
        # Ukuran jendela menyesuaikan layar (aman untuk HiDPI / Xft.dpi tinggi)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w, h = min(int(sw * 0.9), 1560), min(int(sh * 0.92), 1200)
        self.root.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}")
        self.root.minsize(min(1100, w), min(700, h))
        self.root.configure(bg="#f5f6fa")

        # Histori hasil per algoritma -> untuk overlay & perbandingan
        self.history_data = {}
        self.analysis_cache = {}
        self.is_running = False
        self._stop_requested = False

        self.setup_ui()

    # ------------------------------------------------------------------ UI
    def setup_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#f5f6fa")
        style.configure("TLabel", background="#f5f6fa", font=("Segoe UI", 10))
        style.configure("Header.TLabel", font=("Segoe UI", 11, "bold"), foreground="#2f3640")
        style.configure("TButton", font=("Segoe UI", 10, "bold"), padding=6)
        body_font = tkfont.Font(root=self.root, family="Segoe UI", size=9)
        style.configure("Treeview", rowheight=body_font.metrics("linespace") + 8, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

        # ================= PANEL KIRI (KONTROL & ANALISIS) =================
        left_panel = ttk.Frame(self.root, padding=(14, 12), width=470)
        left_panel.pack(side=tk.LEFT, fill=tk.Y)
        left_panel.pack_propagate(False)

        # --- Bagian 1: Konfigurasi ---
        ttk.Label(left_panel, text="⚙️ Konfigurasi Benchmark", style="Header.TLabel").pack(anchor=tk.W, pady=(0, 8))

        ttk.Label(left_panel, text="Mode Pengujian:").pack(anchor=tk.W)
        self.mode_var = tk.StringVar(value="Simulasi (Tanpa Root/Iperf)")
        self.mode_cb = ttk.Combobox(
            left_panel,
            textvariable=self.mode_var,
            state="readonly",
            values=["Simulasi (Tanpa Root/Iperf)", "Real Network (Linux iperf3)"],
        )
        self.mode_cb.pack(fill=tk.X, pady=(2, 8))
        self.mode_cb.bind("<<ComboboxSelected>>", self.toggle_mode)

        ttk.Label(left_panel, text="Algoritma Congestion Control:").pack(anchor=tk.W)
        self.algo_var = tk.StringVar(value="cubic")
        self.algo_cb = ttk.Combobox(left_panel, textvariable=self.algo_var, state="readonly", values=ALGORITHMS)
        self.algo_cb.pack(fill=tk.X, pady=(2, 8))

        ttk.Label(left_panel, text="Durasi Ambil Data (detik):").pack(anchor=tk.W)
        self.duration_var = tk.IntVar(value=15)
        self.duration_spin = ttk.Spinbox(left_panel, from_=5, to=120, textvariable=self.duration_var)
        self.duration_spin.pack(fill=tk.X, pady=(2, 8))

        ttk.Label(left_panel, text="Target Server iperf3 (IP):").pack(anchor=tk.W)
        self.server_var = tk.StringVar(value="127.0.0.1")
        self.server_entry = ttk.Entry(left_panel, textvariable=self.server_var, state="disabled")
        self.server_entry.pack(fill=tk.X, pady=(2, 12))

        self.btn_start = tk.Button(
            left_panel, text="▶ Mulai Benchmark", bg="#4cd137", fg="white",
            font=("Segoe UI", 10, "bold"), relief=tk.FLAT, activebackground="#44bd32",
            command=self.start_benchmark,
        )
        self.btn_start.pack(fill=tk.X, pady=3)

        self.btn_clear = tk.Button(
            left_panel, text="🗑 Reset Grafik & Data", bg="#e84118", fg="white",
            font=("Segoe UI", 10, "bold"), relief=tk.FLAT, activebackground="#c23616",
            command=self.clear_data,
        )
        self.btn_clear.pack(fill=tk.X, pady=3)

        self.btn_export = tk.Button(
            left_panel, text="💾 Export Hasil (CSV)", bg="#00a8ff", fg="white",
            font=("Segoe UI", 10, "bold"), relief=tk.FLAT, activebackground="#0097e6",
            command=self.export_csv,
        )
        self.btn_export.pack(fill=tk.X, pady=3)

        self.progress = ttk.Progressbar(left_panel, orient=tk.HORIZONTAL, mode="determinate")
        self.progress.pack(fill=tk.X, pady=(12, 6))
        self.status_label = ttk.Label(left_panel, text="Status: Siap", foreground="#718093", wraplength=370)
        self.status_label.pack(anchor=tk.W)

        ttk.Separator(left_panel, orient="horizontal").pack(fill=tk.X, pady=10)

        # --- Bagian 2: Hasil Analisis ---
        ttk.Label(left_panel, text="📊 Hasil Analisis Data", style="Header.TLabel").pack(anchor=tk.W, pady=(0, 6))

        columns = ("Algo", "Thr(Mbps)", "RTT(ms)", "JFI")
        col_widths = {"Algo": 90, "Thr(Mbps)": 120, "RTT(ms)": 118, "JFI": 85}
        self.tree = ttk.Treeview(left_panel, columns=columns, show="headings", height=4)
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=col_widths[col], minwidth=60, anchor=tk.CENTER)
        self.tree.pack(fill=tk.X, pady=4)

        text_frame = ttk.Frame(left_panel)
        text_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        self.analysis_text = tk.Text(
            text_frame, height=8, width=42, font=("DejaVu Sans Mono", 9),
            bg="#dcdde1", relief=tk.FLAT, wrap=tk.WORD, padx=8, pady=8,
        )
        scroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.analysis_text.yview)
        self.analysis_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.analysis_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._set_analysis_text("Jalankan benchmark untuk melihat analisis detail algoritma...")

        # ================= PANEL KANAN (GRAFIK VISUALISASI) =================
        right_panel = ttk.Frame(self.root, padding="10")
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.fig, (self.ax_thr, self.ax_rtt, self.ax_cwnd) = plt.subplots(3, 1, figsize=(8, 7), dpi=100)
        self.fig.patch.set_facecolor("#f5f6fa")
        self.fig.subplots_adjust(hspace=0.45, left=0.09, right=0.98, top=0.95, bottom=0.07)
        self.setup_axes()

        self.canvas = FigureCanvasTkAgg(self.fig, master=right_panel)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def setup_axes(self):
        self.ax_thr.set_title("Throughput terhadap Waktu", fontsize=11, fontweight="bold")
        self.ax_thr.set_ylabel("Mbps")
        self.ax_thr.grid(True, linestyle="--", alpha=0.6)

        self.ax_rtt.set_title("Round Trip Time (Latency / RTT)", fontsize=11, fontweight="bold")
        self.ax_rtt.set_ylabel("ms")
        self.ax_rtt.grid(True, linestyle="--", alpha=0.6)

        self.ax_cwnd.set_title("Congestion Window (CWND) / Retransmits", fontsize=11, fontweight="bold")
        self.ax_cwnd.set_xlabel("Waktu (Detik)")
        self.ax_cwnd.set_ylabel("CWND (KB)")
        self.ax_cwnd.grid(True, linestyle="--", alpha=0.6)

    def _set_analysis_text(self, text):
        self.analysis_text.config(state=tk.NORMAL)
        self.analysis_text.delete(1.0, tk.END)
        self.analysis_text.insert(tk.END, text)
        self.analysis_text.config(state=tk.DISABLED)

    # ------------------------------------------------------------- Kontrol
    def toggle_mode(self, event=None):
        real = "Real" in self.mode_var.get()
        self.server_entry.config(state="normal" if real else "disabled")
        if real and not shutil.which("iperf3"):
            self.status_label.config(text="Status: iperf3 tidak ditemukan di PATH!", foreground="#e84118")
        else:
            self.status_label.config(text="Status: Siap", foreground="#718093")

    def _read_duration(self):
        try:
            duration = int(self.duration_spin.get())
        except (ValueError, tk.TclError):
            messagebox.showerror("Input tidak valid", "Durasi harus berupa angka bulat (5-120 detik).")
            return None
        if not 5 <= duration <= 120:
            messagebox.showerror("Input tidak valid", "Durasi harus di antara 5 dan 120 detik.")
            return None
        return duration

    def start_benchmark(self):
        if self.is_running:
            return

        algo = self.algo_var.get()
        mode = self.mode_var.get()
        duration = self._read_duration()
        if duration is None:
            return

        if "Real" in mode and not shutil.which("iperf3"):
            messagebox.showerror(
                "iperf3 tidak ditemukan",
                "Mode Real membutuhkan iperf3.\n\nInstall dengan:\n  sudo apt install iperf3\n\n"
                "Atau gunakan Mode Simulasi.",
            )
            return

        self.is_running = True
        self._stop_requested = False
        self.btn_start.config(state="disabled", bg="#7f8fa6", text="⏳ Menjalankan...")
        self.progress["value"] = 0
        self.progress["maximum"] = duration
        self.status_label.config(text=f"Status: Menyiapkan [{algo.upper()}]...", foreground="#718093")

        # Jalankan di thread terpisah agar GUI tidak freeze
        thread = threading.Thread(target=self.run_process, args=(algo, duration, mode), daemon=True)
        thread.start()

    def run_process(self, algo, duration, mode):
        try:
            if "Simulasi" in mode:
                self.run_simulation(algo, duration)
            else:
                self.run_real_iperf(algo, duration)
        except Exception as exc:  # jangan biarkan thread mati diam-diam
            self.root.after(0, lambda e=exc: messagebox.showerror("Error", f"Benchmark gagal:\n{e}"))
        finally:
            self.root.after(0, self.finish_benchmark)

    # ----------------------------------------------------------- Simulasi
    def run_simulation(self, algo, duration):
        """
        Mensimulasikan perilaku matematis algoritma TCP Congestion Control:
        - Reno : sawtooth klasik (AIMD - Additive Increase Multiplicative Decrease)
        - Cubic: fungsi kubik, agresif, rentan bufferbloat
        - BBR  : throughput tinggi & stabil, RTT minimal (queue tetap kosong)
        - Vegas: berbasis delay, RTT rendah tapi throughput lebih rendah
        """
        timestamps, throughputs, rtts, cwnds = [], [], [], []

        cwnd = 10.0
        base_rtt = 25.0  # ms
        bottleneck_bw = 100.0  # Mbps

        for t in range(1, duration + 1):
            if self._stop_requested:
                break
            time.sleep(SIMULATION_STEP)

            if algo == "reno":
                cwnd += 8  # Additive Increase
                if cwnd > 85 or np.random.rand() < 0.15:  # Loss event
                    cwnd *= 0.5  # Multiplicative Decrease
                thr = min(bottleneck_bw, cwnd * 1.15 + np.random.normal(0, 2))
                rtt = base_rtt + (cwnd * 0.45) + np.random.normal(0, 1.5)

            elif algo == "cubic":
                cwnd = cwnd + (0.4 * ((t % 8) - 3) ** 3) + 12
                cwnd = max(20, min(110, cwnd))
                if cwnd >= 105:  # Buffer penuh -> drop
                    cwnd *= 0.7  # Beta = 0.7 pada Cubic
                thr = min(bottleneck_bw, cwnd * 0.95 + np.random.normal(0, 1.5))
                rtt = base_rtt + (cwnd * 0.55) + np.random.normal(0, 2)  # rentan bufferbloat

            elif algo == "bbr":
                probe = 10 if (t % 8 == 0) else 0
                cwnd = 75 + probe + np.random.normal(0, 2)
                thr = min(bottleneck_bw, 94 + np.random.normal(0, 1.2))
                rtt = base_rtt + 4.0 + (probe * 0.5) + np.random.normal(0, 0.8)

            elif algo == "vegas":
                rtt_current = base_rtt + (cwnd * 0.25)
                cwnd = cwnd - 6 if rtt_current > base_rtt + 12 else cwnd + 6
                cwnd = max(25, cwnd)
                thr = min(bottleneck_bw, cwnd * 1.1 + np.random.normal(0, 1.5))
                rtt = rtt_current + np.random.normal(0, 1.0)

            else:
                raise ValueError(f"Algoritma tidak dikenal: {algo}")

            timestamps.append(t)
            throughputs.append(max(0.0, float(thr)))
            rtts.append(max(base_rtt, float(rtt)))
            cwnds.append(max(1.0, float(cwnd)))

            # Update GUI secara realtime (salinan list agar aman antar-thread)
            self.root.after(
                0, self.update_realtime_progress, t, duration, algo,
                list(timestamps), list(throughputs), list(rtts), list(cwnds),
            )

        self.save_and_analyze(algo, list(timestamps), list(throughputs), list(rtts), list(cwnds))

    # --------------------------------------------------------------- Real
    def run_real_iperf(self, algo, duration):
        """Menjalankan iperf3 asli (khusus Linux dengan iperf3 terinstal)."""
        server_ip = self.server_var.get().strip() or "127.0.0.1"
        self.root.after(0, lambda: self.status_label.config(
            text=f"Status: Menjalankan iperf3 ({algo}) ke {server_ip}..."))

        cmd = ["iperf3", "-c", server_ip, "-t", str(duration), "-C", algo, "-J"]

        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        except FileNotFoundError:
            self.root.after(0, lambda: messagebox.showerror(
                "iperf3 tidak ditemukan", "Install iperf3 terlebih dahulu:\n  sudo apt install iperf3"))
            return

        for t in range(1, duration + 1):
            if self._stop_requested or proc.poll() is not None:
                break
            time.sleep(1)
            self.root.after(0, lambda val=t: self.progress.config(value=val))

        stdout, stderr = proc.communicate()

        if proc.returncode != 0:
            msg = (stderr or "").strip() or f"iperf3 keluar dengan kode {proc.returncode}"
            self.root.after(0, lambda m=msg: messagebox.showerror(
                "Error Real Mode",
                f"Gagal mengambil data dari iperf3:\n\n{m}\n\n"
                "Pastikan: server iperf3 menyala (`iperf3 -s`), IP/port benar, "
                "dan algoritma didukung kernel (`sysctl net.ipv4.tcp_available_congestion_control`).\n"
                "Atau gunakan Mode Simulasi.",
            ))
            return

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as exc:
            self.root.after(0, lambda e=exc: messagebox.showerror(
                "Error Real Mode", f"Output iperf3 tidak bisa dibaca:\n{e}"))
            return

        timestamps, throughputs, rtts, cwnds = [], [], [], []
        for idx, interval in enumerate(data.get("intervals", []), 1):
            streams = interval.get("streams") or [{}]
            stream = streams[0]
            timestamps.append(idx)
            throughputs.append(stream.get("bits_per_second", 0) / 1e6)  # Mbps
            rtts.append(stream.get("rtt", 0) / 1000.0)  # mikrodetik -> ms
            cwnds.append(stream.get("snd_cwnd", 0) / 1024.0)  # byte -> KB

        if not throughputs:
            self.root.after(0, lambda: messagebox.showwarning(
                "Data kosong", "iperf3 tidak mengembalikan data interval. "
                "Coba tambah durasi atau periksa koneksi ke server."))
            return

        self.root.after(0, self.update_realtime_progress, duration, duration, algo,
                        timestamps, throughputs, rtts, cwnds)
        self.save_and_analyze(algo, timestamps, throughputs, rtts, cwnds)

    # ---------------------------------------------------------- Visualisasi
    def update_realtime_progress(self, current_t, total_t, algo, t_list, thr_list, rtt_list, cwnd_list):
        self.progress["value"] = current_t
        self.status_label.config(text=f"Status: Mengambil data [{algo.upper()}] ({current_t}/{total_t} s)")

        self.history_data[algo.upper()] = {
            "time": t_list,
            "thr": thr_list,
            "rtt": rtt_list,
            "cwnd": cwnd_list,
        }
        self.redraw_plots()

    def redraw_plots(self):
        for ax in (self.ax_thr, self.ax_rtt, self.ax_cwnd):
            ax.clear()
        self.setup_axes()

        for algo_name, data in self.history_data.items():
            c = COLORS.get(algo_name)
            self.ax_thr.plot(data["time"], data["thr"], marker=MARKERS["thr"], markersize=3,
                             label=algo_name, color=c, linewidth=2)
            self.ax_rtt.plot(data["time"], data["rtt"], marker=MARKERS["rtt"], markersize=3,
                             label=algo_name, color=c, linewidth=2)
            self.ax_cwnd.plot(data["time"], data["cwnd"], marker=MARKERS["cwnd"], markersize=3,
                              label=algo_name, color=c, linewidth=2)

        if self.history_data:
            self.ax_thr.legend(loc="lower right", fontsize=8)
            self.ax_rtt.legend(loc="upper right", fontsize=8)
            self.ax_cwnd.legend(loc="upper right", fontsize=8)

        self.canvas.draw()

    # ------------------------------------------------------------- Analisis
    def save_and_analyze(self, algo, timestamps, throughputs, rtts, cwnds):
        if not throughputs:
            return

        algo_key = algo.upper()
        thr_arr = np.array(throughputs, dtype=float)
        rtt_arr = np.array(rtts, dtype=float)

        avg_thr = float(np.mean(thr_arr))
        max_thr = float(np.max(thr_arr))
        std_thr = float(np.std(thr_arr))
        avg_rtt = float(np.mean(rtt_arr))
        min_rtt = float(np.min(rtt_arr))

        # Jain's Fairness Index dipakai sebagai indeks stabilitas alokasi bandwidth antar waktu
        denom = len(thr_arr) * float(np.sum(thr_arr ** 2))
        jfi = (float(np.sum(thr_arr)) ** 2) / denom if denom > 0 else 0.0

        # Power Metric = Throughput / Delay (semakin tinggi semakin efisien)
        power = avg_thr / avg_rtt if avg_rtt > 0 else 0.0

        conclusions = {
            "bbr": "BBR mencapai throughput tinggi dengan latensi sangat rendah karena "
                   "menghindari pengisian antrian berlebih (bufferbloat).",
            "cubic": "CUBIC sangat agresif meraih throughput tinggi, namun cenderung memenuhi "
                     "buffer sehingga RTT meningkat.",
            "reno": "Reno menunjukkan pola sawtooth (gigi gergaji) klasik, kurang optimal pada "
                    "jaringan berkecepatan tinggi.",
            "vegas": "Vegas berhasil menjaga RTT tetap stabil dan rendah, namun mengorbankan "
                     "maksimalisasi throughput.",
        }

        report = (
            f"=== ANALISIS ALGORITMA {algo_key} ===\n"
            f"• Avg Throughput  : {avg_thr:.2f} Mbps\n"
            f"• Peak Throughput : {max_thr:.2f} Mbps\n"
            f"• Fluktuasi (Std) : ±{std_thr:.2f} Mbps\n"
            f"• Avg Latency/RTT : {avg_rtt:.2f} ms (Min: {min_rtt:.1f} ms)\n"
            f"• Stability (JFI) : {jfi:.4f} (Ideal = 1.0)\n"
            f"• Efisiensi Power : {power:.2f} Mbps/ms\n\n"
            f"Kesimpulan Karakteristik:\n{conclusions.get(algo, '-')}"
        )

        self.analysis_cache[algo_key] = {
            "avg_thr": avg_thr, "max_thr": max_thr, "std_thr": std_thr,
            "avg_rtt": avg_rtt, "min_rtt": min_rtt, "jfi": jfi, "power": power,
        }

        def update_ui_analysis():
            for item in self.tree.get_children():
                if self.tree.item(item, "values")[0] == algo_key:
                    self.tree.delete(item)
            self.tree.insert("", tk.END, values=(algo_key, f"{avg_thr:.1f}", f"{avg_rtt:.1f}", f"{jfi:.3f}"))
            self._set_analysis_text(report)

        self.root.after(0, update_ui_analysis)

    # ---------------------------------------------------------------- Aksi
    def finish_benchmark(self):
        self.is_running = False
        self.btn_start.config(state="normal", bg="#4cd137", text="▶ Mulai Benchmark")
        if self._stop_requested:
            self.status_label.config(text="Status: Dihentikan oleh pengguna", foreground="#e84118")
        else:
            self.status_label.config(text="Status: Benchmark Selesai!", foreground="#718093")

    def clear_data(self):
        if self.is_running:
            return
        self.history_data.clear()
        self.analysis_cache.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.redraw_plots()
        self._set_analysis_text("Data telah di-reset.")
        self.progress["value"] = 0
        self.status_label.config(text="Status: Siap", foreground="#718093")

    def export_csv(self):
        if not self.history_data:
            messagebox.showwarning("Kosong", "Belum ada data benchmark untuk diekspor!")
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile="tcp_cc_benchmark.csv",
        )
        if not file_path:
            return

        try:
            with open(file_path, mode="w", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                writer.writerow(["Algorithm", "Time (s)", "Throughput (Mbps)", "RTT (ms)", "CWND (KB)"])
                for algo, data in self.history_data.items():
                    for i in range(len(data["time"])):
                        writer.writerow([
                            algo,
                            data["time"][i],
                            f"{data['thr'][i]:.2f}",
                            f"{data['rtt'][i]:.2f}",
                            f"{data['cwnd'][i]:.2f}",
                        ])
        except OSError as exc:
            messagebox.showerror("Gagal menyimpan", f"Tidak bisa menulis file:\n{exc}")
            return

        messagebox.showinfo("Berhasil", f"Data berhasil disimpan ke:\n{file_path}")

    def on_close(self):
        self._stop_requested = True
        self.root.after(150, self._destroy)

    def _destroy(self):
        # quit() dulu supaya mainloop benar-benar keluar (perilaku tkinter 3.13+)
        self.root.quit()
        self.root.destroy()


def main():
    root = tk.Tk()
    CongestionControlBenchmarkGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
