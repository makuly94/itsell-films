#!/usr/bin/env python3
"""
Скачивает фид поставщика (ITsell Опт, формат YML для Kasta),
добавляет наценку к ценам и сохраняет результат в public/feed.xml.

Ссылка на исходный фид берётся из переменной окружения SOURCE_URL
(в GitHub это секрет, чтобы ссылка не светилась в публичном репозитории).

Локальная проверка на файле:
    python markup_feed.py source.xml
"""
import os
import re
import sys
import time

import requests

# ---------------- НАСТРОЙКИ ----------------
MARKUP = 1.15              # наценка +15%
OUT_DIR = "public"
OUT_FILE = "feed.xml"
MIN_OFFERS = int(os.environ.get("MIN_OFFERS", "1000"))   # защита: если товаров меньше — не публикуем
# -------------------------------------------

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/xml,text/xml,*/*",
}


def load_source() -> bytes:
    if len(sys.argv) > 1:
        with open(sys.argv[1], "rb") as f:
            return f.read()
    url = os.environ.get("SOURCE_URL", "").strip()
    if not url:
        sys.exit("Не задана переменная SOURCE_URL (ссылка на исходный фид).")
    for attempt in range(1, 4):
        try:
            r = requests.get(url, headers=HEADERS, timeout=300)
            r.raise_for_status()
            return r.content
        except Exception as e:  # noqa: BLE001
            print(f"Попытка {attempt}/3 не удалась: {type(e).__name__}: {e}")
            time.sleep(10 * attempt)
    sys.exit("Не удалось скачать исходный фид.")


def main():
    data = load_source()
    head = data[:300].lstrip()
    if not head.startswith(b"<?xml"):
        sys.exit("Ответ не похож на XML (возможно, блокировка или страница ошибки).")

    stats = {"changed": 0, "zero": 0}

    def bump(m):
        attrs, num = m.group(1), m.group(2)
        old = float(num)
        if old == 0:
            stats["zero"] += 1
            return m.group(0)
        stats["changed"] += 1
        new = int(old * MARKUP + 0.5)      # округление до целого
        return b"<price" + attrs + b">" + str(new).encode() + b"</price>"

    # меняем <price>число</price> (в т.ч. <price name="price">…), остальной XML не трогаем
    data = re.sub(rb"<price((?:\s[^>]*)?)>(\d+(?:\.\d+)?)</price>", bump, data)

    if stats["changed"] == 0:
        sys.exit("Ни одна цена не изменена — формат фида неожиданный, публикация отменена.")

    # у некоторых товаров поставщик отдаёт пустой id и vendorCode —
    # подставляем номер товара из ссылки (…/1006210)
    def fix_empty_id(m):
        attrs, body = m.group(1), m.group(2)
        u = re.search(rb"<url>[^<]*?/(\d+)</url>", body)
        if not u:
            return m.group(0)
        pid = u.group(1)
        stats["ids"] += 1
        body = body.replace(b"<vendorCode/>", b"<vendorCode>" + pid + b"</vendorCode>", 1)
        return b'<offer id="' + pid + b'"' + attrs + b">" + body + b"</offer>"

    stats["ids"] = 0
    data = re.sub(rb'<offer id=""([^>]*)>(.*?)</offer>', fix_empty_id, data, flags=re.S)

    offers = data.count(b"<offer ")
    if offers < MIN_OFFERS:
        sys.exit(f"Подозрительно мало товаров ({offers}) — публикация отменена.")

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, OUT_FILE)
    with open(path, "wb") as f:
        f.write(data)

    print(f"Товаров: {offers}; цен с наценкой: {stats['changed']}; "
          f"цен 0 (не менялись): {stats['zero']}; пустых id заполнено: {stats['ids']}; файл: {path} "
          f"({len(data) / 1024 / 1024:.1f} МБ)")


if __name__ == "__main__":
    main()
