import os
import subprocess
from typing import List, Optional

class PrinterService:
    """Обнаружение принтеров и отправка файлов в печать."""

    def detect_available_printers(self) -> List[str]:
        printers: List[str] = []
        # PowerShell
        try:
            result = subprocess.run(
                ['powershell', '-Command', 'Get-Printer | Select-Object Name | Format-Table -HideTableHeaders'],
                capture_output=True, text=True, encoding='cp866'
            )
            if result.returncode == 0 and result.stdout:
                for line in result.stdout.splitlines():
                    ln = (line or '').strip()
                    if ln:
                        printers.append(ln)
                return printers
        except Exception:
            pass

        # WMI fallback
        try:
            result = subprocess.run(['wmic', 'printer', 'get', 'name'],
                                    capture_output=True, text=True, encoding='cp866')
            if result.returncode == 0 and result.stdout:
                for line in result.stdout.splitlines():
                    ln = (line or '').strip()
                    if ln and ln.lower() != 'name':
                        printers.append(ln)
        except Exception:
            pass

        return printers

    def print_file(self, file_path: str, printer_name: Optional[str] = None) -> bool:
        """Печать файла. Для PDF — пробуем Acrobat Reader, иначе системная печать."""
        try:
            if printer_name:
                if file_path.lower().endswith('.pdf'):
                    acrobat_paths = [
                        r'C:\Program Files\Adobe\Acrobat DC\Reader\AcroRd32.exe',
                        r'C:\Program Files (x86)\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe'
                    ]
                    for ap in acrobat_paths:
                        if os.path.exists(ap):
                            try:
                                subprocess.run([ap, '/t', file_path, printer_name], check=False)
                                return True
                            except Exception:
                                pass
                try:
                    os.startfile(file_path, "print")
                    return True
                except Exception:
                    try:
                        os.startfile(file_path, "print")
                        return True
                    except Exception:
                        return False
            else:
                os.startfile(file_path, "print")
                return True
        except Exception:
            return False
