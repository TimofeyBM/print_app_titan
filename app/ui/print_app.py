import os
import threading
import time
import random
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

# DB init
from app.db.init_db import init_db

# Сервисы
from app.core.constants import SUPPORTED_PRINTER_EXTS, DEFAULT_CANCEL_PASSWORD
from app.services.settings_service_db import SettingsServiceDB as SettingsService
from app.services.io_service import IOService
from app.services.printer_service import PrinterService
from app.services.task_service_db import TaskServiceDB as TaskService
from app.services.history_service_db import HistoryServiceDB as HistoryService
from app.services.label_service import LabelService
from app.services.import_export_service_db import ImportExportServiceDB

def ask_collector(collectors_list):
    """Показывает окно выбора сборщика перед запуском программы"""
    dialog = tk.Toplevel()
    dialog.title("Выбор сборщика")
    dialog.geometry("300x150")
    dialog.grab_set()  # блокирует основное окно

    tk.Label(dialog, text="Выберите сборщика:", font=("Arial", 12)).pack(pady=10)

    collector_var = tk.StringVar()
    combo = ttk.Combobox(dialog, textvariable=collector_var, values=collectors_list, width=25, state="readonly")
    combo.pack(pady=5)
    combo.current(0)  # выбираем первого по умолчанию

    def confirm():
        if not collector_var.get():
            messagebox.showwarning("Ошибка", "Выберите сборщика!")
            return
        dialog.destroy()

    ttk.Button(dialog, text="ОК", command=confirm).pack(pady=10)

    dialog.wait_window()  # ждём закрытия
    return collector_var.get()

class PrintApp:
    """UI + координация сервисов (PostgreSQL)."""
    def __init__(self, root: tk.Tk):
        init_db()
        self.root = root
        self.root.title("Печать файлов по артикулу (PostgreSQL)")
        self.root.geometry("980x840")

        # --- сервисы ---
        self.settings_srv = SettingsService()
        self.io_srv = IOService()
        self.printer_srv = PrinterService()
        self.task_srv = TaskService()
        self.hist_srv = HistoryService()
        self.label_srv = LabelService()
        self.imp_exp_srv = ImportExportServiceDB()

        # --- загрузка настроек ---
        self.settings = self.settings_srv.load()
        # после self.settings = self.settings_srv.load() и var'ов base_dir/auto/temp

        self.cancel_password = self.settings.get("cancel_password", DEFAULT_CANCEL_PASSWORD)

        self.base_dir = tk.StringVar(value=self.settings["base_dir"])
        self.auto_save_dir = tk.StringVar(value=self.settings["auto_save_dir"])
        self.temp_save_dir = tk.StringVar(value=self.settings["temp_save_dir"])
        self.task_folder_path = tk.StringVar(value=self.settings.get("task_folder_path",""))  # не используется, оставлено для совместимости

        self.collectors_list = list(self.settings.get("collectors_list", []))
        self.inspectors_list = list(self.settings.get("inspectors_list", []))
        self.printer_settings = dict(self.settings.get("printer_settings", {}))
        use_emul = os.getenv("PRINT_EMULATE", "0") == "1"
        if use_emul:
            from app.services.printer_emulator import EmulatedPrinterService
            # temp_save_dir уже установлен из настроек, берем его путь
            self.printer_srv = EmulatedPrinterService(self.temp_save_dir.get())
            # чтобы в UI и логах было понятно, что печать — эмуляция
            self.log("Эмуляция печати включена (PRINT_EMULATE=1). Файлы копируются в temp_save_dir/_printed/<date>")

        # --- состояние ---
        self.articles_data = []             # [{"article": str, "copies": int}, ...] (для UI)
        self.remaining_copies = {}          # {article: left}
        self.collector_data = []            # [{"article","collector","datetime","copies"}] (кэш UI)
        self.check_history = []             # [{"article","inspector","datetime"}] (кэш UI)
        self.last_collector_time = {}
        self.collector_timeout = 120
        self.shift_started = False
        self.available_printers = []
        self.printing_in_progress = False
        self.stop_printing = False

        # --- UI-переменные ---
        self.shift_button_var = tk.StringVar(value="Смена не начата")
        self.file_path_var = tk.StringVar(value="")
        self.print_status_var = tk.StringVar(value="Готов к работе")
        self.task_status_var = tk.StringVar(value="Введите имя сборщика")
        self.task_info_var = tk.StringVar(value="Загружено артикулов: 0")

        # printer vars по расширениям
        self.printer_vars = {ext: tk.StringVar(value=self.printer_settings.get(ext, "")) for ext in SUPPORTED_PRINTER_EXTS}
        self.printer_combos = {}

        # --- UI ---
        self._build_ui()

        # --- данные ---
        self._detect_printers()
        self._load_histories()

        # --- закрытие ---
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    # ------------- UI build -------------
    def _build_ui(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.assembly_frame = ttk.Frame(self.notebook, padding="10")
        self.task_frame = ttk.Frame(self.notebook, padding="10")
        self.check_frame = ttk.Frame(self.notebook, padding="10")
        self.settings_frame = ttk.Frame(self.notebook, padding="10")

        self.notebook.add(self.assembly_frame, text="Сборка")
        self.notebook.add(self.task_frame, text="Задание")
        self.notebook.add(self.check_frame, text="Проверка")
        self.notebook.add(self.settings_frame, text="Настройки")

        self._build_assembly_tab()
        self._build_task_tab()
        self._build_check_tab()
        self._build_settings_tab()

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _on_tab_changed(self, event):
        idx = self.notebook.index(self.notebook.select())
        if idx != 3:
            self.save_settings()

    # ---------- Assembly tab ----------
    def _build_assembly_tab(self):
        shift_frame = ttk.Frame(self.assembly_frame)
        shift_frame.grid(row=0, column=0, columnspan=5, pady=5, sticky="w")

        self.start_shift_button = ttk.Button(shift_frame, text="Начать смену", command=self.start_shift)
        self.start_shift_button.grid(row=0, column=0, padx=5)

        self.continue_shift_button = ttk.Button(shift_frame, text="Продолжить смену", command=self.continue_shift)
        self.continue_shift_button.grid(row=0, column=1, padx=5)

        ttk.Label(shift_frame, textvariable=self.shift_button_var).grid(row=0, column=2, padx=10)

        ttk.Label(self.assembly_frame, text="Ручной ввод артикула:", font=('Arial', 10, 'bold')).grid(row=1, column=0, sticky="w", pady=5)
        # self.entry = ttk.Entry(self.assembly_frame, width=30)
        # self.entry.grid(row=1, column=1, pady=5, padx=5)
        # self.entry.bind("<Return>", lambda e: self.print_single_article())
        self.entry = ttk.Combobox(
            self.assembly_frame,
            values=[row["article"] for row in self.articles_data],
            width=30
        )
        self.entry.grid(row=1, column=1, pady=5, padx=5)
        self.entry.bind("<Return>", lambda e: self.print_single_article())

        ttk.Label(self.assembly_frame, text="Копий:").grid(row=1, column=2, sticky="w", pady=5)
        self.copies_entry = ttk.Entry(self.assembly_frame, width=10)
        self.copies_entry.insert(0, "1")
        self.copies_entry.grid(row=1, column=3, pady=5, padx=5)

        ttk.Button(self.assembly_frame, text="Печать", command=self.print_single_article).grid(row=1, column=4, padx=5)

        ttk.Label(self.assembly_frame, text="Загрузка файла:", font=('Arial', 10, 'bold')).grid(row=2, column=0, columnspan=5, sticky="w", pady=(20,10))
        ttk.Entry(self.assembly_frame, textvariable=self.file_path_var, width=40, state='readonly').grid(row=3, column=0, columnspan=3, sticky="w", pady=5)

        self.select_file_button = ttk.Button(self.assembly_frame, text="Выбрать файл", command=self.select_file, state="disabled")
        self.select_file_button.grid(row=3, column=3, padx=5)

        self.load_file_button = ttk.Button(self.assembly_frame, text="Загрузить", command=self.load_file_data, state="disabled")
        self.load_file_button.grid(row=3, column=4, padx=5)

        ttk.Label(self.assembly_frame, text="Загруженные артикулы:", font=('Arial', 10, 'bold')).grid(row=4, column=0, columnspan=5, sticky="w", pady=(30,5))

        cols = ('article', 'copies', 'status')
        self.tree = ttk.Treeview(self.assembly_frame, columns=cols, show='headings', height=10)
        for c, title, width in [('article','Артикул',240), ('copies','Копий',100), ('status','Статус',120)]:
            self.tree.heading(c, text=title)
            self.tree.column(c, width=width)
        self.tree.grid(row=4, column=0, columnspan=5, pady=5, sticky="nsew")
        self.load_from_db_button = ttk.Button(
            self.assembly_frame,
            text="Загрузить из БД",
            command=self.load_task_from_db,
            state="disabled"
        )
        self.load_from_db_button.grid(row=3, column=5, padx=5)

        tree_scrollbar = ttk.Scrollbar(self.assembly_frame, orient="vertical", command=self.tree.yview)
        tree_scrollbar.grid(row=4, column=5, sticky="ns", pady=5)
        self.tree.configure(yscrollcommand=tree_scrollbar.set)

        btn_frame = ttk.Frame(self.assembly_frame)
        btn_frame.grid(row=5, column=0, columnspan=6, pady=10, sticky="w")

        ttk.Button(btn_frame, text="Печать всех", command=self.start_print_all_thread).grid(row=0, column=0, padx=5)
        ttk.Button(btn_frame, text="Остановить печать", command=self.stop_printing_process).grid(row=0, column=1, padx=5)
        ttk.Button(btn_frame, text="Очистить список", command=self.clear_articles_list).grid(row=0, column=2, padx=5)

        ttk.Label(btn_frame, textvariable=self.print_status_var).grid(row=0, column=3, padx=10)

        self.assembly_frame.columnconfigure(0, weight=1)
        self.assembly_frame.rowconfigure(4, weight=1)

    # ---------- Task tab ----------
    def _build_task_tab(self):
        ttk.Label(self.task_frame, text="Режим задания", font=('Arial', 12, 'bold')).grid(row=0, column=0, columnspan=2, pady=10)
        ttk.Label(self.task_frame, text="Сборщик:*").grid(row=1, column=0, sticky="w", pady=5)
        self.collector_var = tk.StringVar()
        # self.collector_entry = ttk.Entry(self.task_frame, textvariable=self.collector_var, width=30)
        self.collector_entry = ttk.Combobox(
            self.task_frame,
            textvariable=self.collector_var,
            values=self.collectors_list,  # список из настроек
            width=30
        )
        self.collector_entry.grid(row=1, column=1, pady=5, padx=5)
        self.collector_entry.bind("<<ComboboxSelected>>", self.update_collector_button_state)

        # self.collector_entry.grid(row=1, column=1, pady=5, padx=5)
        # self.collector_entry.bind("<KeyRelease>", self.update_collector_button_state)

        ttk.Label(self.task_frame, text="Печать следующего артикула (все файлы, кроме .btw), по 1 копии").grid(row=2, column=0, columnspan=2, pady=5)

        self.collect_button = ttk.Button(self.task_frame, text="Собрать", command=self.start_task_thread, state="disabled")
        self.collect_button.grid(row=5, column=0, padx=5, pady=20)

        self.cancel_task_button = ttk.Button(self.task_frame, text="Отмена", command=self.cancel_last_task)
        self.cancel_task_button.grid(row=5, column=1, padx=5, pady=20)

        ttk.Label(self.task_frame, textvariable=self.task_status_var).grid(row=6, column=0, columnspan=2, pady=10)
        ttk.Label(self.task_frame, textvariable=self.task_info_var).grid(row=7, column=0, columnspan=2, pady=5)

        ttk.Label(self.task_frame, text="История сборки:", font=('Arial', 10, 'bold')).grid(row=8, column=0, columnspan=2, sticky="w", pady=(20,5))
        cols = ('article', 'collector', 'datetime', 'copies')
        self.collector_tree = ttk.Treeview(self.task_frame, columns=cols, show='headings', height=8)
        for c, title, width in [('article','Артикул',140), ('collector','Сборщик',120), ('datetime','Дата и время',180), ('copies','Кол-во',100)]:
            self.collector_tree.heading(c, text=title)
            self.collector_tree.column(c, width=width)
        self.collector_tree.grid(row=9, column=0, columnspan=2, pady=5, sticky="nsew")
        ct_scroll = ttk.Scrollbar(self.task_frame, orient="vertical", command=self.collector_tree.yview)
        ct_scroll.grid(row=9, column=2, sticky="ns", pady=5)
        self.collector_tree.configure(yscrollcommand=ct_scroll.set)

        ctrl = ttk.Frame(self.task_frame); ctrl.grid(row=10, column=0, columnspan=2, pady=10)
        ttk.Button(ctrl, text="Сохранить историю сборки", command=self.save_collector_data_to_file).grid(row=0, column=0, padx=5)
        ttk.Button(ctrl, text="Очистить историю сборки", command=self.clear_collector_data).grid(row=0, column=1, padx=5)
        ttk.Button(ctrl, text="Обновить задание", command=self.force_load_task).grid(row=0, column=2, padx=5)

        self.task_frame.columnconfigure(0, weight=1)
        self.task_frame.columnconfigure(1, weight=1)
        self.task_frame.rowconfigure(9, weight=1)

    # ---------- Check tab ----------
    def _build_check_tab(self):
        ttk.Label(self.check_frame, text="Режим проверки", font=('Arial', 12, 'bold')).grid(row=0, column=0, columnspan=2, pady=10)
        ttk.Label(self.check_frame, text="Проверяющий:*").grid(row=1, column=0, sticky="w", pady=5)

        self.inspector_var = tk.StringVar()
        # self.inspector_entry = ttk.Entry(self.check_frame, textvariable=self.inspector_var, width=30)
        self.inspector_entry = ttk.Combobox(
            self.check_frame,
            textvariable=self.inspector_var,
            values=self.inspectors_list,  # список из настроек
            width=30
        )
        self.inspector_entry.grid(row=1, column=1, pady=5, padx=5)
        self.inspector_entry.bind("<<ComboboxSelected>>", self.update_check_button_state)

        # self.inspector_entry.grid(row=1, column=1, pady=5, padx=5)
        # self.inspector_entry.bind("<KeyRelease>", self.update_check_button_state)

        ttk.Label(self.check_frame, text="Артикул:").grid(row=2, column=0, sticky="w", pady=10)
        self.check_article_var = tk.StringVar()
        # ent = ttk.Entry(self.check_frame, textvariable=self.check_article_var, width=30)
        # ent.grid(row=2, column=1, pady=10, padx=5)
        # ent.bind("<Return>", lambda e: self.start_check_thread())
        self.check_article_entry = ttk.Combobox(
            self.check_frame,
            textvariable=self.check_article_var,
            values=[row["article"] for row in self.articles_data],
            width=30
        )
        self.check_article_entry.grid(row=2, column=1, pady=10, padx=5)
        self.check_article_entry.bind("<Return>", lambda e: self.start_check_thread())

        self.check_button = ttk.Button(self.check_frame, text="Проверить", command=self.start_check_thread, state="disabled")
        self.check_button.grid(row=3, column=0, padx=5, pady=20)
        self.cancel_check_button = ttk.Button(self.check_frame, text="Отмена", command=self.cancel_last_check)
        self.cancel_check_button.grid(row=3, column=1, padx=5, pady=20)

        self.check_status_var = tk.StringVar(value="Введите данные для проверки")
        ttk.Label(self.check_frame, textvariable=self.check_status_var).grid(row=4, column=0, columnspan=2, pady=10)

        ttk.Label(self.check_frame, text="История проверок:", font=('Arial', 10, 'bold')).grid(row=5, column=0, columnspan=2, sticky="w", pady=(20,5))
        cols = ('article','inspector','datetime')
        self.check_tree = ttk.Treeview(self.check_frame, columns=cols, show='headings', height=8)
        for c, title, width in [('article','Артикул',150), ('inspector','Проверяющий',150), ('datetime','Дата и время',180)]:
            self.check_tree.heading(c, text=title)
            self.check_tree.column(c, width=width)
        self.check_tree.grid(row=6, column=0, columnspan=2, pady=5, sticky="nsew")
        sc = ttk.Scrollbar(self.check_frame, orient="vertical", command=self.check_tree.yview)
        sc.grid(row=6, column=2, sticky="ns", pady=5)
        self.check_tree.configure(yscrollcommand=sc.set)

        hist_ctrl = ttk.Frame(self.check_frame); hist_ctrl.grid(row=7, column=0, columnspan=2, pady=10)
        ttk.Button(hist_ctrl, text="Сохранить историю", command=self.save_check_history_to_file).grid(row=0, column=0, padx=5)
        ttk.Button(hist_ctrl, text="Очистить историю", command=self.clear_check_history).grid(row=0, column=1, padx=5)

        self.check_frame.columnconfigure(0, weight=1)
        self.check_frame.columnconfigure(1, weight=1)
        self.check_frame.rowconfigure(6, weight=1)

    # ---------- Settings tab ----------
    def _build_settings_tab(self):
        ttk.Label(self.settings_frame, text="Директория с товарами:", font=('Arial', 10, 'bold')).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0,10))
        ttk.Entry(self.settings_frame, textvariable=self.base_dir, width=50).grid(row=1, column=0, sticky="w", pady=5, padx=(0,5))
        ttk.Button(self.settings_frame, text="Выбрать папку", command=self.select_directory).grid(row=1, column=1, padx=5)

        ttk.Label(self.settings_frame, text="Директория для автосохранения:", font=('Arial', 10, 'bold')).grid(row=2, column=0, columnspan=2, sticky="w", pady=(20,10))
        ttk.Entry(self.settings_frame, textvariable=self.auto_save_dir, width=50).grid(row=3, column=0, sticky="w", pady=5, padx=(0,5))
        ttk.Button(self.settings_frame, text="Выбрать папку", command=self.select_auto_save_directory).grid(row=3, column=1, padx=5)

        ttk.Label(self.settings_frame, text="Директория для временного автосохранения:", font=('Arial', 10, 'bold')).grid(row=4, column=0, columnspan=2, sticky="w", pady=(20,10))
        ttk.Entry(self.settings_frame, textvariable=self.temp_save_dir, width=50).grid(row=5, column=0, sticky="w", pady=5, padx=(0,5))
        ttk.Button(self.settings_frame, text="Выбрать папку", command=self.select_temp_save_directory).grid(row=5, column=1, padx=5)

        # task_folder_path оставлен для совместимости (не используется)
        ttk.Label(self.settings_frame, text="(Не используется) Папка для задания на сборку:", font=('Arial', 10, 'bold')).grid(row=6, column=0, columnspan=2, sticky="w", pady=(20,10))
        ttk.Entry(self.settings_frame, textvariable=self.task_folder_path, width=50, state='disabled').grid(row=7, column=0, sticky="w", pady=5, padx=(0,5))
        ttk.Button(self.settings_frame, text="...", state='disabled').grid(row=7, column=1, padx=5)

        ttk.Label(self.settings_frame, text="Пароль отмены:", font=('Arial', 10, 'bold')).grid(row=8, column=0, sticky="w", pady=(20,10))
        self.password_var = tk.StringVar(value=self.cancel_password)
        ttk.Entry(self.settings_frame, textvariable=self.password_var, width=20, show="*").grid(row=8, column=1, sticky="w")
        ttk.Button(self.settings_frame, text="Сохранить пароль", command=self.save_password).grid(row=8, column=2, padx=6)

        ttk.Label(self.settings_frame, text="Списки:", font=('Arial', 10, 'bold')).grid(row=9, column=0, columnspan=2, sticky="w", pady=(20,10))
        lists = ttk.Frame(self.settings_frame); lists.grid(row=10, column=0, columnspan=2, sticky="we")

        ttk.Label(lists, text="Сборщики:").grid(row=0, column=0, sticky="w", pady=2, padx=5)
        self.new_collector_var = tk.StringVar()
        ttk.Entry(lists, textvariable=self.new_collector_var, width=20).grid(row=0, column=1, pady=2, padx=5)
        ttk.Button(lists, text="Добавить", command=self.add_collector).grid(row=0, column=2, padx=5)
        self.collectors_listbox = tk.Listbox(lists, height=4, width=25); self.collectors_listbox.grid(row=1, column=0, columnspan=2, pady=5, padx=5, sticky="we")
        ttk.Button(lists, text="Удалить", command=self.remove_collector).grid(row=1, column=2, padx=5)

        ttk.Label(lists, text="Проверяющие:").grid(row=2, column=0, sticky="w", pady=(10,2), padx=5)
        self.new_inspector_var = tk.StringVar()
        ttk.Entry(lists, textvariable=self.new_inspector_var, width=20).grid(row=2, column=1, pady=(10,2), padx=5)
        ttk.Button(lists, text="Добавить", command=self.add_inspector).grid(row=2, column=2, padx=5)
        self.inspectors_listbox = tk.Listbox(lists, height=4, width=25); self.inspectors_listbox.grid(row=3, column=0, columnspan=2, pady=5, padx=5, sticky="we")
        ttk.Button(lists, text="Удалить", command=self.remove_inspector).grid(row=3, column=2, padx=5)

        self.update_collectors_listbox()
        self.update_inspectors_listbox()

        ttk.Label(self.settings_frame, text="Принтеры по расширениям:", font=('Arial', 10, 'bold')).grid(row=12, column=0, columnspan=2, sticky="w", pady=(20,10))
        printer_frame = ttk.Frame(self.settings_frame); printer_frame.grid(row=13, column=0, columnspan=2, sticky="we")
        canvas = tk.Canvas(printer_frame, height=200)
        scrollbar = ttk.Scrollbar(printer_frame, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas)
        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0,0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        for i, ext in enumerate(sorted(self.printer_vars.keys())):
            ttk.Label(scrollable, text=f"{ext}:").grid(row=i, column=0, sticky="w", pady=2, padx=5)
            combo = ttk.Combobox(scrollable, textvariable=self.printer_vars[ext], width=32, state="readonly")
            combo.grid(row=i, column=1, pady=2, padx=5); self.printer_combos[ext] = combo
            ttk.Button(scrollable, text="Тест", command=lambda ext=ext: self.test_printer(ext)).grid(row=i, column=2, padx=5)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Импорт/экспорт CSV
        csv_frame = ttk.LabelFrame(self.settings_frame, text="Импорт / Экспорт CSV")
        csv_frame.grid(row=23, column=0, columnspan=3, sticky="we", pady=(15,5))
        ttk.Button(csv_frame, text="Импорт задания (merge)", command=self.ui_import_task_merge).grid(row=0, column=0, padx=5, pady=5)
        ttk.Button(csv_frame, text="Импорт задания (replace)", command=self.ui_import_task_replace).grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(csv_frame, text="Экспорт задания", command=self.ui_export_task).grid(row=0, column=2, padx=5, pady=5)
        ttk.Button(csv_frame, text="Импорт истории сборки", command=self.ui_import_collect).grid(row=1, column=0, padx=5, pady=5)
        ttk.Button(csv_frame, text="Экспорт истории сборки", command=self.ui_export_collect).grid(row=1, column=1, padx=5, pady=5)
        ttk.Button(csv_frame, text="Импорт истории проверок", command=self.ui_import_check).grid(row=2, column=0, padx=5, pady=5)
        ttk.Button(csv_frame, text="Экспорт истории проверок", command=self.ui_export_check).grid(row=2, column=1, padx=5, pady=5)

        ttk.Label(self.settings_frame, text="Лог:", font=('Arial', 10, 'bold')).grid(row=24, column=0, columnspan=2, sticky="w", pady=(20,5))
        self.log_text = tk.Text(self.settings_frame, height=10, width=82)
        self.log_text.grid(row=25, column=0, columnspan=2, sticky="nsew")
        s = ttk.Scrollbar(self.settings_frame, orient="vertical", command=self.log_text.yview)
        s.grid(row=25, column=2, sticky="ns"); self.log_text.configure(yscrollcommand=s.set)

        lb = ttk.Frame(self.settings_frame); lb.grid(row=26, column=0, columnspan=2, pady=5)
        ttk.Button(lb, text="Очистить лог", command=self.clear_log).grid(row=0, column=0, padx=5)
        ttk.Button(lb, text="Сохранить лог в файл", command=self.save_log_to_file).grid(row=0, column=1, padx=5)

        self.settings_frame.columnconfigure(0, weight=1)
        self.settings_frame.rowconfigure(25, weight=1)

    # ------------- Общие действия -------------
    def _detect_printers(self):
        printers = self.printer_srv.detect_available_printers()
        self.available_printers = printers
        for combo in self.printer_combos.values():
            combo['values'] = printers
        self.log(f"Найдено принтеров: {len(printers)}")

    def _load_histories(self):
        self.check_history = self.hist_srv.load_check_history("")
        self.collector_data = self.hist_srv.load_collector_data("")
        self.update_check_history_table()
        self.update_collector_table()
        self.log(f"Загружено историй: сборка={len(self.collector_data)}, проверка={len(self.check_history)}")

    def update_article_lists(self):
        values = [row["article"] for row in self.articles_data]
        if hasattr(self, "entry"):
            self.entry['values'] = values
        if hasattr(self, "check_article_entry"):
            self.check_article_entry['values'] = values

    def save_settings(self):
        self.printer_settings = {ext: var.get() for ext, var in self.printer_vars.items()}
        data = {
            "base_dir": self.base_dir.get(),
            "auto_save_dir": self.auto_save_dir.get(),
            "temp_save_dir": self.temp_save_dir.get(),
            "task_folder_path": self.task_folder_path.get(),
            "collectors_list": self.collectors_list,
            "inspectors_list": self.inspectors_list,
            "printer_settings": self.printer_settings,
            "cancel_password": self.cancel_password
        }
        self.settings_srv.save(data)
        self.log("Настройки сохранены.")

    # ------------- Вкладка Сборка -------------
    def select_file(self):
        if not self.shift_started:
            messagebox.showwarning("Внимание", "Сначала начните или продолжите смену!")
            return
        p = filedialog.askopenfilename(title="Выберите файл",
                                       filetypes=[("CSV", "*.csv"), ("Excel", "*.xlsx;*.xls"), ("Текст", "*.txt"), ("All files", "*.*")])
        if p:
            self.file_path_var.set(p)
            self.log(f"Выбран файл: {p}")

    def load_task_from_db(self):
        if not self.shift_started:
            messagebox.showwarning("Внимание", "Сначала начните или продолжите смену!")
            return
        try:
            # загрузка задания через сервис
            self.articles_data, self.remaining_copies = self.task_srv.load_task("")
            self._rebuild_assembly_table()
            self._update_task_info()
            self.update_article_lists()
            self.log("Артикулы успешно загружены из БД")
            messagebox.showinfo("Успех", "Задание загружено из базы данных.")
        except Exception as e:
            self.log(f"Ошибка загрузки из БД: {e}")
            messagebox.showerror("Ошибка", str(e))

    def load_file_data(self):
        if not self.shift_started:
            messagebox.showwarning("Внимание", "Сначала начните или продолжите смену!")
            return
        p = self.file_path_var.get().strip()
        if not p:
            messagebox.showerror("Ошибка", "Выберите файл!"); return
        try:
            new_data = self.io_srv.load_any(p)
            self.articles_data, self.remaining_copies, added, updated = self.task_srv.merge_articles(self.articles_data, new_data, self.remaining_copies)
            self._rebuild_assembly_table()
            self._update_task_info()
            self.update_article_lists()
            self.log(f"Загрузка завершена. Добавлено: {added}, Обновлено: {updated}, Всего: {len(self.articles_data)}")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка загрузки файла: {e}")
            self.log(f"Ошибка загрузки: {e}")

    def print_single_article(self):
        art = self.entry.get().strip()
        if not art:
            messagebox.showerror("Ошибка", "Введите артикул!"); return
        try:
            copies = max(1, int(self.copies_entry.get() or 1))
        except Exception:
            copies = 1
        self._print_article(art, copies, manual=True)

    def start_print_all_thread(self):
        if self.printing_in_progress:
            messagebox.showwarning("Внимание", "Печать уже выполняется!"); return
        if not self.articles_data:
            messagebox.showwarning("Внимание", "Нет загруженных артикулов!"); return
        t = threading.Thread(target=self._print_all_articles, daemon=True)
        t.start()

    def _print_all_articles(self):
        self.printing_in_progress = True
        self.stop_printing = False
        self.print_status_var.set("Печать...")
        success = 0
        total = len(self.articles_data)
        for i, row in enumerate(self.articles_data):
            if self.stop_printing:
                self.log("Печать остановлена пользователем"); break
            item_id = list(self.tree.get_children())[i]
            self.tree.set(item_id, 'status', 'В процессе')
            self.print_status_var.set(f"Печать: {i+1}/{total}")
            self.root.update()
            if self._print_article(row['article'], row['copies']):
                self.tree.set(item_id, 'status', 'Успешно'); success += 1
            else:
                self.tree.set(item_id, 'status', 'Ошибка')
            time.sleep(0.3)
        self.print_status_var.set("Готов к работе")
        self.printing_in_progress = False
        self.log(f"Готово! Успешно: {success}/{total}")

    def stop_printing_process(self):
        if self.printing_in_progress:
            self.stop_printing = True
            self.print_status_var.set("Останавливается...")
            self.log("Запрошена остановка печати...")
        else:
            messagebox.showinfo("Информация", "Печать не выполняется")

    def clear_articles_list(self):
        self.articles_data = []
        self.remaining_copies = {}
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._update_task_info()
        self.update_article_lists()
        self.log("Список артикулов очищен (локально). Задание в БД не тронуто.")

    def _rebuild_assembly_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in self.articles_data:
            self.tree.insert('', 'end', values=(row['article'], row['copies'], 'Ожидание'))

    # ------------- Вкладка Задание -------------
    def update_collector_button_state(self, event=None):
        name = self.collector_var.get().strip()
        if not name:
            self.collect_button.config(state="disabled"); self.task_status_var.set("Введите имя сборщика"); return
        if name not in self.collectors_list:
            self.collect_button.config(state="disabled"); self.task_status_var.set("Сборщик не найден в списке"); return
        current = time.time(); last = self.last_collector_time.get(name, 0)
        if current - last < self.collector_timeout:
            remain = int(self.collector_timeout - (current - last))
            self.collect_button.config(state="disabled"); self.task_status_var.set(f"Ждите {remain} сек.")
        else:
            self.collect_button.config(state="normal"); self.task_status_var.set("Готов к работе")

    def start_task_thread(self):
        if self.printing_in_progress:
            messagebox.showwarning("Внимание", "Печать уже выполняется!"); return
        name = self.collector_var.get().strip()
        if not name:
            messagebox.showwarning("Внимание", "Введите имя сборщика!"); return
        if name not in self.collectors_list:
            messagebox.showwarning("Внимание", "Сборщик не найден в списке!"); return
        t = threading.Thread(target=self._execute_task, args=(name,), daemon=True)
        t.start()

    def _execute_task(self, collector_name: str):
        self.printing_in_progress = True
        self.task_status_var.set("Выполнение задания...")

        # атомарный выбор позиции с уменьшением remaining (FOR UPDATE SKIP LOCKED)
        try:
            pick = self.task_srv.pick_next_available_and_decrement(order="fifo")
        except Exception as e:
            self.task_status_var.set("Ошибка БД при выборе задания")
            self.log(f"Ошибка выбора задания: {e}")
            self.printing_in_progress = False
            return

        if not pick:
            self.task_status_var.set("Все копии распечатаны!")
            self.log("Все копии распечатаны в режиме задания")
            self.printing_in_progress = False; return

        article, left = pick
        self.log(f"Режим задания: сборщик '{collector_name}', выбран '{article}' (осталось после уменьшения: {left})")

        ok = self._print_article_task(article)
        if not ok:
            # компенсируем уменьшение remaining
            try:
                self.task_srv.inc_remaining(article, by=1)
            except Exception as e:
                self.log(f"Ошибка компенсации remaining для '{article}': {e}")
            self.task_status_var.set(f"Ошибка печати: {article}")
            messagebox.showerror("Ошибка", "Проверьте принтер!")
            self.printing_in_progress = False; return

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.collector_data.append({'collector': collector_name, 'article': article, 'datetime': now, 'copies': 1})
        self.hist_srv.save_collector_data("", [self.collector_data[-1]])

        self.last_collector_time[collector_name] = time.time()
        self.update_collector_button_state()

        self.articles_data, self.remaining_copies = self.task_srv.load_task("")
        self.update_collector_table()

        self.task_status_var.set(f"Сборщик: {collector_name}, артикул: {article}")
        self._update_task_info()
        self.update_article_lists()
        self.printing_in_progress = False

    def cancel_last_task(self):
        if not self.collector_data:
            messagebox.showinfo("Информация", "Нет действий для отмены"); return
        if not self._ask_password():
            messagebox.showerror("Ошибка", "Неверный пароль!"); return
        last_db = self.hist_srv.cancel_last_collect()
        if not last_db:
            messagebox.showinfo("Информация", "Нет действий для отмены"); return
        art = last_db['article']
        self.task_srv.inc_remaining(art, by=int(last_db.get("copies",1)))
        self.collector_data.pop()
        self.update_collector_table(); self._update_task_info()
        self.update_article_lists()
        self.articles_data, self.remaining_copies = self.task_srv.load_task("")
        self.log(f"Отменено последнее действие: {last_db['collector']} — {art}")
        messagebox.showinfo("Успех", f"Отменено действие для артикула '{art}'")

    def update_collector_table(self):
        for i in self.collector_tree.get_children():
            self.collector_tree.delete(i)
        for row in self.collector_data:
            self.collector_tree.insert('', 'end', values=(row['article'], row['collector'], row['datetime'], row['copies']))

    def save_collector_data_to_file(self):
        if not self.collector_data:
            messagebox.showwarning("Внимание", "Нет данных для сохранения!"); return
        p = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")], title="Сохранить историю сборки")
        if p:
            # выгрузка из БД, чтобы всё было консистентно
            try:
                path = self.imp_exp_srv.export_collector_to_csv(p)
                self.log(f"История сборки сохранена: {path}")
                messagebox.showinfo("Успех", f"Сохранено: {path}")
            except Exception as e:
                self.log(f"Экспорт истории сборки ошибка: {e}")
                messagebox.showerror("Ошибка", str(e))

    def clear_collector_data(self):
        if messagebox.askyesno("Подтверждение", "Очистить историю сборки?"):
            self.collector_data = []; self.update_collector_table()
            self.log("История сборки очищена (только в UI). Данные в БД не удалены.")

    # ------------- Вкладка Проверка -------------
    def update_check_button_state(self, event=None):
        name = self.inspector_var.get().strip()
        if not name:
            self.check_button.config(state="disabled"); self.check_status_var.set("Введите имя проверяющего"); return
        if name not in self.inspectors_list:
            self.check_button.config(state="disabled"); self.check_status_var.set("Проверяющий не найден"); return
        self.check_button.config(state="normal")
        self.check_status_var.set("Готов к проверке" if self.check_article_var.get().strip() else "Введите артикул")

    def start_check_thread(self):
        name = self.inspector_var.get().strip(); art = self.check_article_var.get().strip()
        if not name:
            messagebox.showwarning("Внимание", "Введите имя проверяющего!"); return
        if name not in self.inspectors_list:
            messagebox.showwarning("Внимание", "Проверяющий не найден!"); return
        if not art:
            messagebox.showwarning("Внимание", "Введите артикул для проверки!"); return
        t = threading.Thread(target=self._execute_check, args=(name, art), daemon=True)
        t.start()

    def _execute_check(self, inspector_name: str, article: str):
        self.check_status_var.set("Проверка...")
        if not self._print_btw_files(article):
            self.check_status_var.set(f"Ошибка печати: {article}")
            self.log(f"Ошибка печати .btw для '{article}'")
            messagebox.showerror("Ошибка", "Проверьте принтер!"); return

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rec = {'article': article, 'inspector': inspector_name, 'datetime': now}
        self.check_history.append(rec)
        self.update_check_history_table()

        path = self.label_srv.create_check_label(self.temp_save_dir.get(), rec)
        png_printer = self.printer_vars['.png'].get() or None
        _ = self.printer_srv.print_file(path, png_printer)

        self.hist_srv.save_check_history("", [rec])

        self.check_status_var.set(f"Проверено: {article} (.btw напечатаны)")
        self.log(f"Проверка: {article} - {inspector_name} - {now}")
        self.check_article_var.set("")

    def cancel_last_check(self):
        if not self.check_history:
            messagebox.showinfo("Информация", "Нет проверок для отмены"); return
        if not self._ask_password():
            messagebox.showerror("Ошибка", "Неверный пароль!"); return
        last = self.hist_srv.cancel_last_check()
        if not last:
            messagebox.showinfo("Информация", "Нет проверок для отмены"); return
        self.check_history.pop()
        self.update_check_history_table()
        self.log(f"Отменена последняя проверка: {last.get('inspector','?')} — {last.get('article','?')}")
        messagebox.showinfo("Успех", f"Отменена последняя проверка для '{last.get('article','?')}'")

    def update_check_history_table(self):
        for i in self.check_tree.get_children():
            self.check_tree.delete(i)
        for row in self.check_history:
            self.check_tree.insert('', 'end', values=(row['article'], row['inspector'], row['datetime']))

    def save_check_history_to_file(self):
        if not self.check_history:
            messagebox.showwarning("Внимание", "Нет данных для сохранения!"); return
        p = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")], title="Сохранить историю проверки")
        if p:
            try:
                path = self.imp_exp_srv.export_check_to_csv(p)
                self.log(f"История проверок сохранена: {path}")
                messagebox.showinfo("Успех", f"Сохранено: {path}")
            except Exception as e:
                self.log(f"Экспорт истории проверок ошибка: {e}")
                messagebox.showerror("Ошибка", str(e))

    def clear_check_history(self):
        if messagebox.askyesno("Подтверждение", "Очистить историю проверок (только в UI)?"):
            self.check_history = []; self.update_check_history_table()
            self.log("История проверок очищена (только в UI). Данные в БД не удалены.")

    # ------------- Настройки -------------
    def select_directory(self):
        d = filedialog.askdirectory(title="Выберите папку с товарами")
        if d:
            self.base_dir.set(d); self.save_settings(); self.log(f"Директория с товарами: {d}")

    def select_auto_save_directory(self):
        d = filedialog.askdirectory(title="Выберите папку для автосохранения")
        if d:
            self.auto_save_dir.set(d); self.save_settings(); self.log(f"Автосохранение: {d}")

    def select_temp_save_directory(self):
        d = filedialog.askdirectory(title="Выберите папку для временного автосохранения")
        if d:
            self.temp_save_dir.set(d); self.save_settings(); self.log(f"Временное автосохранение: {d}")

    def save_password(self):
        new = self.password_var.get().strip()
        if new:
            self.cancel_password = new; self.save_settings()
            self.log("Пароль отмены сохранен")
            messagebox.showinfo("Успех", "Пароль отмены сохранен!")
        else:
            messagebox.showwarning("Внимание", "Пароль не может быть пустым!")

    def add_collector(self):
        name = self.new_collector_var.get().strip()
        if name and name not in self.collectors_list:
            self.collectors_list.append(name); self.update_collectors_listbox(); self.new_collector_var.set(""); self.save_settings()
            self.log(f"Добавлен сборщик: {name}")
        elif name in self.collectors_list:
            messagebox.showwarning("Внимание", "Такой сборщик уже есть!")

    def remove_collector(self):
        sel = self.collectors_listbox.curselection()
        if sel:
            name = self.collectors_list[sel[0]]
            self.collectors_list.pop(sel[0]); self.update_collectors_listbox(); self.save_settings()
            self.log(f"Удален сборщик: {name}")

    def update_collectors_listbox(self):
        self.collectors_listbox.delete(0, tk.END)
        for name in sorted(self.collectors_list):
            self.collectors_listbox.insert(tk.END, name)

    def add_inspector(self):
        name = self.new_inspector_var.get().strip()
        if name and name not in self.inspectors_list:
            self.inspectors_list.append(name); self.update_inspectors_listbox(); self.new_inspector_var.set(""); self.save_settings()
            self.log(f"Добавлен проверяющий: {name}")
        elif name in self.inspectors_list:
            messagebox.showwarning("Внимание", "Такой проверяющий уже есть!")

    def remove_inspector(self):
        sel = self.inspectors_listbox.curselection()
        if sel:
            name = self.inspectors_list[sel[0]]
            self.inspectors_list.pop(sel[0]); self.update_inspectors_listbox(); self.save_settings()
            self.log(f"Удален проверяющий: {name}")

    def ui_import_task_merge(self):
        p = filedialog.askopenfilename(title="CSV задания", filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if not p: return
        try:
            self.imp_exp_srv.import_task_from_csv(p, mode="merge")
            self.force_load_task()
            self.log(f"Импорт задания (merge): {p}")
            messagebox.showinfo("Успех", "Импорт завершён (merge).")
        except Exception as e:
            self.log(f"Импорт задания ошибка: {e}")
            messagebox.showerror("Ошибка", str(e))

    def ui_import_task_replace(self):
        p = filedialog.askopenfilename(title="CSV задания (replace)",
                                       filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if not p: return
        try:
            self.imp_exp_srv.import_task_from_csv(p, mode="replace")
            self.force_load_task()
            self.log(f"Импорт задания (replace): {p}")
            messagebox.showinfo("Успех", "Импорт завершён (replace).")
        except Exception as e:
            self.log(f"Импорт задания ошибка: {e}")
            messagebox.showerror("Ошибка", str(e))

    def ui_export_task(self):
        p = filedialog.asksaveasfilename(title="Экспорт задания", defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not p: return
        try:
            path = self.imp_exp_srv.export_task_to_csv(p)
            self.log(f"Экспорт задания: {path}")
            messagebox.showinfo("Успех", f"Сохранено: {path}")
        except Exception as e:
            self.log(f"Экспорт задания ошибка: {e}")
            messagebox.showerror("Ошибка", str(e))

    def ui_import_collect(self):
        p = filedialog.askopenfilename(title="CSV истории сборки", filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if not p: return
        try:
            # НЕ уменьшаем remaining по умолчанию; если нужно — передайте True
            self.imp_exp_srv.import_collector_from_csv(p, apply_to_remaining=False)
            self.collector_data = self.hist_srv.load_collector_data("")
            self.update_collector_table()
            self.log(f"Импорт истории сборки: {p}")
            messagebox.showinfo("Успех", "Импорт истории сборки завершён.")
        except Exception as e:
            self.log(f"Импорт истории сборки ошибка: {e}")
            messagebox.showerror("Ошибка", str(e))

    def ui_export_collect(self):
        p = filedialog.asksaveasfilename(title="Экспорт истории сборки", defaultextension=".csv",
                                         filetypes=[("CSV", "*.csv")])
        if not p: return
        try:
            path = self.imp_exp_srv.export_collector_to_csv(p)
            self.log(f"Экспорт истории сборки: {path}")
            messagebox.showinfo("Успех", f"Сохранено: {path}")
        except Exception as e:
            self.log(f"Экспорт истории сборки ошибка: {e}")
            messagebox.showerror("Ошибка", str(e))

    def ui_import_check(self):
        p = filedialog.askopenfilename(title="CSV истории проверок", filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if not p: return
        try:
            self.imp_exp_srv.import_check_from_csv(p)
            self.check_history = self.hist_srv.load_check_history("")
            self.update_check_history_table()
            self.log(f"Импорт истории проверок: {p}")
            messagebox.showinfo("Успех", "Импорт истории проверок завершён.")
        except Exception as e:
            self.log(f"Импорт истории проверок ошибка: {e}")
            messagebox.showerror("Ошибка", str(e))

    def ui_export_check(self):
        p = filedialog.asksaveasfilename(title="Экспорт истории проверок", defaultextension=".csv",
                                         filetypes=[("CSV", "*.csv")])
        if not p: return
        try:
            path = self.imp_exp_srv.export_check_to_csv(p)
            self.log(f"Экспорт истории проверок: {path}")
            messagebox.showinfo("Успех", f"Сохранено: {path}")
        except Exception as e:
            self.log(f"Экспорт истории проверок ошибка: {e}")
            messagebox.showerror("Ошибка", str(e))

    def update_inspectors_listbox(self):
        self.inspectors_listbox.delete(0, tk.END)
        for name in sorted(self.inspectors_list):
            self.inspectors_listbox.insert(tk.END, name)

    def test_printer(self, ext: str):
        printer = self.printer_vars.get(ext).get()
        if not printer:
            messagebox.showwarning("Внимание", "Выберите принтер для теста!"); return
        try:
            test_file = os.path.join(self.temp_save_dir.get(), "test_print.txt")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write(f"Тестовая печать для формата {ext}\nПринтер: {printer}\nВремя: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            ok = self.printer_srv.print_file(test_file, printer)
            if ok:
                self.log(f"Тестовая печать отправлена на {printer}")
                messagebox.showinfo("Успех", f"Тест отправлен на {printer}")
            else:
                self.log(f"Ошибка тестовой печати на {printer}")
                messagebox.showerror("Ошибка", "Не удалось отправить тест")
        except Exception as e:
            self.log(f"Ошибка теста: {e}")

    # ------------- Печать -------------
    def _get_printer_for_file(self, filename: str):
        ext = os.path.splitext(filename)[1].lower()
        pn = self.printer_vars.get(ext).get() if ext in self.printer_vars else ""
        return pn or None

    def _print_article(self, article: str, copies: int, manual: bool = False) -> bool:
        folder = os.path.join(self.base_dir.get(), article)
        if not os.path.exists(folder):
            msg = f"Папка '{article}' не найдена"
            self.log(f"Ошибка: {msg}")
            if manual: messagebox.showerror("Ошибка", msg)
            return False
        files = [f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))]
        if not files:
            msg = f"В папке '{article}' нет файлов"
            self.log(f"Ошибка: {msg}")
            if manual: messagebox.showerror("Ошибка", msg)
            return False
        ok = True; printed = 0
        for file in files:
            for _ in range(copies):
                p = os.path.join(folder, file)
                printer = self._get_printer_for_file(file)
                if self.printer_srv.print_file(p, printer):
                    printed += 1; self.log(f"Печать: {article} → {file}")
                    time.sleep(0.2)
                else:
                    ok = False; self.log(f"Ошибка печати: {file}")
        if manual:
            if ok: messagebox.showinfo("Успех", f"Артикул '{article}' отправлен на печать ({printed} файлов)")
            else: messagebox.showwarning("Внимание", f"Были ошибки при печати '{article}'")
        return ok

    def _print_article_task(self, article: str) -> bool:
        folder = os.path.join(self.base_dir.get(), article)
        if not os.path.exists(folder):
            self.log(f"Ошибка: Папка '{article}' не найдена"); return False
        files = [f for f in os.listdir(folder)
                 if os.path.isfile(os.path.join(folder, f)) and not f.lower().endswith('.btw')]
        if not files:
            self.log(f"Внимание: В '{article}' нет файлов для печати (кроме .btw)"); return False
        ok = True
        for f in files:
            p = os.path.join(folder, f)
            printer = self._get_printer_for_file(f)
            if self.printer_srv.print_file(p, printer):
                self.log(f"Задание: печать {f}")
                time.sleep(0.2)
            else:
                ok = False; self.log(f"Ошибка печати: {f}")
        return ok

    def _print_btw_files(self, article: str) -> bool:
        folder = os.path.join(self.base_dir.get(), article)
        if not os.path.exists(folder):
            self.log(f"Ошибка: Папка '{article}' не найдена для .btw"); return False
        files = [f for f in os.listdir(folder)
                 if os.path.isfile(os.path.join(folder, f)) and f.lower().endswith('.btw')]
        if not files:
            self.log(f"Внимание: В '{article}' нет .btw для печати"); return False
        ok = True
        for f in files:
            p = os.path.join(folder, f)
            printer = self._get_printer_for_file(f)
            if self.printer_srv.print_file(p, printer):
                self.log(f"Проверка: печать .btw {f}")
                time.sleep(0.2)
            else:
                ok = False; self.log(f"Ошибка печати .btw: {f}")
        return ok

    # ------------- Смена / задание -------------
    def start_shift(self):
        name = self.collector_var.get().strip()
        if not name:
            messagebox.showwarning("Внимание", "Выберите сборщика для начала смены!")
            return

        if messagebox.askyesno("Начать смену", f"Начать смену для сборщика {name}? Текущие данные будут очищены."):
            self.task_srv.start_new_shift(name)
            self.articles_data, self.remaining_copies = self.task_srv.load_task("")
            self._rebuild_assembly_table()
            self._update_task_info()
            self.shift_started = True
            self.shift_button_var.set(f"Смена начата ({name})")
            self._update_buttons_state()
            self.log(f"Новая смена начата для {name}")

    def continue_shift(self):
        sid = self.task_srv.continue_open_shift()
        if sid:
            self.articles_data, self.remaining_copies = self.task_srv.load_task("")
            self._rebuild_assembly_table(); self._update_task_info()
            self.update_article_lists()
            self.shift_started = True; self.shift_button_var.set("Смена продолжена")
            self._update_buttons_state(); self.log(f"Смена продолжена (shift_id={sid})")
            self.start_shift_button.config(state="normal"); self.continue_shift_button.config(state="disabled")
        else:
            messagebox.showwarning("Внимание", "Нет открытой смены! Начните новую.")

    def _update_buttons_state(self):
        if self.shift_started:
            self.select_file_button.config(state="normal")
            self.load_file_button.config(state="normal")
            self.load_from_db_button.config(state="normal")  # <<< добавили
            self.collect_button.config(state="normal" if self.collector_var.get() else "disabled")
        else:
            self.select_file_button.config(state="disabled")
            self.load_file_button.config(state="disabled")
            self.load_from_db_button.config(state="disabled")  # <<< добавили
            self.collect_button.config(state="disabled")

    def force_load_task(self):
        self.articles_data, self.remaining_copies = self.task_srv.load_task("")
        self._rebuild_assembly_table(); self._update_task_info()
        self.update_article_lists()
        self.log("Задание успешно обновлено из БД!"); return True

    def _update_task_info(self):
        total_articles = len(self.articles_data)
        remaining_total = self.task_srv.remaining_total(self.articles_data, self.remaining_copies)
        self.task_info_var.set(f"Загружено артикулов: {total_articles}, Осталось копий: {remaining_total} (БД)")

    # ------------- Истории/логи/закрытие -------------
    def _ask_password(self) -> bool:
        pwd = simpledialog.askstring("Пароль отмены", "Введите пароль:", show="*", parent=self.root)
        return pwd == self.cancel_password

    def log(self, msg: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {msg}\n"
        if hasattr(self, "log_text"):
            self.log_text.insert("end", line); self.log_text.see("end")
        print(line, end="")

    def clear_log(self):
        self.log_text.delete("1.0", "end")
        self.log("Лог очищен")

    def save_log_to_file(self):
        p = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text", "*.txt"), ("All files", "*.*")], title="Сохранить лог")
        if p:
            with open(p, "w", encoding="utf-8") as f:
                f.write(self.log_text.get("1.0", "end"))
            self.log(f"Лог сохранен: {p}")
            messagebox.showinfo("Успех", f"Лог сохранен: {p}")

    def on_closing(self):
        try:
            path = self.task_srv.export_unsaved_kits(self.auto_save_dir.get(), self.articles_data, self.remaining_copies, auto_save=True)
            if path:
                self.log(f"Автосохранены несобранные комплекты: {path}")
            self.save_settings()
        finally:
            self.root.destroy()

# Запуск
def run_app():
    root = tk.Tk()
    root.withdraw()  # скрываем основное окно до выбора

    # допустим, у нас список сборщиков в настройках
    collectors_list = ["Иванов", "Петров", "Сидоров"]

    selected_collector = ask_collector(collectors_list)
    if not selected_collector:
        root.destroy()
        return

    root.deiconify()  # показываем основное окно
    app = PrintApp(root)
    app.collector_var.set(selected_collector)  # сразу заполняем выбранным
    root.mainloop()
