from typing import List, Dict, Optional
from datetime import datetime
import csv, os

from app.services.io_service import IOService
from app.services.repositories import TaskRepository, HistoryRepository

class ImportExportServiceDB:
    def __init__(self):
        self.io = IOService()
        self.task_repo = TaskRepository()
        self.hist_repo = HistoryRepository()

    # --- TASK ---
    def import_task_from_csv(self, file_path: str, mode: str = "merge") -> None:
        enc = self.io.detect_csv_encoding(file_path)
        delim = self.io.detect_csv_delimiter(file_path, enc)
        with open(file_path, 'r', encoding=enc, newline='') as f:
            rows = list(csv.reader(f, delimiter=delim))
        if not rows: return
        header = [h.strip().lower() for h in rows[0]]

        def find_idx(keys: list[str]) -> int | None:
            for i, h in enumerate(header):
                for k in keys:
                    if k in h:
                        return i
            return None

        idx_article = find_idx(['артикул','article','код','code']) or 0
        idx_total   = find_idx(['количество','кол-во','copies','count','quantity'])
        idx_rem     = find_idx(['осталось','remaining','left'])

        out = []
        for r in rows[1:]:
            if not r or len(r) <= idx_article: continue
            art = str(r[idx_article]).strip()
            if not art: continue
            total = 1
            if idx_total is not None and len(r) > idx_total:
                try: total = int(float(r[idx_total]))
                except: total = 1
            remaining = None
            if idx_rem is not None and len(r) > idx_rem and r[idx_rem].strip():
                try: remaining = int(float(r[idx_rem]))
                except: remaining = None
            out.append({"article": art, "total": total, "remaining": remaining})
        self.task_repo.import_task_rows(out, mode=mode)

    def export_task_to_csv(self, file_path: str) -> str:
        return self.task_repo.export_task_to_csv(file_path)

    # --- Collector history ---
    def import_collector_from_csv(self, file_path: str, apply_to_remaining: bool = False) -> None:
        enc = self.io.detect_csv_encoding(file_path)
        delim = self.io.detect_csv_delimiter(file_path, enc)
        with open(file_path, 'r', encoding=enc, newline='') as f:
            rows = list(csv.reader(f, delimiter=delim))
        if not rows: return
        header = [h.strip().lower() for h in rows[0]]
        def idx(keys):
            for i,h in enumerate(header):
                for k in keys:
                    if k in h: return i
            return None

        i_art = idx(['артикул','article','код','code']) or 0
        i_col = idx(['сборщик','collector'])
        i_dt  = idx(['дата и время','дата','date','datetime','occurred'])
        i_cp  = idx(['количество','кол-во','copies','count','quantity'])

        out = []
        for r in rows[1:]:
            if not r or len(r) <= i_art: continue
            art = str(r[i_art]).strip()
            if not art: continue
            cp = 1
            if i_cp is not None and len(r) > i_cp:
                try: cp = int(float(r[i_cp]))
                except: cp = 1
            when = r[i_dt].strip() if i_dt is not None and len(r) > i_dt and r[i_dt].strip() else None
            out.append({"article": art, "collector": (r[i_col].strip() if i_col is not None and len(r)>i_col else ""),
                        "datetime": when, "copies": cp})
        self.hist_repo.import_collector_rows(out, apply_to_remaining=apply_to_remaining)

    def export_collector_to_csv(self, file_path: str, date_from: Optional[datetime]=None, date_to: Optional[datetime]=None) -> str:
        return self.hist_repo.export_collector_to_csv(file_path, date_from=date_from, date_to=date_to)

    # --- Check history ---
    def import_check_from_csv(self, file_path: str) -> None:
        enc = self.io.detect_csv_encoding(file_path)
        delim = self.io.detect_csv_delimiter(file_path, enc)
        with open(file_path, 'r', encoding=enc, newline='') as f:
            rows = list(csv.reader(f, delimiter=delim))
        if not rows: return
        header = [h.strip().lower() for h in rows[0]]
        def idx(keys):
            for i,h in enumerate(header):
                for k in keys:
                    if k in h: return i
            return None

        i_art = idx(['артикул','article','код','code']) or 0
        i_insp = idx(['проверяющий','inspector'])
        i_dt = idx(['дата и время','дата','date','datetime','occurred'])

        out = []
        for r in rows[1:]:
            if not r or len(r) <= i_art: continue
            art = str(r[i_art]).strip()
            if not art: continue
            when = r[i_dt].strip() if i_dt is not None and len(r)>i_dt and r[i_dt].strip() else None
            out.append({"article": art, "inspector": (r[i_insp].strip() if i_insp is not None and len(r)>i_insp else ""),
                        "datetime": when})
        self.hist_repo.import_check_rows(out)

    def export_check_to_csv(self, file_path: str, date_from: Optional[datetime]=None, date_to: Optional[datetime]=None) -> str:
        return self.hist_repo.export_check_to_csv(file_path, date_from=date_from, date_to=date_to)
