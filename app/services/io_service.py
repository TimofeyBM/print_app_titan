import chardet
import pandas as pd
from typing import List, Dict

class IOService:
    """Загрузка списков артикулов из Excel/CSV/TXT."""

    def detect_csv_encoding(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                raw = f.read(10000)
            result = chardet.detect(raw)
            encoding = result['encoding'] if result.get('confidence', 0) > 0.7 else 'utf-8'
            try:
                with open(file_path, 'r', encoding=encoding, errors='ignore') as f:
                    _ = f.read(100)
                return encoding
            except Exception:
                pass
        except Exception:
            pass

        for enc in ['utf-8', 'cp1251', 'windows-1251', 'iso-8859-1', 'cp866']:
            try:
                with open(file_path, 'r', encoding=enc, errors='ignore') as f:
                    _ = f.read(100)
                return enc
            except Exception:
                continue
        return 'utf-8'

    def detect_csv_delimiter(self, file_path: str, encoding: str) -> str:
        delimiters = [',', ';', '\t', '|']
        with open(file_path, 'r', encoding=encoding, newline='') as f:
            sample = [f.readline() for _ in range(5)]
        best = ','
        maxcnt = 0
        for d in delimiters:
            total = sum((ln or '').count(d) for ln in sample if ln)
            if total > maxcnt:
                maxcnt, best = total, d
        return best

    def load_excel(self, file_path: str) -> List[Dict[str, int]]:
        data: List[Dict[str, int]] = []
        df = pd.read_excel(file_path)
        article_col, copies_col = None, None
        for col in df.columns:
            cl = str(col).lower()
            if any(k in cl for k in ['артикул', 'article', 'код', 'code']):
                article_col = col
            elif any(k in cl for k in ['количество', 'кол-во', 'copies', 'count', 'quantity']):
                copies_col = col
        if article_col is None:
            article_col = df.columns[0]
        for _, row in df.iterrows():
            art = str(row[article_col]).strip()
            if not art or str(art).lower() == 'nan':
                continue
            copies = 1
            if copies_col is not None and copies_col in row and pd.notna(row[copies_col]):
                try:
                    copies = int(float(row[copies_col]))
                except Exception:
                    copies = 1
            data.append({"article": art, "copies": copies})
        return data

    def load_csv(self, file_path: str) -> List[Dict[str, int]]:
        enc = self.detect_csv_encoding(file_path)
        delim = self.detect_csv_delimiter(file_path, enc)
        with open(file_path, 'r', encoding=enc, newline='') as f:
            content = f.read().splitlines()
        if not content:
            return []
        headers = content[0].split(delim)
        article_idx, copies_idx = -1, -1
        for i, h in enumerate(headers):
            hcl = str(h).strip().lower()
            if any(k in hcl for k in ['артикул', 'article', 'код', 'code']):
                article_idx = i
            elif any(k in hcl for k in ['количество', 'кол-во', 'copies', 'count', 'quantity']):
                copies_idx = i
        if article_idx == -1:
            article_idx = 0

        data = []
        for ln in content[1:]:
            if not ln.strip():
                continue
            row = ln.split(delim)
            if len(row) <= article_idx:
                continue
            art = str(row[article_idx]).strip()
            if not art:
                continue
            copies = 1
            if copies_idx != -1 and len(row) > copies_idx:
                try:
                    copies = int(float(str(row[copies_idx]).strip()))
                except Exception:
                    copies = 1
            data.append({"article": art, "copies": copies})
        return data

    def load_text(self, file_path: str) -> List[Dict[str, int]]:
        enc = self.detect_csv_encoding(file_path)
        out: List[Dict[str, int]] = []
        with open(file_path, 'r', encoding=enc) as f:
            for line in f:
                ln = line.strip()
                if not ln or ln.startswith('#'):
                    continue
                parts = ln.split()
                if len(parts) == 1:
                    out.append({"article": parts[0], "copies": 1})
                else:
                    try:
                        copies = int(float(parts[-1]))
                        art = ' '.join(parts[:-1])
                    except Exception:
                        copies = 1
                        art = ln
                    out.append({"article": art, "copies": copies})
        return out

    def load_any(self, file_path: str) -> List[Dict[str, int]]:
        low = file_path.lower()
        if low.endswith(('.xlsx', '.xls')):
            return self.load_excel(file_path)
        elif low.endswith('.csv'):
            return self.load_csv(file_path)
        else:
            return self.load_text(file_path)
