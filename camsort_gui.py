# camsort V3 GUI — настройка конфига и запуск сортировки.
# Автор: Симоненко К.В. 2026
# Стандартная библиотека Python (tkinter), без внешних зависимостей.

import os
import sys
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime

import camsort

APP_NAME = "camsort"
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.txt")
DAY_TYPE_LABELS = {
    "all": "Все дни",
    "weekdays": "Будни",
    "weekends": "Выходные"
}
DAY_TYPE_BY_LABEL = {v: k for k, v in DAY_TYPE_LABELS.items()}


# ---------- запись/чтение конфига ----------

def default_config():
    # Значения по умолчанию (как в config_example.txt)
    return {
        "src_dir": "",
        "dst_dir": "",
        "filename_regex": r"^(?:.*?)_(?P<date>\d{8})(?P<time>\d{6})_\d{14}_\d+\.mp4$",
        "date_format": "%Y%m%d",
        "time_format": "%H%M%S",
        "intervals": [],
        "whitelist": [],
        "blacklist": [],
        "day_type": "all",
        "overwrite": False,
    }


def config_to_text(cfg):
    # Формирует текст INI-конфига с комментариями
    def join(lst):
        return ", ".join(lst) if lst else ""

    return f"""[settings]

; Входной каталог с записями
src_dir = {cfg['src_dir']}

; Выходной каталог, куда раскладывать по папкам ГГГГ-ММ-ДД
dst_dir = {cfg['dst_dir']}

; Regex с группами date и time. Не менять, если формат имён не менялся.
filename_regex = {cfg['filename_regex']}

; Форматы даты и времени из имени файла. Не менять, если формат имён не менялся.
date_format = {cfg['date_format']}
time_format = {cfg['time_format']}

; Интервалы через запятую, формат ЧЧ:ММ-ЧЧ:ММ. Границы включительно.
; Пусто — без фильтра по времени (копируется любое время).
intervals = {join(cfg['intervals'])}

; Белый список: даты через запятую, ГГГГ-ММ-ДД. Пусто — берутся все дни.
; Поддерживаются диапазоны: 2026-10-12..2026-10-16
whitelist = {join(cfg['whitelist'])}

; Чёрный список: даты через запятую, ГГГГ-ММ-ДД. Пусто — ничего не исключается.
; Поддерживаются диапазоны: 2026-10-12..2026-10-16
blacklist = {join(cfg['blacklist'])}

; Тип дня: all | weekdays | weekends. Применяется до белого/чёрного списков.
day_type = {cfg['day_type']}

; Перезаписывать существующие файлы: true | false
overwrite = {'true' if cfg['overwrite'] else 'false'}
"""


def save_config(cfg):
    # Создаёт папку в %APPDATA% и пишет конфиг
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(config_to_text(cfg))


def load_config_file():
    # Читает конфиг, если он есть; иначе возвращает значения по умолчанию
    if not os.path.isfile(CONFIG_PATH):
        return default_config()
    try:
        parsed = camsort.load_config(CONFIG_PATH)
    except (SystemExit, ValueError):
        return default_config()
    return {
        "src_dir": parsed["src_dir"],
        "dst_dir": parsed["dst_dir"],
        "filename_regex": parsed["filename_regex"],
        "date_format": parsed["date_format"],
        "time_format": parsed["time_format"],
        "intervals": [f"{a}-{b}" for a, b in parsed["intervals"]],
        "whitelist": parsed["whitelist"],
        "blacklist": parsed["blacklist"],
        "day_type": parsed["day_type"],
        "overwrite": parsed["overwrite"],
    }


# ---------- календарь ----------

class CalendarDialog(tk.Toplevel):
    # Календарь на tkinter: одиночная дата или диапазон.
    # Режим range_mode=False: клик по дню -> подсветка, ОК возвращает дату.
    # Режим range_mode=True: первый клик — начало, второй — конец,
    # между ними подсветка, третий клик сбрасывает и начинает заново.
    def __init__(self, parent, title="Выбор даты", range_mode=False):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result = None
        self.range_mode = range_mode
        self.start = None
        self.end = None

        today = datetime.now()
        self.year = today.year
        self.month = today.month

        # Заголовок с навигацией
        self.header = tk.Frame(self)
        self.header.pack(pady=4)
        tk.Button(self.header, text="<", width=3, command=self.prev_month).pack(side="left")
        self.label = tk.Label(self.header, width=14, font=("Segoe UI", 10, "bold"))
        self.label.pack(side="left")
        tk.Button(self.header, text=">", width=3, command=self.next_month).pack(side="left")

        # Сетка дней
        self.grid_frame = tk.Frame(self)
        self.grid_frame.pack(padx=6, pady=6)
        self.day_buttons = {}

        # Подсказка
        hint = "Выберите начало и конец диапазона" if range_mode else "Выберите дату"
        tk.Label(self, text=hint, fg="gray").pack(pady=(0, 4))

        # Кнопки
        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=(0, 6))
        tk.Button(btn_frame, text="ОК", width=8, command=self.ok).pack(side="left", padx=4)
        tk.Button(btn_frame, text="Отмена", width=8, command=self.destroy).pack(side="left", padx=4)

        self.draw_month()

    def prev_month(self):
        self.month -= 1
        if self.month == 0:
            self.month = 12
            self.year -= 1
        self.draw_month()

    def next_month(self):
        self.month += 1
        if self.month == 13:
            self.month = 1
            self.year += 1
        self.draw_month()

    def draw_month(self):
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.day_buttons = {}
        self.label.config(text=f"{self.month:02d}.{self.year}")

        for i, d in enumerate(["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]):
            tk.Label(self.grid_frame, text=d, width=4).grid(row=0, column=i)

        first = datetime(self.year, self.month, 1)
        start_col = first.weekday()
        if self.month == 12:
            days_in_month = 31
        else:
            days_in_month = (datetime(self.year, self.month + 1, 1) - first).days

        row, col = 1, start_col
        for day in range(1, days_in_month + 1):
            btn = tk.Button(self.grid_frame, text=str(day), width=4,
                            command=lambda d=day: self.click_day(d))
            btn.grid(row=row, column=col)
            self.day_buttons[day] = btn
            col += 1
            if col == 7:
                col = 0
                row += 1

        self.refresh_highlight()

    def click_day(self, day):
        d = datetime(self.year, self.month, day).date()
        if not self.range_mode:
            self.start = d
            self.end = d
            self.refresh_highlight()
            return
        # режим диапазона
        if self.start is None or (self.start is not None and self.end is not None):
            # первый клик или третий (сброс)
            self.start = d
            self.end = None
        else:
            # второй клик — конец, нормализуем порядок
            if d < self.start:
                self.start, self.end = d, self.start
            else:
                self.end = d
        self.refresh_highlight()

    def refresh_highlight(self):
        # Снимаем подсветку и заново красим выбранные дни
        for btn in self.day_buttons.values():
            btn.configure(bg="SystemButtonFace", fg="black")
        if self.start is None:
            return
        if self.end is None:
            self._paint(self.start, "yellow")
            return
        cur = self.start
        while cur <= self.end:
            if cur.year == self.year and cur.month == self.month:
                self._paint(cur, "#a8d8ff")
            cur = cur.fromordinal(cur.toordinal() + 1)

    def _paint(self, d, color):
        btn = self.day_buttons.get(d.day)
        if btn is not None and d.year == self.year and d.month == self.month:
            btn.configure(bg=color)

    def ok(self):
        if self.start is None:
            messagebox.showwarning("Не выбрано", "Выберите дату", parent=self)
            return
        if self.range_mode and self.end is None:
            # выбран только один день — считаем его и началом, и концом
            self.end = self.start
        if self.range_mode:
            self.result = f"{self.start.isoformat()}..{self.end.isoformat()}"
        else:
            self.result = self.start.isoformat()
        self.destroy()


# ---------- основное окно ----------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("camsort")
        self.geometry("820x760")
        self.cfg = load_config_file()
        self.log_queue = queue.Queue()
        self.worker = None
        self.interval_rows = []  # список кортежей (Frame, StringVar h1, m1, h2, m2)
        self._build_ui()
        self._fill_ui()
        self.after(100, self._poll_queue)

    def _build_ui(self):
        pad = {"padx": 6, "pady": 3}

        # --- Пути ---
        frame_paths = tk.LabelFrame(self, text="Каталоги")
        frame_paths.pack(fill="x", **pad)

        tk.Label(frame_paths, text="Входной:").grid(row=0, column=0, sticky="w")
        self.var_src = tk.StringVar()
        tk.Entry(frame_paths, textvariable=self.var_src, width=60).grid(row=0, column=1, sticky="we")
        tk.Button(frame_paths, text="Обзор…", command=lambda: self._pick_dir(self.var_src)).grid(row=0, column=2)

        tk.Label(frame_paths, text="Выходной:").grid(row=1, column=0, sticky="w")
        self.var_dst = tk.StringVar()
        tk.Entry(frame_paths, textvariable=self.var_dst, width=60).grid(row=1, column=1, sticky="we")
        tk.Button(frame_paths, text="Обзор…", command=lambda: self._pick_dir(self.var_dst)).grid(row=1, column=2)
        frame_paths.columnconfigure(1, weight=1)

        # --- Интервалы (ячейки) ---
        frame_int = tk.LabelFrame(self, text="Временные интервалы (пусто — любое время)")
        frame_int.pack(fill="x", **pad)

        self.intervals_container = tk.Frame(frame_int)
        self.intervals_container.pack(fill="x", padx=4, pady=4)

        tk.Button(frame_int, text="Добавить интервал", command=self._add_interval_row).pack(anchor="w", padx=4, pady=(0, 4))

        # --- Тип дня ---
        frame_misc = tk.Frame(self)
        frame_misc.pack(fill="x", **pad)

        tk.Label(frame_misc, text="Тип дня:").pack(side="left")
        self.var_daytype_label = tk.StringVar(value=DAY_TYPE_LABELS["all"])
        ttk.Combobox(frame_misc, textvariable=self.var_daytype_label,
                     values=list(DAY_TYPE_LABELS.values()), state="readonly", width=14).pack(side="left", padx=6)

        # --- Списки дат ---
        frame_dates = tk.Frame(self)
        frame_dates.pack(fill="both", expand=True, **pad)

        # whitelist
        fw = tk.LabelFrame(frame_dates, text="Белый список (пусто — все дни)")
        fw.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.list_white = tk.Listbox(fw, height=6)
        self.list_white.pack(fill="both", expand=True, padx=4, pady=4)
        bw = tk.Frame(fw)
        bw.pack(fill="x", padx=4, pady=(0, 4))
        tk.Button(bw, text="Добавить дату", command=lambda: self._add_date(self.list_white)).pack(side="left")
        tk.Button(bw, text="Диапазон", command=lambda: self._add_range(self.list_white)).pack(side="left", padx=4)
        tk.Button(bw, text="Удалить", command=lambda: self._del_date(self.list_white)).pack(side="left")

        # blacklist
        fb = tk.LabelFrame(frame_dates, text="Чёрный список (пусто — ничего не исключается)")
        fb.pack(side="left", fill="both", expand=True, padx=(4, 0))
        self.list_black = tk.Listbox(fb, height=6)
        self.list_black.pack(fill="both", expand=True, padx=4, pady=4)
        bb = tk.Frame(fb)
        bb.pack(fill="x", padx=4, pady=(0, 4))
        tk.Button(bb, text="Добавить дату", command=lambda: self._add_date(self.list_black)).pack(side="left")
        tk.Button(bb, text="Диапазон", command=lambda: self._add_range(self.list_black)).pack(side="left", padx=4)
        tk.Button(bb, text="Удалить", command=lambda: self._del_date(self.list_black)).pack(side="left")

        # --- Кнопки ---
        frame_btn = tk.Frame(self)
        frame_btn.pack(fill="x", **pad)
        tk.Button(frame_btn, text="Запустить сортировку", command=self._run).pack(side="left", padx=6)
        tk.Button(frame_btn, text="Сохранить конфиг", command=self._save).pack(side="right")
        tk.Button(frame_btn, text="Сбросить настройки", command=self._reset).pack(side="right", padx=6)
        tk.Button(frame_btn, text="Выход", command=self.destroy).pack(side="right")

        # --- Прогресс + лог ---
        frame_prog = tk.LabelFrame(self, text="Выполнение")
        frame_prog.pack(fill="both", expand=True, **pad)

        self.progress = ttk.Progressbar(frame_prog, orient="horizontal", mode="determinate")
        self.progress.pack(fill="x", padx=4, pady=4)

        self.log = tk.Text(frame_prog, height=8, state="disabled")
        self.log.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        # --- Дополнительные настройки (выпадающая секция) ---
        self.adv_open = False
        self.adv_header = tk.Frame(self)
        self.adv_header.pack(fill="x", padx=6, pady=(3, 0))
        self.adv_arrow = tk.Label(self.adv_header, text="▶", width=2)
        self.adv_arrow.pack(side="left")
        self.adv_title = tk.Label(self.adv_header, text="Дополнительные настройки", fg="black")
        self.adv_title.pack(side="left")
        # клик по стрелке или заголовку раскрывает/сворачивает
        for w in (self.adv_arrow, self.adv_title, self.adv_header):
            w.bind("<Button-1>", lambda e: self._toggle_adv())

        self.frame_adv = tk.LabelFrame(self, text="")

        tk.Label(self.frame_adv, text="Regex:").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        self.var_regex = tk.StringVar()
        tk.Entry(self.frame_adv, textvariable=self.var_regex, width=60).grid(row=0, column=1, columnspan=3, sticky="we", padx=4, pady=2)

        tk.Label(self.frame_adv, text="Формат даты:").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        self.var_datefmt = tk.StringVar()
        tk.Entry(self.frame_adv, textvariable=self.var_datefmt, width=16).grid(row=1, column=1, sticky="w", padx=4, pady=2)

        tk.Label(self.frame_adv, text="Формат времени:").grid(row=1, column=2, sticky="w", padx=4, pady=2)
        self.var_timefmt = tk.StringVar()
        tk.Entry(self.frame_adv, textvariable=self.var_timefmt, width=16).grid(row=1, column=3, sticky="w", padx=4, pady=2)

        self.var_overwrite = tk.BooleanVar(value=False)
        tk.Checkbutton(self.frame_adv, text="Перезаписывать существующие файлы",
                       variable=self.var_overwrite).grid(row=2, column=0, columnspan=4, sticky="w", padx=4, pady=2)

        self.frame_adv.columnconfigure(1, weight=1)

    def _toggle_adv(self):
        # Раскрывает/сворачивает блок дополнительных настроек
        self.adv_open = not self.adv_open
        if self.adv_open:
            self.adv_arrow.config(text="▼")
            self.frame_adv.pack(fill="x", padx=6, pady=(0, 3), after=self.adv_header)
        else:
            self.adv_arrow.config(text="▶")
            self.frame_adv.pack_forget()

    def _pick_dir(self, var):
        d = filedialog.askdirectory()
        if d:
            var.set(d)

    # ---------- интервалы: ячейки ----------

    def _add_interval_row(self, values=None):
        # Создаёт новую строку интервала: ЧЧ:ММ - ЧЧ:ММ и крестик удаления
        row = tk.Frame(self.intervals_container)
        row.pack(fill="x", pady=1)

        v_h1 = tk.StringVar(value=(values[0] if values else "09"))
        v_m1 = tk.StringVar(value=(values[1] if values else "00"))
        v_h2 = tk.StringVar(value=(values[2] if values else "10"))
        v_m2 = tk.StringVar(value=(values[3] if values else "00"))

        # Валидация: только 2 цифры
        vcmd = (self.register(lambda s: len(s) <= 2 and s.isdigit() or s == ""), "%P")

        tk.Label(row, text="С:").pack(side="left")
        e_h1 = tk.Entry(row, textvariable=v_h1, width=3, validate="key", validatecommand=vcmd)
        e_h1.pack(side="left")
        tk.Label(row, text=":").pack(side="left")
        tk.Entry(row, textvariable=v_m1, width=3, validate="key", validatecommand=vcmd).pack(side="left")

        tk.Label(row, text="  По:").pack(side="left")
        tk.Entry(row, textvariable=v_h2, width=3, validate="key", validatecommand=vcmd).pack(side="left")
        tk.Label(row, text=":").pack(side="left")
        tk.Entry(row, textvariable=v_m2, width=3, validate="key", validatecommand=vcmd).pack(side="left")

        entry = (row, v_h1, v_m1, v_h2, v_m2)
        self.interval_rows.append(entry)

        tk.Button(row, text="✕", width=2, command=lambda: self._del_interval_row(entry)).pack(side="left", padx=6)

    def _del_interval_row(self, entry):
        row = entry[0]
        row.destroy()
        self.interval_rows.remove(entry)

    def _collect_intervals(self):
        # Собирает заполненные интервалы; пустые строки игнорируются
        result = []
        for (_row, v_h1, v_m1, v_h2, v_m2) in self.interval_rows:
            h1, m1, h2, m2 = v_h1.get().strip(), v_m1.get().strip(), v_h2.get().strip(), v_m2.get().strip()
            if not (h1 or m1 or h2 or m2):
                continue
            try:
                a = f"{int(h1):02d}:{int(m1):02d}"
                b = f"{int(h2):02d}:{int(m2):02d}"
                ta = datetime.strptime(a, "%H:%M").time()
                tb = datetime.strptime(b, "%H:%M").time()
            except ValueError:
                raise ValueError(f"Некорректный интервал: {h1}:{m1}-{h2}:{m2}")
            if ta > tb:
                raise ValueError(f"Начало интервала позже конца: {a}-{b}")
            result.append(f"{a}-{b}")
        return result

    # ---------- заполнение формы ----------

    def _fill_ui(self):
        c = self.cfg
        self.var_src.set(c["src_dir"])
        self.var_dst.set(c["dst_dir"])
        self.var_regex.set(c["filename_regex"])
        self.var_datefmt.set(c["date_format"])
        self.var_timefmt.set(c["time_format"])
        self.var_daytype_label.set(DAY_TYPE_LABELS.get(c["day_type"], "Все дни"))
        self.var_overwrite.set(c["overwrite"])

        # интервалы — ячейки
        for row in list(self.interval_rows):
            row[0].destroy()
        self.interval_rows = []
        for it in c["intervals"]:
            a, b = it.split("-")
            h1, m1 = a.split(":")
            h2, m2 = b.split(":")
            self._add_interval_row((h1, m1, h2, m2))
        if not c["intervals"]:
            self._add_interval_row()

        # списки дат
        self.list_white.delete(0, "end")
        self.list_black.delete(0, "end")
        for d in c["whitelist"]:
            self.list_white.insert("end", d)
        for d in c["blacklist"]:
            self.list_black.insert("end", d)

    def _read_ui(self):
        # Собирает конфиг из полей формы
        return {
            "src_dir": self.var_src.get().strip(),
            "dst_dir": self.var_dst.get().strip(),
            "filename_regex": self.var_regex.get().strip(),
            "date_format": self.var_datefmt.get().strip(),
            "time_format": self.var_timefmt.get().strip(),
            "intervals": self._collect_intervals(),
            "whitelist": list(self.list_white.get(0, "end")),
            "blacklist": list(self.list_black.get(0, "end")),
            "day_type": DAY_TYPE_BY_LABEL.get(self.var_daytype_label.get(), "all"),
            "overwrite": self.var_overwrite.get(),
        }

    # ---------- даты ----------

    def _add_date(self, listbox):
        dlg = CalendarDialog(self, "Выбор даты", range_mode=False)
        self.wait_window(dlg)
        if dlg.result:
            listbox.insert("end", dlg.result)

    def _add_range(self, listbox):
        dlg = CalendarDialog(self, "Выбор диапазона", range_mode=True)
        self.wait_window(dlg)
        if dlg.result:
            listbox.insert("end", dlg.result)

    def _del_date(self, listbox):
        sel = listbox.curselection()
        if sel:
            listbox.delete(sel[0])

    # ---------- сохранение/сброс/запуск ----------

    def _save(self):
        try:
            cfg = self._read_ui()
        except ValueError as e:
            messagebox.showerror("Ошибка", str(e))
            return
        try:
            save_config(cfg)
            camsort.load_config(CONFIG_PATH)
        except (SystemExit, ValueError) as e:
            messagebox.showerror("Ошибка конфига", str(e))
            return
        messagebox.showinfo("Готово", f"Конфиг сохранён:\n{CONFIG_PATH}")

    def _reset(self):
        if not messagebox.askyesno("Сброс", "Удалить текущий конфиг и вернуть настройки по умолчанию?"):
            return
        if os.path.isfile(CONFIG_PATH):
            os.remove(CONFIG_PATH)
        self.cfg = default_config()
        self._fill_ui()
        messagebox.showinfo("Готово", "Настройки сброшены")

    def _log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.log_queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "progress":
                    done, total = payload
                    self.progress["maximum"] = max(total, 1)
                    self.progress["value"] = done
                elif kind == "done":
                    self._log("--- готово ---")
                    messagebox.showinfo("Готово", "Сортировка завершена")
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _run(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Подождите", "Сортировка уже выполняется")
            return
        try:
            cfg = self._read_ui()
            save_config(cfg)
            camsort.load_config(CONFIG_PATH)
        except (SystemExit, ValueError) as e:
            messagebox.showerror("Ошибка конфига", str(e))
            return

        self.progress["value"] = 0
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

        self.worker = threading.Thread(target=self._worker_run, daemon=True)
        self.worker.start()

    def _worker_run(self):
        import io
        import contextlib

        class QueueWriter(io.TextIOBase):
            def __init__(self, q):
                self.q = q

            def write(self, s):
                if s.strip():
                    self.q.put(("log", s.rstrip()))
                return len(s)

        def progress_cb(done, total):
            self.log_queue.put(("progress", (done, total)))

        buf = QueueWriter(self.log_queue)
        try:
            with contextlib.redirect_stdout(buf):
                camsort.run(CONFIG_PATH, progress_cb=progress_cb)
            self.log_queue.put(("done", None))
        except SystemExit as e:
            self.log_queue.put(("log", str(e)))
            self.log_queue.put(("done", None))
        except Exception as e:
            self.log_queue.put(("log", f"ОШИБКА: {e}"))
            self.log_queue.put(("done", None))


if __name__ == "__main__":
    App().mainloop()