from __future__ import annotations

import csv
import io
import math
import os
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageGrab, ImageTk


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "03_处理数据"
FIG_DIR = ROOT / "04_图表"

CSV_FILES = [
    "measurements.csv",
    "distance_response.csv",
    "lateral_profile.csv",
    "uniformity_symmetry_repeatability.csv",
    "background_by_measurement.csv",
    "background_summary.csv",
    "forty_minute_stability.csv",
    "median_mean_comparison.csv",
    "center_net_spectra.csv",
    "led_median_spectra.csv",
    "shade_median_spectra.csv",
    "net_spectra.csv",
    "net_mean_spectra.csv",
]

SPECTRUM_FILES = {
    "LED、遮阴、净光谱同时显示": None,
    "LED中位光谱": "led_median_spectra.csv",
    "遮阴中位光谱": "shade_median_spectra.csv",
    "扣背景净光谱": "net_spectra.csv",
    "扣背景净光谱（均值）": "net_mean_spectra.csv",
    "中位数与均值净光谱同时显示": None,
    "中心平均净光谱": "center_net_spectra.csv",
}

COLORS = ["#2457A6", "#F07B2D", "#6B4FA1", "#2F8F46", "#C43C39", "#4D91D9"]


def resolve_csv_path(source: str | Path) -> Path:
    path = Path(source)
    return path if path.is_absolute() else DATA_DIR / path


def read_csv(source: str | Path) -> tuple[list[str], list[dict[str, str]]]:
    """Read common CSV/TSV encodings and delimiters without modifying the source."""
    path = resolve_csv_path(source)
    raw_bytes = path.read_bytes()
    encodings = ("utf-16",) if raw_bytes.startswith((b"\xff\xfe", b"\xfe\xff")) else ("utf-8-sig", "utf-8", "gb18030")
    last_error = None
    text = None
    for encoding in encodings:
        try:
            text = raw_bytes.decode(encoding)
            break
        except UnicodeError as exc:
            last_error = exc
    if text is None:
        raise ValueError(f"无法识别文件编码：{path}\n{last_error}")
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter)
    headers = [str(name).strip() for name in (reader.fieldnames or [])]
    rows = []
    for raw in reader:
        rows.append({str(key).strip(): "" if value is None else str(value).strip()
                     for key, value in raw.items() if key is not None})
    return headers, rows


def parse_number(value: str) -> float:
    text = str(value).strip().replace(",", "")
    if text.endswith("%"):
        return float(text[:-1])
    return float(text)


def numeric_key(value: str):
    try:
        return (0, parse_number(value))
    except (TypeError, ValueError):
        return (1, str(value).lower())


def save_canvas_png(canvas: tk.Canvas, default_name: str) -> None:
    path = filedialog.asksaveasfilename(
        title="保存当前图",
        defaultextension=".png",
        initialfile=default_name,
        filetypes=[("PNG图片", "*.png")],
    )
    if not path:
        return
    canvas.update_idletasks()
    x1 = canvas.winfo_rootx()
    y1 = canvas.winfo_rooty()
    x2 = x1 + canvas.winfo_width()
    y2 = y1 + canvas.winfo_height()
    ImageGrab.grab(bbox=(x1, y1, x2, y2)).save(path)


def draw_xy_series(canvas: tk.Canvas, series, x_label: str, y_label: str,
                   chart_type: str = "折线图") -> None:
    canvas.delete("all")
    valid = [(label, [(x, y) for x, y in points if math.isfinite(x) and math.isfinite(y)])
             for label, points in series]
    valid = [(label, points) for label, points in valid if points]
    if not valid:
        canvas.create_text(20, 20, anchor="nw", text="没有可绘制的数值。", fill="#666666")
        return
    width = max(canvas.winfo_width(), 700)
    height = max(canvas.winfo_height(), 460)
    left, right, top, bottom = 82, 30, 44, 64
    all_x = [x for _, points in valid for x, _ in points]
    all_y = [y for _, points in valid for _, y in points]
    xmin, xmax = min(all_x), max(all_x)
    ymin, ymax = min(all_y), max(all_y)
    if xmin == xmax:
        xmin, xmax = xmin - 0.5, xmax + 0.5
    if ymin > 0:
        ymin = 0.0
    if ymin == ymax:
        ymin, ymax = ymin - 0.5, ymax + 0.5

    def sx(value):
        return left + (value - xmin) / (xmax - xmin) * (width - left - right)

    def sy(value):
        return top + (ymax - value) / (ymax - ymin) * (height - top - bottom)

    for tick in range(6):
        value = ymin + (ymax - ymin) * tick / 5
        py = sy(value)
        canvas.create_line(left, py, width - right, py, fill="#E3E3E3")
        fmt = f"{value:,.0f}" if max(abs(ymin), abs(ymax)) >= 10 else f"{value:.3g}"
        canvas.create_text(left - 8, py, anchor="e", text=fmt, fill="#555555")
    for tick in range(7):
        value = xmin + (xmax - xmin) * tick / 6
        px = sx(value)
        canvas.create_line(px, height - bottom, px, height - bottom + 5, fill="#333333")
        canvas.create_text(px, height - bottom + 10, anchor="n", text=f"{value:.3g}", fill="#555555")
    canvas.create_line(left, top, left, height - bottom, fill="#333333")
    canvas.create_line(left, height - bottom, width - right, height - bottom, fill="#333333")
    canvas.create_text(width / 2, height - 18, text=x_label, font=("Microsoft YaHei UI", 10))
    canvas.create_text(18, height / 2, text=y_label, angle=90, font=("Microsoft YaHei UI", 10))

    for index, (label, points) in enumerate(valid):
        color = COLORS[index % len(COLORS)]
        coords = [(sx(x), sy(y)) for x, y in points]
        if chart_type == "散点图":
            for px, py in coords:
                canvas.create_oval(px - 3, py - 3, px + 3, py + 3, fill=color, outline="")
        elif chart_type == "柱状图":
            bar_width = max(3, min(22, (width - left - right) / max(len(coords), 1) * 0.55))
            zero_y = sy(0 if ymin <= 0 <= ymax else ymin)
            for px, py in coords:
                canvas.create_rectangle(px - bar_width / 2, py, px + bar_width / 2, zero_y,
                                        fill=color, outline="")
        else:
            flattened = [coordinate for point in coords for coordinate in point]
            if len(flattened) >= 4:
                canvas.create_line(*flattened, fill=color, width=2)
            for px, py in coords:
                canvas.create_oval(px - 2, py - 2, px + 2, py + 2, fill=color, outline="")
        if index < 12:
            lx, ly = left + 14, top + 12 + index * 21
            canvas.create_line(lx, ly, lx + 26, ly, fill=color, width=3)
            canvas.create_text(lx + 34, ly, anchor="w", text=label, fill="#222222")


class CsvTable(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=10)
        self.headers: list[str] = []
        self.rows: list[dict[str, str]] = []
        self.filtered: list[dict[str, str]] = []
        self.sort_reverse: dict[str, bool] = {}
        self.current_path = DATA_DIR / "measurements.csv"

        controls = ttk.Frame(self)
        controls.pack(fill="x", pady=(0, 8))
        ttk.Label(controls, text="数据表：").pack(side="left")
        self.file_var = tk.StringVar(value="measurements.csv")
        file_box = ttk.Combobox(controls, textvariable=self.file_var, values=CSV_FILES,
                                width=38, state="readonly")
        file_box.pack(side="left", padx=(0, 12))
        file_box.bind("<<ComboboxSelected>>", lambda _e: self.load())
        ttk.Button(controls, text="打开任意CSV/TSV", command=self.choose_file).pack(side="left", padx=(0, 12))

        ttk.Label(controls, text="搜索：").pack(side="left")
        self.search_var = tk.StringVar()
        search = ttk.Entry(controls, textvariable=self.search_var, width=24)
        search.pack(side="left", padx=(0, 6))
        search.bind("<KeyRelease>", lambda _e: self.apply_filter())
        ttk.Button(controls, text="清除", command=self.clear_search).pack(side="left")
        ttk.Button(controls, text="用默认程序打开CSV", command=self.open_csv).pack(side="right")

        tree_area = ttk.Frame(self)
        tree_area.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_area, show="headings")
        ybar = ttk.Scrollbar(tree_area, orient="vertical", command=self.tree.yview)
        xbar = ttk.Scrollbar(tree_area, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        tree_area.rowconfigure(0, weight=1)
        tree_area.columnconfigure(0, weight=1)
        self.tree.bind("<Control-c>", lambda _e: self.copy_selected())

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", pady=(7, 0))
        self.status = ttk.Label(bottom, text="")
        self.status.pack(side="left")
        ttk.Button(bottom, text="复制选中行", command=self.copy_selected).pack(side="right")
        self.load()

    def choose_file(self):
        path = filedialog.askopenfilename(
            title="选择CSV或TSV文件",
            filetypes=[("CSV和TSV", "*.csv *.tsv *.txt"), ("CSV", "*.csv"),
                       ("TSV", "*.tsv"), ("所有文件", "*.*")],
        )
        if path:
            self.current_path = Path(path)
            self.file_var.set(str(self.current_path))
            self.load(self.current_path)

    def load(self, source=None):
        try:
            if source is None:
                value = self.file_var.get()
                self.current_path = resolve_csv_path(value)
            else:
                self.current_path = resolve_csv_path(source)
            self.headers, self.rows = read_csv(self.current_path)
        except Exception as exc:
            messagebox.showerror("读取失败", str(exc))
            return
        self.tree.delete(*self.tree.get_children())
        self.tree["columns"] = self.headers
        for header in self.headers:
            width = max(95, min(230, 12 + len(header) * 9))
            self.tree.heading(header, text=header,
                              command=lambda col=header: self.sort_by(col))
            self.tree.column(header, width=width, minwidth=70, anchor="center", stretch=False)
        self.apply_filter()

    def apply_filter(self):
        needle = self.search_var.get().strip().lower()
        if needle:
            self.filtered = [row for row in self.rows
                             if needle in "  ".join(row.get(h, "") for h in self.headers).lower()]
        else:
            self.filtered = list(self.rows)
        self.render_rows()

    def render_rows(self):
        self.tree.delete(*self.tree.get_children())
        for row in self.filtered:
            self.tree.insert("", "end", values=[row.get(h, "") for h in self.headers])
        self.status.configure(text=f"{self.current_path.name}：显示 {len(self.filtered)} / {len(self.rows)} 行，{len(self.headers)} 列｜{self.current_path}")

    def sort_by(self, column: str):
        reverse = self.sort_reverse.get(column, False)
        self.filtered.sort(key=lambda row: numeric_key(row.get(column, "")), reverse=reverse)
        self.sort_reverse[column] = not reverse
        self.render_rows()

    def clear_search(self):
        self.search_var.set("")
        self.apply_filter()

    def open_csv(self):
        os.startfile(self.current_path)

    def copy_selected(self):
        selected = self.tree.selection()
        if not selected:
            return
        lines = ["\t".join(self.headers)]
        lines.extend("\t".join(map(str, self.tree.item(item, "values"))) for item in selected)
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))
        self.status.configure(text=f"已复制 {len(selected)} 行，可直接粘贴到Excel或Word")


class SpectrumView(ttk.Frame):
    DISPLAY_MODES = ["真实DN（默认）", "峰值归一化（每条峰值=1）", "相对首条峰值（首条峰值=100%）"]

    def __init__(self, master):
        super().__init__(master, padding=10)
        _, self.measurements = read_csv("measurements.csv")
        self.distances = list(dict.fromkeys(row["distance_m"] for row in self.measurements))
        self.series: list[tuple[str, list[float], list[float]]] = []

        controls = ttk.Frame(self)
        controls.pack(fill="x", pady=(0, 8))
        ttk.Label(controls, text="内容：").grid(row=0, column=0, sticky="w")
        self.kind_var = tk.StringVar(value="扣背景净光谱")
        ttk.Combobox(controls, textvariable=self.kind_var, values=list(SPECTRUM_FILES),
                     width=26, state="readonly").grid(row=0, column=1, padx=(4, 12))
        ttk.Label(controls, text="距离：").grid(row=0, column=2)
        self.distance_var = tk.StringVar(value="3.016")
        distance_box = ttk.Combobox(controls, textvariable=self.distance_var,
                                    values=self.distances, width=9, state="readonly")
        distance_box.grid(row=0, column=3, padx=(4, 12))
        distance_box.bind("<<ComboboxSelected>>", lambda _e: self.update_positions())
        ttk.Label(controls, text="位置：").grid(row=0, column=4)
        self.position_var = tk.StringVar(value="中间1")
        self.position_box = ttk.Combobox(controls, textvariable=self.position_var,
                                         width=11, state="readonly")
        self.position_box.grid(row=0, column=5, padx=(4, 12))
        ttk.Button(controls, text="替换显示", command=lambda: self.load_selection(False)).grid(row=0, column=6)
        ttk.Button(controls, text="添加对比", command=lambda: self.load_selection(True)).grid(row=0, column=7, padx=(6, 0))
        ttk.Button(controls, text="清空", command=self.clear).grid(row=0, column=8, padx=(6, 0))

        ttk.Label(controls, text="纵轴：").grid(row=1, column=0, sticky="w", pady=(7, 0))
        self.display_var = tk.StringVar(value=self.DISPLAY_MODES[0])
        display_box = ttk.Combobox(controls, textvariable=self.display_var,
                                   values=self.DISPLAY_MODES, width=30, state="readonly")
        display_box.grid(row=1, column=1, padx=(4, 12), pady=(7, 0))
        display_box.bind("<<ComboboxSelected>>", lambda _e: self.draw())
        ttk.Label(controls, text="波段：").grid(row=1, column=2, pady=(7, 0))
        self.band_var = tk.StringVar(value="400–720 nm")
        band_box = ttk.Combobox(controls, textvariable=self.band_var,
                                values=["400–720 nm", "全部288通道", "自定义"],
                                width=14, state="readonly")
        band_box.grid(row=1, column=3, padx=(4, 12), pady=(7, 0))
        band_box.bind("<<ComboboxSelected>>", lambda _e: self.draw())
        ttk.Label(controls, text="自定义起止nm：").grid(row=1, column=4, pady=(7, 0))
        custom = ttk.Frame(controls)
        custom.grid(row=1, column=5, padx=(4, 12), pady=(7, 0))
        self.band_start = tk.StringVar(value="400")
        self.band_end = tk.StringVar(value="720")
        ttk.Entry(custom, textvariable=self.band_start, width=7).pack(side="left")
        ttk.Label(custom, text=" 至 ").pack(side="left")
        ttk.Entry(custom, textvariable=self.band_end, width=7).pack(side="left")
        ttk.Button(controls, text="应用波段", command=self.draw).grid(row=1, column=6, pady=(7, 0))
        ttk.Button(controls, text="导出当前图PNG", command=lambda: save_canvas_png(self.canvas, "光谱图.png")).grid(row=1, column=7, padx=(6, 0), pady=(7, 0))
        ttk.Button(controls, text="导出曲线CSV", command=self.export_series).grid(row=1, column=8, padx=(6, 0), pady=(7, 0))

        self.canvas = tk.Canvas(self, background="white", highlightthickness=1,
                                highlightbackground="#BBBBBB")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self.draw())
        self.status = ttk.Label(self, text="")
        self.status.pack(fill="x", pady=(7, 0))
        self.update_positions()
        self.load_selection(False)

    def update_positions(self):
        distance = self.distance_var.get()
        positions = [row["position"] for row in self.measurements if row["distance_m"] == distance]
        self.position_box["values"] = positions
        if self.position_var.get() not in positions:
            self.position_var.set(positions[0] if positions else "")

    def selected_measurement(self):
        distance, position = self.distance_var.get(), self.position_var.get()
        return next((row for row in self.measurements
                     if row["distance_m"] == distance and row["position"] == position), None)

    @staticmethod
    def measurement_column(row: dict[str, str]) -> str:
        return f"M{int(row['id']):02d}_{row['distance_m']}m_{row['position']}"

    def spectrum(self, filename: str, column: str) -> tuple[list[float], list[float]]:
        headers, rows = read_csv(filename)
        if column not in headers:
            raise KeyError(f"{filename}中没有列：{column}")
        x, y = [], []
        for row in rows:
            try:
                x.append(float(row["wavelength_nm"]))
                y.append(float(row[column]))
            except (ValueError, KeyError):
                continue
        return x, y

    def load_selection(self, append: bool):
        try:
            kind = self.kind_var.get()
            distance = self.distance_var.get()
            new_series = []
            if kind == "中心平均净光谱":
                x, y = self.spectrum("center_net_spectra.csv", f"{distance}m")
                new_series.append((f"{distance} m 中心平均净光谱", x, y))
            else:
                measurement = self.selected_measurement()
                if not measurement:
                    raise ValueError("未找到对应测量")
                column = self.measurement_column(measurement)
                label = f"{distance} m {measurement['position']}"
                if kind == "LED、遮阴、净光谱同时显示":
                    specs = [
                        ("LED中位", "led_median_spectra.csv"),
                        ("遮阴中位", "shade_median_spectra.csv"),
                        ("净光谱", "net_spectra.csv"),
                    ]
                elif kind == "中位数与均值净光谱同时显示":
                    specs = [
                        ("中位数净光谱", "net_spectra.csv"),
                        ("均值净光谱", "net_mean_spectra.csv"),
                    ]
                else:
                    specs = [(kind, SPECTRUM_FILES[kind])]
                for series_name, filename in specs:
                    x, y = self.spectrum(filename, column)
                    new_series.append((f"{label} {series_name}", x, y))
            if append:
                existing = {label for label, _, _ in self.series}
                self.series.extend(item for item in new_series if item[0] not in existing)
            else:
                self.series = new_series
            self.draw()
            self.status.configure(text=f"当前 {len(self.series)} 条曲线；原始数据只读，默认纵轴为真实DN。")
        except Exception as exc:
            messagebox.showerror("无法显示", str(exc))

    def wavelength_range(self):
        if self.band_var.get() == "全部288通道":
            return -math.inf, math.inf
        if self.band_var.get() == "400–720 nm":
            return 400.0, 720.0
        start, end = float(self.band_start.get()), float(self.band_end.get())
        return min(start, end), max(start, end)

    def displayed_series(self):
        start, end = self.wavelength_range()
        mode = self.display_var.get()
        first_peak = None
        if self.series:
            values = [y for _, xs, ys in self.series for x, y in zip(xs, ys)
                      if start <= x <= end and math.isfinite(y)]
            first_values = [y for x, y in zip(self.series[0][1], self.series[0][2])
                            if start <= x <= end and math.isfinite(y)]
            first_peak = max(first_values) if first_values else None
        output = []
        for label, xs, ys in self.series:
            points = [(x, y) for x, y in zip(xs, ys)
                      if start <= x <= end and math.isfinite(x) and math.isfinite(y)]
            if mode == "峰值归一化（每条峰值=1）" and points:
                peak = max(y for _, y in points)
                points = [(x, y / peak if peak else math.nan) for x, y in points]
            elif mode == "相对首条峰值（首条峰值=100%）" and first_peak:
                points = [(x, y / first_peak * 100) for x, y in points]
            output.append((label, points))
        return output

    def draw(self):
        try:
            mode = self.display_var.get()
            y_label = "DN" if mode == self.DISPLAY_MODES[0] else ("归一化值" if "峰值=1" in mode else "相对首条峰值 (%)")
            draw_xy_series(self.canvas, self.displayed_series(), "波长 (nm)", y_label, "折线图")
        except ValueError:
            self.status.configure(text="自定义波段必须输入数字。")

    def clear(self):
        self.series = []
        self.draw()
        self.status.configure(text="已清空")

    def export_series(self):
        shown = self.displayed_series()
        if not shown:
            return
        path = filedialog.asksaveasfilename(title="导出当前曲线数据", defaultextension=".csv",
                                            initialfile="当前显示曲线.csv",
                                            filetypes=[("CSV文件", "*.csv")])
        if not path:
            return
        x_values = shown[0][1]
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["wavelength_nm"] + [label for label, _ in shown])
            for index, (x, _) in enumerate(x_values):
                row = [x]
                for _, points in shown:
                    row.append(points[index][1] if index < len(points) and points[index][0] == x else "")
                writer.writerow(row)
        self.status.configure(text=f"已导出：{path}")


class CustomPlotView(ttk.Frame):
    MODES = ["原始数值", "每条除以最大值", "每条首点设为100%"]

    def __init__(self, master):
        super().__init__(master, padding=10)
        self.headers = []
        self.rows = []
        self.current_series = []
        self.current_path = DATA_DIR / "distance_response.csv"

        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="CSV：").grid(row=0, column=0, sticky="w")
        self.file_var = tk.StringVar(value="distance_response.csv")
        file_box = ttk.Combobox(top, textvariable=self.file_var, values=CSV_FILES,
                                width=36, state="readonly")
        file_box.grid(row=0, column=1, padx=(4, 12))
        file_box.bind("<<ComboboxSelected>>", lambda _e: self.load_file())
        ttk.Button(top, text="打开任意CSV/TSV", command=self.choose_file).grid(row=0, column=2, padx=(0, 18))
        ttk.Label(top, text="横轴X：").grid(row=0, column=3)
        self.x_var = tk.StringVar()
        self.x_box = ttk.Combobox(top, textvariable=self.x_var, width=28, state="readonly")
        self.x_box.grid(row=0, column=4, padx=(4, 12))
        ttk.Label(top, text="图形：").grid(row=1, column=0, sticky="w", pady=(7, 0))
        self.chart_var = tk.StringVar(value="折线图")
        chart_box = ttk.Combobox(top, textvariable=self.chart_var,
                                 values=["折线图", "散点图", "柱状图"], width=10, state="readonly")
        chart_box.grid(row=1, column=1, sticky="w", padx=(4, 12), pady=(7, 0))
        chart_box.bind("<<ComboboxSelected>>", lambda _e: self.draw())
        ttk.Label(top, text="数值处理：").grid(row=1, column=2, pady=(7, 0))
        self.mode_var = tk.StringVar(value=self.MODES[0])
        mode_box = ttk.Combobox(top, textvariable=self.mode_var, values=self.MODES,
                                width=19, state="readonly")
        mode_box.grid(row=1, column=3, sticky="w", padx=(4, 12), pady=(7, 0))
        mode_box.bind("<<ComboboxSelected>>", lambda _e: self.draw())

        ttk.Label(top, text="筛选列：").grid(row=2, column=0, sticky="w", pady=(7, 0))
        self.filter_col_var = tk.StringVar(value="（不筛选）")
        self.filter_box = ttk.Combobox(top, textvariable=self.filter_col_var,
                                       width=36, state="readonly")
        self.filter_box.grid(row=2, column=1, padx=(4, 12), pady=(7, 0))
        ttk.Label(top, text="包含文本：").grid(row=2, column=2, pady=(7, 0))
        self.filter_value_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.filter_value_var, width=30).grid(row=2, column=3, padx=(4, 12), pady=(7, 0))
        ttk.Button(top, text="绘图", command=self.draw).grid(row=3, column=0, sticky="w", pady=(7, 0))
        ttk.Button(top, text="导出当前图PNG",
                   command=lambda: save_canvas_png(self.canvas, "自定义图.png")).grid(row=3, column=1, sticky="w", padx=(4, 0), pady=(7, 0))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        chooser = ttk.LabelFrame(body, text="纵轴Y（可多选，Ctrl或Shift选择）", padding=6)
        chooser.pack(side="left", fill="y", padx=(0, 8))
        self.y_list = tk.Listbox(chooser, selectmode="extended", exportselection=False, width=36)
        ybar = ttk.Scrollbar(chooser, orient="vertical", command=self.y_list.yview)
        self.y_list.configure(yscrollcommand=ybar.set)
        self.y_list.pack(side="left", fill="y")
        ybar.pack(side="right", fill="y")
        self.y_list.bind("<<ListboxSelect>>", lambda _e: self.draw())

        self.canvas = tk.Canvas(body, background="white", highlightthickness=1,
                                highlightbackground="#BBBBBB")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self.draw())
        self.status = ttk.Label(self, text="")
        self.status.pack(fill="x", pady=(7, 0))
        self.load_file()

    def choose_file(self):
        path = filedialog.askopenfilename(
            title="选择要绘图的CSV或TSV文件",
            filetypes=[("CSV和TSV", "*.csv *.tsv *.txt"), ("CSV", "*.csv"),
                       ("TSV", "*.tsv"), ("所有文件", "*.*")],
        )
        if path:
            self.current_path = Path(path)
            self.file_var.set(str(self.current_path))
            self.load_file(self.current_path)

    def load_file(self, source=None):
        try:
            if source is None:
                self.current_path = resolve_csv_path(self.file_var.get())
            else:
                self.current_path = resolve_csv_path(source)
            self.headers, self.rows = read_csv(self.current_path)
            numeric = []
            for header in self.headers:
                sample = [row.get(header, "") for row in self.rows[:30] if row.get(header, "") != ""]
                if sample and sum(1 for value in sample if numeric_key(value)[0] == 0) >= max(1, len(sample) * 0.8):
                    numeric.append(header)
            if not numeric:
                raise ValueError("这个文件没有识别到可绘图的数值列，但仍可在CSV数据表中查看。")
            self.x_box["values"] = ["（行号）"] + numeric
            preferred = "wavelength_nm" if "wavelength_nm" in numeric else ("distance_m" if "distance_m" in numeric else "（行号）")
            self.x_var.set(preferred)
            self.filter_box["values"] = ["（不筛选）"] + self.headers
            self.filter_col_var.set("（不筛选）")
            self.y_list.delete(0, "end")
            for header in numeric:
                if header != preferred:
                    self.y_list.insert("end", header)
            if self.y_list.size():
                self.y_list.selection_set(0, min(1, self.y_list.size() - 1))
            self.draw()
        except Exception as exc:
            messagebox.showerror("读取失败", str(exc))

    def filtered_rows(self):
        column = self.filter_col_var.get()
        needle = self.filter_value_var.get().strip().lower()
        if column == "（不筛选）" or not needle:
            return self.rows
        return [row for row in self.rows if needle in row.get(column, "").lower()]

    def draw(self):
        x_column = self.x_var.get()
        selected = [self.y_list.get(index) for index in self.y_list.curselection()]
        if not x_column or not selected:
            self.canvas.delete("all")
            self.canvas.create_text(20, 20, anchor="nw", text="请选择横轴和至少一个纵轴。", fill="#666666")
            return
        rows = self.filtered_rows()
        series = []
        for y_column in selected:
            points = []
            for row_index, row in enumerate(rows, start=1):
                try:
                    x_value = float(row_index) if x_column == "（行号）" else parse_number(row[x_column])
                    points.append((x_value, parse_number(row[y_column])))
                except (KeyError, ValueError):
                    continue
            points.sort(key=lambda pair: pair[0])
            if self.mode_var.get() == "每条除以最大值" and points:
                peak = max(y for _, y in points)
                points = [(x, y / peak if peak else math.nan) for x, y in points]
            elif self.mode_var.get() == "每条首点设为100%" and points:
                first = points[0][1]
                points = [(x, y / first * 100 if first else math.nan) for x, y in points]
            series.append((y_column, points))
        self.current_series = series
        y_label = selected[0] if len(selected) == 1 else "数值"
        if self.mode_var.get() == "每条除以最大值":
            y_label = "归一化值"
        elif self.mode_var.get() == "每条首点设为100%":
            y_label = "相对首点 (%)"
        draw_xy_series(self.canvas, series, x_column, y_label, self.chart_var.get())
        self.status.configure(text=f"{self.current_path.name}：使用 {len(rows)} 行，绘制 {len(selected)} 个纵轴字段。原始文件未修改。")


class FigureView(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=10)
        figures = sorted(path.name for path in FIG_DIR.glob("*.png"))
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text="已有分析图：").pack(side="left")
        self.figure_var = tk.StringVar(value=figures[0] if figures else "")
        box = ttk.Combobox(bar, textvariable=self.figure_var, values=figures,
                           width=42, state="readonly")
        box.pack(side="left", padx=(4, 8))
        box.bind("<<ComboboxSelected>>", lambda _e: self.show())
        ttk.Button(bar, text="用默认程序打开", command=self.open_external).pack(side="left")
        self.label = ttk.Label(self, anchor="center")
        self.label.pack(fill="both", expand=True)
        self.label.bind("<Configure>", lambda _e: self.show())
        self.photo = None
        self.after(100, self.show)

    def show(self):
        name = self.figure_var.get()
        if not name:
            return
        path = FIG_DIR / name
        try:
            image = Image.open(path).convert("RGB")
            max_w = max(self.label.winfo_width() - 20, 600)
            max_h = max(self.label.winfo_height() - 20, 400)
            image.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
            self.photo = ImageTk.PhotoImage(image)
            self.label.configure(image=self.photo)
        except Exception as exc:
            self.label.configure(text=str(exc), image="")

    def open_external(self):
        if self.figure_var.get():
            os.startfile(FIG_DIR / self.figure_var.get())


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("通用CSV数据查看器｜LED光源实验功能已内置")
        width = min(1280, max(940, self.winfo_screenwidth() - 80))
        height = min(820, max(620, self.winfo_screenheight() - 120))
        self.geometry(f"{width}x{height}+20+20")
        self.minsize(940, 620)
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Treeview", rowheight=25, font=("Microsoft YaHei UI", 9))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"))
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)
        notebook.add(CsvTable(notebook), text="CSV数据表")
        notebook.add(SpectrumView(notebook), text="光谱选择与对比")
        notebook.add(CustomPlotView(notebook), text="自定义绘图")
        notebook.add(FigureView(notebook), text="已有分析图")


if __name__ == "__main__":
    App().mainloop()
