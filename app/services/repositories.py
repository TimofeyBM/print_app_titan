from datetime import datetime
from typing import List, Dict, Tuple, Optional

from sqlalchemy import select, update, func, delete
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import NoResultFound

from app.db.database import session_scope, session_scope_serializable, advisory_xact_lock
from app.db.models import Settings, Article, Shift, TaskItem, CollectorHistory, CheckHistory
from app.core.constants import SUPPORTED_PRINTER_EXTS, DEFAULT_CANCEL_PASSWORD

# --- helpers ---
def _get_or_create_article(session, code: str) -> Article:
    a = session.execute(select(Article).where(Article.code == code)).scalar_one_or_none()
    if not a:
        a = Article(code=code); session.add(a); session.flush()
    return a

def _get_open_shift(session, create_if_absent: bool = True) -> Shift:
    sh = session.execute(select(Shift).where(Shift.status == "open").order_by(Shift.started_at.desc())).scalars().first()
    if sh is None and create_if_absent:
        sh = Shift(status="open"); session.add(sh); session.flush()
    return sh

# --- Settings ---
class SettingsRepository:
    def load(self) -> Dict:
        with session_scope() as s:
            st = s.get(Setting, 1)
            if not st:
                st = Setting(
                    id=1, base_dir="", auto_save_dir="", temp_save_dir="",
                    cancel_password=DEFAULT_CANCEL_PASSWORD,
                    printer_settings={ext: "" for ext in SUPPORTED_PRINTER_EXTS},
                    collectors_list=[], inspectors_list=[]
                )
                s.add(st); s.flush()
            return {
                "base_dir": st.base_dir,
                "auto_save_dir": st.auto_save_dir,
                "temp_save_dir": st.temp_save_dir,
                "task_folder_path": "",  # исторический атрибут, не используется
                "collectors_list": list(st.collectors_list or []),
                "inspectors_list": list(st.inspectors_list or []),
                "printer_settings": dict(st.printer_settings or {ext:"" for ext in SUPPORTED_PRINTER_EXTS}),
                "cancel_password": st.cancel_password or DEFAULT_CANCEL_PASSWORD
            }

    def save(self, data: Dict) -> None:
        with session_scope() as s:
            st = s.get(Setting, 1) or Setting(id=1)
            for k in ("base_dir","auto_save_dir","temp_save_dir","cancel_password"):
                if k in data: setattr(st, k, data[k])
            if "printer_settings" in data:
                st.printer_settings = {ext: data["printer_settings"].get(ext,"") for ext in SUPPORTED_PRINTER_EXTS}
            if "collectors_list" in data:
                st.collectors_list = list(data["collectors_list"])
            if "inspectors_list" in data:
                st.inspectors_list = list(data["inspectors_list"])
            s.add(st)

# --- Task ---
class TaskRepository:
    def start_new_shift(self, started_by_role=None, started_by_computer=None):
        with session_scope() as s:
            shift = Shift(
                status="open",
                started_at=datetime.now(),
            )
            # новые поля
            if started_by_role:
                shift.started_by_role = started_by_role
            if started_by_computer:
                shift.started_by_computer = started_by_computer

            s.add(shift)
            s.flush()
            return shift.id

    def continue_open_shift(self) -> Optional[int]:
        with session_scope() as s:
            sh = _get_open_shift(s, create_if_absent=False)
            return sh.id if sh else None

    def get_task(self, shift_id: Optional[int] = None) -> Tuple[List[Dict[str,int]], Dict[str,int]]:
        with session_scope() as s:
            sh = s.get(Shift, shift_id) if shift_id else _get_open_shift(s)
            items = s.execute(select(TaskItem).options(joinedload(TaskItem.article)).where(TaskItem.shift_id == sh.id)).scalars().all()
            articles = [{"article": it.article.code, "copies": it.total_copies} for it in items]
            remaining = {it.article.code: it.remaining_copies for it in items}
            return articles, remaining

    def merge_articles(self, new_items: List[Dict[str,int]]) -> Tuple[List[Dict[str,int]], Dict[str,int], int, int]:
        added = updated = 0
        with session_scope() as s:
            sh = _get_open_shift(s)
            for item in new_items:
                code = item["article"].strip()
                cp = int(item.get("copies", 1) or 1)
                art = _get_or_create_article(s, code)
                ti = s.execute(select(TaskItem).where(TaskItem.shift_id == sh.id, TaskItem.article_id == art.id)).scalar_one_or_none()
                if ti:
                    ti.total_copies += cp
                    ti.remaining_copies += cp
                    updated += 1
                else:
                    s.add(TaskItem(shift_id=sh.id, article_id=art.id, total_copies=cp, remaining_copies=cp))
                    added += 1
            s.flush()
            items = s.execute(select(TaskItem).options(joinedload(TaskItem.article)).where(TaskItem.shift_id == sh.id)).scalars().all()
            articles = [{"article": it.article.code, "copies": it.total_copies} for it in items]
            remaining = {it.article.code: it.remaining_copies for it in items}
            return articles, remaining, added, updated

    def dec_remaining(self, article_code: str, by: int = 1) -> int:
        with session_scope() as s:
            sh = _get_open_shift(s)
            art = _get_or_create_article(s, article_code)
            ti = s.execute(
                select(TaskItem).where(TaskItem.shift_id == sh.id, TaskItem.article_id == art.id).with_for_update()
            ).scalar_one_or_none()
            if not ti: raise NoResultFound(f"TaskItem not found for {article_code}")
            if by > ti.remaining_copies:
                by = ti.remaining_copies
            ti.remaining_copies -= by
            s.add(ti); s.flush()
            return ti.remaining_copies

    def inc_remaining(self, article_code: str, by: int = 1) -> int:
        with session_scope() as s:
            sh = _get_open_shift(s)
            art = _get_or_create_article(s, article_code)
            ti = s.execute(
                select(TaskItem).where(TaskItem.shift_id == sh.id, TaskItem.article_id == art.id).with_for_update()
            ).scalar_one_or_none()
            if not ti:
                ti = TaskItem(shift_id=sh.id, article_id=art.id, total_copies=by, remaining_copies=by)
            else:
                ti.remaining_copies += by
                if ti.remaining_copies > ti.total_copies:
                    ti.total_copies = ti.remaining_copies
            s.add(ti); s.flush()
            return ti.remaining_copies

    def remaining_total(self) -> int:
        with session_scope() as s:
            sh = _get_open_shift(s)
            tot = s.execute(select(func.coalesce(func.sum(TaskItem.remaining_copies), 0)).where(TaskItem.shift_id == sh.id)).scalar_one()
            return int(tot)

    def pick_random_available_and_decrement(self) -> tuple[str, int] | None:
        with session_scope() as s:
            sh = _get_open_shift(s)
            if not sh:
                return None
            stmt = (
                select(TaskItem)
                .where(TaskItem.shift_id == sh.id, TaskItem.remaining_copies > 0)
                .order_by(func.random())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            ti = s.execute(stmt).scalar_one_or_none()
            if not ti:
                return None
            ti.remaining_copies -= 1
            code = s.get(Article, ti.article_id).code
            left = ti.remaining_copies
            s.add(ti); s.flush()
            return code, left


    # --- импорт/экспорт задания ---
    def import_task_rows(self, rows: list[dict], mode: str = "merge") -> None:
        """
        rows: [{article: str, total: int, remaining: Optional[int]}]
        mode="merge"  -> += total/remaining по каждой позиции
        mode="replace"-> удалить текущее задание и загрузить новое
        """
        mode = (mode or "merge").lower()
        if mode not in ("merge", "replace"):
            raise ValueError("mode must be 'merge' or 'replace'")

        with session_scope_serializable() as s:
            sh = _get_open_shift(s)
            advisory_xact_lock(s, sh.id)  # блокируем смену на время импорта

            if mode == "replace":
                s.execute(delete(TaskItem).where(TaskItem.shift_id == sh.id))

            for r in rows:
                code = str(r["article"]).strip()
                if not code:
                    continue
                total = int(r.get("total") or r.get("copies") or 1)
                remaining = r.get("remaining")
                remaining = total if remaining is None else int(remaining)

                art = _get_or_create_article(s, code)
                ti = s.execute(
                    select(TaskItem).where(TaskItem.shift_id == sh.id, TaskItem.article_id == art.id).with_for_update()
                ).scalar_one_or_none()

                if ti:
                    ti.total_copies += total
                    ti.remaining_copies += remaining
                else:
                    s.add(TaskItem(shift_id=sh.id, article_id=art.id, total_copies=total, remaining_copies=remaining))

    def export_task_to_csv(self, file_path: str, shift_id: int | None = None) -> str:
        import csv, os
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        with session_scope() as s, open(file_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=';')
            w.writerow(["Артикул", "Количество", "Осталось"])
            sh = s.get(Shift, shift_id) if shift_id else _get_open_shift(s)
            items = s.execute(
                select(TaskItem).options(joinedload(TaskItem.article)).where(TaskItem.shift_id == sh.id)
            ).scalars().all()
            for it in items:
                w.writerow([it.article.code, it.total_copies, it.remaining_copies])
        return file_path

# --- History ---
class HistoryRepository:
    def add_collect(self, article_code: str, collector: str, copies: int = 1, at: Optional[datetime] = None) -> None:
        with session_scope() as s:
            sh = _get_open_shift(s)
            art = _get_or_create_article(s, article_code)
            rec = CollectorHistory(shift_id=sh.id, article_id=art.id, collector=collector,
                                   occurred_at=at or datetime.utcnow(), copies=copies)
            s.add(rec)

    def get_collect(self) -> List[Dict]:
        with session_scope() as s:
            sh = _get_open_shift(s)
            rows = s.execute(
                select(CollectorHistory, Article.code)
                .join(Article, CollectorHistory.article_id == Article.id, isouter=True)
                .where(CollectorHistory.shift_id == sh.id)
                .order_by(CollectorHistory.id.asc())
            ).all()
            out = []
            for rec, code in rows:
                out.append({"article": code or "", "collector": rec.collector,
                            "datetime": rec.occurred_at.strftime("%Y-%m-%d %H:%M:%S"), "copies": rec.copies})
            return out

    def cancel_last_collect(self) -> Optional[Dict]:
        with session_scope() as s:
            sh = _get_open_shift(s)
            rec = s.execute(select(CollectorHistory).where(CollectorHistory.shift_id == sh.id)
                            .order_by(CollectorHistory.id.desc()).limit(1)).scalar_one_or_none()
            if not rec: return None
            code = s.get(Article, rec.article_id).code if rec.article_id else ""
            s.delete(rec); s.flush()
            return {"article": code, "collector": rec.collector,
                    "datetime": rec.occurred_at.strftime("%Y-%m-%d %H:%M:%S"), "copies": rec.copies}

    def add_check(self, article_code: str, inspector: str, at: Optional[datetime] = None) -> None:
        with session_scope() as s:
            sh = _get_open_shift(s)
            art = _get_or_create_article(s, article_code)
            rec = CheckHistory(shift_id=sh.id, article_id=art.id, inspector=inspector,
                               occurred_at=at or datetime.utcnow())
            s.add(rec)

    def get_check(self) -> List[Dict]:
        with session_scope() as s:
            sh = _get_open_shift(s)
            rows = s.execute(
                select(CheckHistory, Article.code)
                .join(Article, CheckHistory.article_id == Article.id, isouter=True)
                .where(CheckHistory.shift_id == sh.id)
                .order_by(CheckHistory.id.asc())
            ).all()
            return [{"article": code or "", "inspector": rec.inspector,
                     "datetime": rec.occurred_at.strftime("%Y-%m-%d %H:%M:%S")} for rec, code in rows]

    def cancel_last_check(self) -> Optional[Dict]:
        with session_scope() as s:
            sh = _get_open_shift(s)
            rec = s.execute(select(CheckHistory).where(CheckHistory.shift_id == sh.id)
                            .order_by(CheckHistory.id.desc()).limit(1)).scalar_one_or_none()
            if not rec: return None
            code = s.get(Article, rec.article_id).code if rec.article_id else ""
            s.delete(rec); s.flush()
            return {"article": code, "inspector": rec.inspector,
                    "datetime": rec.occurred_at.strftime("%Y-%m-%d %H:%M:%S")}

    # --- импорт/экспорт историй ---
    def import_collector_rows(self, rows: list[dict], apply_to_remaining: bool = False) -> None:
        with session_scope_serializable() as s:
            sh = _get_open_shift(s)
            advisory_xact_lock(s, sh.id)
            for r in rows:
                code = str(r.get("article","")).strip()
                if not code: continue
                art = _get_or_create_article(s, code)
                copies = int(r.get("copies", 1) or 1)
                when = r.get("datetime")
                s.add(CollectorHistory(shift_id=sh.id, article_id=art.id,
                                       collector=r.get("collector",""), occurred_at=when, copies=copies))
                if apply_to_remaining:
                    ti = s.execute(select(TaskItem).where(TaskItem.shift_id == sh.id, TaskItem.article_id == art.id)
                                   .with_for_update()).scalar_one_or_none()
                    if ti:
                        ti.remaining_copies = max(0, ti.remaining_copies - copies)
                        s.add(ti)

    def export_collector_to_csv(self, file_path: str, shift_id: int | None = None, date_from=None, date_to=None) -> str:
        import csv, os
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        with session_scope() as s, open(file_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=';')
            w.writerow(["Артикул", "Сборщик", "Дата и время", "Количество"])
            sh = s.get(Shift, shift_id) if shift_id else _get_open_shift(s)
            stmt = (select(CollectorHistory, Article.code)
                    .join(Article, CollectorHistory.article_id == Article.id, isouter=True)
                    .where(CollectorHistory.shift_id == sh.id)
                    .order_by(CollectorHistory.id.asc()))
            if date_from: stmt = stmt.where(CollectorHistory.occurred_at >= date_from)
            if date_to:   stmt = stmt.where(CollectorHistory.occurred_at < date_to)
            for rec, code in s.execute(stmt).all():
                w.writerow([code or "", rec.collector, rec.occurred_at.strftime("%Y-%m-%d %H:%M:%S"), rec.copies])
        return file_path

    def import_check_rows(self, rows: list[dict]) -> None:
        with session_scope_serializable() as s:
            sh = _get_open_shift(s)
            advisory_xact_lock(s, sh.id)
            for r in rows:
                code = str(r.get("article","")).strip()
                if not code: continue
                art = _get_or_create_article(s, code)
                when = r.get("datetime")
                s.add(CheckHistory(shift_id=sh.id, article_id=art.id,
                                   inspector=r.get("inspector",""), occurred_at=when))

    def export_check_to_csv(self, file_path: str, shift_id: int | None = None, date_from=None, date_to=None) -> str:
        import csv, os
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        with session_scope() as s, open(file_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=';')
            w.writerow(["Артикул", "Проверяющий", "Дата и время"])
            sh = s.get(Shift, shift_id) if shift_id else _get_open_shift(s)
            stmt = (select(CheckHistory, Article.code)
                    .join(Article, CheckHistory.article_id == Article.id, isouter=True)
                    .where(CheckHistory.shift_id == sh.id)
                    .order_by(CheckHistory.id.asc()))
            if date_from: stmt = stmt.where(CheckHistory.occurred_at >= date_from)
            if date_to:   stmt = stmt.where(CheckHistory.occurred_at < date_to)
            for rec, code in s.execute(stmt).all():
                w.writerow([code or "", rec.inspector, rec.occurred_at.strftime("%Y-%m-%d %H:%M:%S")])
        return file_path
