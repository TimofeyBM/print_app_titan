# app/services/settings_service_db.py
import os
import platform
from datetime import datetime
from typing import Any, Dict
from sqlalchemy import select
from app.db.session import session_scope
from app.db.models import Settings  # твоя модель settings
from app.core.constants import SUPPORTED_PRINTER_EXTS, DEFAULT_CANCEL_PASSWORD

def _hostname() -> str:
    return os.environ.get("COMPUTERNAME") or platform.node()

def _default_settings() -> Dict[str, Any]:
    return {
        "base_dir": os.path.join("C:", "Путь", "К", "Папкам", "Товаров"),
        "auto_save_dir": os.getcwd(),
        "temp_save_dir": os.getcwd(),
        "printer_settings": {ext: "" for ext in SUPPORTED_PRINTER_EXTS},
        "collectors_list": [],
        "inspectors_list": [],
        "cancel_password": DEFAULT_CANCEL_PASSWORD,
    }

class SettingsServiceDB:
    def load_for_computer(self, computer_name: str | None = None) -> Dict[str, Any]:
        comp = computer_name or _hostname()
        with session_scope() as s:
            row = s.execute(select(Settings).where(Settings.computer_name == comp)).scalar_one_or_none()
            if not row:
                # создаём записи с дефолтами
                defaults = _default_settings()
                row = Settings(
                    computer_name=comp,
                    base_dir=defaults["base_dir"],
                    auto_save_dir=defaults["auto_save_dir"],
                    temp_save_dir=defaults["temp_save_dir"],
                    printer_settings=defaults["printer_settings"],
                    collectors_list=defaults["collectors_list"],
                    inspectors_list=defaults["inspectors_list"],
                    cancel_password=defaults["cancel_password"],
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
                s.add(row)
                s.flush()
            return {
                "computer_name": row.computer_name,
                "base_dir": row.base_dir,
                "auto_save_dir": row.auto_save_dir,
                "temp_save_dir": row.temp_save_dir,
                "printer_settings": row.printer_settings or {ext: "" for ext in SUPPORTED_PRINTER_EXTS},
                "collectors_list": row.collectors_list or [],
                "inspectors_list": row.inspectors_list or [],
                "cancel_password": row.cancel_password or DEFAULT_CANCEL_PASSWORD,
            }

    def save_for_computer(self, data: Dict[str, Any], computer_name: str | None = None) -> None:
        comp = computer_name or _hostname()
        with session_scope() as s:
            row = s.execute(select(Settings).where(Settings.computer_name == comp)).scalar_one_or_none()
            if not row:
                row = Settings(computer_name=comp, created_at=datetime.utcnow())
                s.add(row)
                s.flush()
            # минимальная валидация/заполнение
            for key in ["base_dir", "auto_save_dir", "temp_save_dir", "printer_settings",
                        "collectors_list", "inspectors_list", "cancel_password"]:
                if key in data:
                    setattr(row, key, data[key])
            row.updated_at = datetime.utcnow()
