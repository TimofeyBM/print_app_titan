"""
Одноразовая миграция:
- читает print_app_settings.json, collector_data.csv, check_history.csv, задание_на_сборку.csv (если есть)
- создаёт открытую смену и заливает данные в БД

Запуск: python scripts/migrate_from_csv_to_pg.py
"""

import os, csv, json
from datetime import datetime

from app.db.init_db import init_db
from app.db.database import session_scope
from app.db.models import Setting, Shift, Article, TaskItem, CollectorHistory, CheckHistory
from app.core.constants import DEFAULT_CANCEL_PASSWORD, SUPPORTED_PRINTER_EXTS

APP_DIR = os.getcwd()
SETTINGS_JSON = os.path.join(APP_DIR, "print_app_settings.json")
COLLECTOR_FILE = os.path.join(APP_DIR, "collector_data.csv")
CHECK_FILE = os.path.join(APP_DIR, "check_history.csv")
TASK_FILE = os.path.join(APP_DIR, "задание_на_сборку.csv")

def get_or_create_article(session, code: str) -> Article:
    a = session.query(Article).filter_by(code=code).one_or_none()
    if not a:
        a = Article(code=code); session.add(a); session.flush()
    return a

def migrate():
    init_db()
    with session_scope() as s:
        # settings
        st = s.get(Setting, 1)
        if not st:
            st = Setting(id=1)
        if os.path.exists(SETTINGS_JSON):
            with open(SETTINGS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            st.base_dir = data.get("base_dir","")
            st.auto_save_dir = data.get("auto_save_dir","")
            st.temp_save_dir = data.get("temp_save_dir","")
            st.cancel_password = data.get("cancel_password", DEFAULT_CANCEL_PASSWORD) or DEFAULT_CANCEL_PASSWORD
            st.printer_settings = {ext: data.get("printer_settings", {}).get(ext, "") for ext in SUPPORTED_PRINTER_EXTS}
            st.collectors_list = data.get("collectors_list", [])
            st.inspectors_list = data.get("inspectors_list", [])
        s.add(st)

        # открытая смена
        sh = Shift(status="open"); s.add(sh); s.flush()

        # task
        if os.path.exists(TASK_FILE):
            with open(TASK_FILE, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f, delimiter=';')
                headers = next(reader, None)
                for row in reader:
                    if len(row) >= 2 and row[0].strip():
                        code = row[0].strip()
                        try: total = int(row[1])
                        except: total = 1
                        try: left = int(row[2]) if len(row)>=3 else total
                        except: left = total
                        art = get_or_create_article(s, code)
                        s.add(TaskItem(shift_id=sh.id, article_id=art.id, total_copies=total, remaining_copies=left))

        # collector history
        if os.path.exists(COLLECTOR_FILE):
            with open(COLLECTOR_FILE, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f, delimiter=';')
                _ = next(reader, None)
                for row in reader:
                    if len(row) >= 4 and row[0].strip():
                        code = row[0].strip()
                        art = get_or_create_article(s, code)
                        when = row[2].strip() or datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                        try: cp = int(row[3])
                        except: cp = 1
                        s.add(CollectorHistory(shift_id=sh.id, article_id=art.id, collector=row[1].strip(), occurred_at=when, copies=cp))

        # check history
        if os.path.exists(CHECK_FILE):
            with open(CHECK_FILE, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f, delimiter=';')
                _ = next(reader, None)
                for row in reader:
                    if len(row) >= 3 and row[0].strip():
                        code = row[0].strip()
                        art = get_or_create_article(s, code)
                        when = row[2].strip() or datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                        s.add(CheckHistory(shift_id=sh.id, article_id=art.id, inspector=row[1].strip(), occurred_at=when))

if __name__ == "__main__":
    migrate()
    print("Миграция завершена.")
