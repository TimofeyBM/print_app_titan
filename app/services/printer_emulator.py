import os, shutil, time
from datetime import datetime
from typing import List, Optional

class EmulatedPrinterService:
    """
    Эмулятор принтера: вместо отправки в драйвер
    копирует файл в temp_save_dir/_printed/YYYYMMDD и пишет лог.
    """
    def __init__(self, spool_root: str):
        self.spool_root = spool_root or os.getcwd()
        os.makedirs(self.spool_root, exist_ok=True)

    def detect_available_printers(self) -> List[str]:
        return ["EMULATED_PRINTER"]

    def print_file(self, file_path: str, printer_name: Optional[str] = None) -> bool:
        try:
            date_dir = datetime.now().strftime("%Y%m%d")
            outdir = os.path.join(self.spool_root, "_printed", date_dir)
            os.makedirs(outdir, exist_ok=True)

            base = os.path.basename(file_path)
            ts = datetime.now().strftime("%H%M%S_%f")
            dest = os.path.join(outdir, f"{ts}_{base}")
            shutil.copy2(file_path, dest)

            # лог печати
            log_path = os.path.join(outdir, "_print_log.csv")
            with open(log_path, "a", encoding="utf-8-sig") as logf:
                logf.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')};{printer_name or 'EMULATED_PRINTER'};{file_path};{dest}\n")

            # небольшая задержка, имитирующая работу принтера
            time.sleep(0.05)
            return True
        except Exception:
            return False
