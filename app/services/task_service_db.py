from typing import List, Dict, Tuple
import csv, os
from datetime import datetime
from app.services.repositories import TaskRepository

class TaskServiceDB:
    """Хранение задания в PostgreSQL, экспорт в CSV по требованию."""

    def __init__(self):
        self.repo = TaskRepository()

    def merge_articles(self, existing: List[Dict[str,int]], new_items: List[Dict[str,int]], remaining: Dict[str,int]) -> Tuple[List[Dict[str,int]], Dict[str,int], int, int]:
        return self.repo.merge_articles(new_items)

    def save_task(self, task_folder_path: str, articles: List[Dict[str,int]], remaining: Dict[str,int]) -> str:
        # БД — источник истины; ничего сохранять не требуется.
        return ""

    def load_task(self, _task_folder_path: str = "") -> Tuple[List[Dict[str,int]], Dict[str,int]]:
        return self.repo.get_task()

    def export_unsaved_kits(self, save_dir: str, articles: List[Dict[str,int]], remaining: Dict[str,int], auto_save: bool = True) -> str:
        os.makedirs(save_dir, exist_ok=True)
        arts, rem = self.repo.get_task()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(save_dir, f"несобранные_комплекты_{ts}.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Артикул", "Количество"])
            for row in arts:
                code = row["article"]; left = int(rem.get(code, row["copies"]))
                if left > 0:
                    w.writerow([code, left])
        return path

    def remaining_total(self, articles: List[Dict[str,int]], remaining: Dict[str,int]) -> int:
        return self.repo.remaining_total()

    # доп. методы
    def dec_remaining(self, article: str, by: int = 1) -> int:
        return self.repo.dec_remaining(article, by)

    def inc_remaining(self, article: str, by: int = 1) -> int:
        return self.repo.inc_remaining(article, by)

    def start_new_shift(self) -> int:
        return self.repo.start_new_shift()

    def continue_open_shift(self) -> int | None:
        return self.repo.continue_open_shift()

    def pick_random_available_and_decrement(self):
        return self.repo.pick_random_available_and_decrement()

    # импорт/экспорт задания
    def import_task_rows(self, rows: list[dict], mode: str = "merge") -> None:
        self.repo.import_task_rows(rows, mode)

    def export_task_to_csv(self, file_path: str) -> str:
        return self.repo.export_task_to_csv(file_path)

    def pick_next_available_and_decrement(self, order: str = "fifo"):
        return self.repo.pick_next_available_and_decrement(order)
