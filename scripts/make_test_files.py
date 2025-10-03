import os

BASE_DIR = r"C:\Users\borod_fu6d0w3\PycharmProjects\PythonProject3"  # поменяй на свою тестовую папку

ARTICLES = {
    "A001": ["label1.txt", "card1.txt", "tag1.btw"],   # есть .btw для проверки
    "A002": ["label2.txt"],
    "A003": ["doc.txt"],
}

CONTENT = "Это тестовый контент файла для эмуляции печати.\n"

def main():
    os.makedirs(BASE_DIR, exist_ok=True)
    for art, files in ARTICLES.items():
        d = os.path.join(BASE_DIR, art)
        os.makedirs(d, exist_ok=True)
        for fn in files:
            with open(os.path.join(d, fn), "w", encoding="utf-8") as f:
                f.write(CONTENT)
    print(f"Готово: {BASE_DIR}")

if __name__ == "__main__":
    main()
