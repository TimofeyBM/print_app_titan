import os
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

class LabelService:
    """Создание PNG с информацией о проверке."""
    def create_check_label(self, temp_dir: str, record: dict) -> str:
        os.makedirs(temp_dir, exist_ok=True)
        width, height = 400, 200
        img = Image.new('RGB', (width, height), 'white')
        drw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 20)
            small = ImageFont.truetype("arial.ttf", 16)
        except Exception:
            font = ImageFont.load_default()
            small = ImageFont.load_default()

        drw.rectangle([10,10,width-10,height-10], outline='black', width=2)
        drw.text((width//2, 30), "ПРОВЕРКА", fill='black', font=font, anchor='mm')
        y = 70
        drw.text((20, y), f"Артикул: {record['article']}", fill='black', font=font); y += 40
        drw.text((20, y), f"Проверяющий: {record['inspector']}", fill='black', font=font); y += 40
        drw.text((20, y), f"Дата/время: {record['datetime']}", fill='black', font=small)

        filename = f"check_{record['article']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        path = os.path.join(temp_dir, filename)
        img.save(path, 'PNG')
        return path
