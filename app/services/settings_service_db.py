from typing import Dict, Any
from app.services.repositories import SettingsRepository
from app.core.constants import SUPPORTED_PRINTER_EXTS, DEFAULT_CANCEL_PASSWORD

class SettingsServiceDB:
    def __init__(self):
        self.repo = SettingsRepository()

    def load(self) -> Dict[str, Any]:
        data = self.repo.load()
        data["printer_settings"] = {ext: data["printer_settings"].get(ext, "") for ext in SUPPORTED_PRINTER_EXTS}
        data["collectors_list"] = list(data.get("collectors_list", []))
        data["inspectors_list"] = list(data.get("inspectors_list", []))
        data["cancel_password"] = data.get("cancel_password") or DEFAULT_CANCEL_PASSWORD
        return data

    def save(self, data: Dict[str, Any]) -> None:
        self.repo.save(data)
