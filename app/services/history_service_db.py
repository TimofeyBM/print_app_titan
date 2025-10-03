from typing import List, Dict
from app.services.repositories import HistoryRepository

class HistoryServiceDB:
    """Истории в PostgreSQL; имена методов сохранены для совместимости с UI."""

    def __init__(self):
        self.repo = HistoryRepository()

    # --- Collector ---
    def save_collector_data(self, path: str, data: List[Dict], append: bool = True) -> str:
        for row in data:
            self.repo.add_collect(article_code=row.get("article",""), collector=row.get("collector",""), copies=int(row.get("copies",1)))
        return path

    def load_collector_data(self, path: str) -> List[Dict]:
        return self.repo.get_collect()

    def clear_collector_file(self, path: str) -> None:
        pass

    # --- Check ---
    def save_check_history(self, path: str, data: List[Dict], append: bool = True) -> str:
        for row in data:
            self.repo.add_check(article_code=row.get("article",""), inspector=row.get("inspector",""))
        return path

    def load_check_history(self, path: str) -> List[Dict]:
        return self.repo.get_check()

    def clear_check_history_file(self, path: str) -> None:
        pass

    # Autosave/Temp — не нужно для БД
    def autosave_collector(self, auto_dir: str, data: List[Dict], use_timestamp: bool = False) -> str:
        return ""

    def autosave_checks(self, auto_dir: str, data: List[Dict], use_timestamp: bool = False) -> str:
        return ""

    def save_temp(self, temp_dir: str, collectors: List[Dict], checks: List[Dict]) -> None:
        pass

    # Cancel
    def cancel_last_collect(self) -> Dict | None:
        return self.repo.cancel_last_collect()

    def cancel_last_check(self) -> Dict | None:
        return self.repo.cancel_last_check()
