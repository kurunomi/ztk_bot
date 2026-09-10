# 🎓 ZTK Schedule Bot

Telegram бот для перегляду розкладу занять Житомирського технічного коледжу.

## Можливості

- 📅 Показує розклад **на завтра** для будь-якої групи
- 🔄 Автоматично підтягує **заміни** з PDF-файлу на сайті
- 📚 **Автовизначення семестру** (1 сем: вересень–січень, 2 сем: лютий–серпень)
- 🏫 Підтримка **1–4 курсів**, всіх груп
- 🗓 Відображає повний список пар з часом, викладачем та аудиторією

---

## Встановлення (Arch Linux)

### 1. Встановити системні залежності

```bash
sudo pacman -S python python-pip git poppler
```

> `poppler` потрібен для утиліт `pdftotext` / `pdfinfo`, які використовує парсер.

### 2. Розпакувати проєкт

```bash
unzip ztk_bot.zip
cd ztk_bot
```

### 3. Створити віртуальне середовище

На Arch **не можна** робити `pip install` глобально без прапорця — використовуй venv:

```bash
python -m venv .venv
source .venv/bin/activate
```

Після активації в терміналі з'явиться `(.venv)`. Для виходу з venv — `deactivate`.

### 4. Встановити Python-залежності

```bash
pip install -r requirements.txt
```

### 5. Створити Telegram бота

1. Відкрий [@BotFather](https://t.me/BotFather) в Telegram
2. Надішли `/newbot` та дотримуйся інструкцій
3. Скопіюй **токен** (виглядає як `123456789:ABCdef...`)

### 6. Налаштувати токен

```bash
cp .env.example .env
nano .env
```

Встав свій токен:
```
BOT_TOKEN=123456789:ABCdef...
```

### 7. Запустити бота

```bash
source .venv/bin/activate   # якщо venv ще не активований
python bot.py
```

---

## Дебаг / тестування парсера

Перед запуском бота перевір, що парсер правильно читає PDF:

```bash
source .venv/bin/activate

# Показати розклад для групи КН-11 на завтра
python debug_parser.py --course 1 --group КН-11

# Вказати конкретну дату
python debug_parser.py --course 2 --group ІТ-21 --date 2026-06-04

# Вивести сирий текст PDF (корисно якщо парсер нічого не знаходить)
python debug_parser.py --course 1 --group КН-11 --dump
```

### Якщо парсер нічого не знаходить

1. Запусти `--dump` щоб побачити сирий текст PDF
2. Подивись як виглядають назви груп у файлі (можуть бути `КН11`, `КН 11`, `КН-11`)
3. Якщо потрібно — виправ список груп у `config.py` (GROUPS)
4. Якщо структура таблиці відрізняється — відкрий `schedule_parser.py` і адаптуй `_parse_table_for_group`

---

## Структура проєкту

```
ztk_bot/
├── bot.py              # Головний файл бота (aiogram 3)
├── config.py           # Налаштування: токен, URL, список груп
├── states.py           # FSM стани
├── keyboards.py        # Inline-клавіатури
├── schedule_parser.py  # Завантаження і парсинг PDF
├── utils.py            # Допоміжні функції, форматування
├── debug_parser.py     # Скрипт для тестування парсера
├── requirements.txt
└── .env                # Твій токен (не комітити в git!)
```

---

## Оновлення списку груп

Якщо в коледжі з'являються нові групи або змінюються назви — відкрий `config.py` і відредагуй словник `GROUPS`:

```python
GROUPS = {
    1: ["КН-11", "КН-12", "ІТ-11", ...],
    2: [...],
    ...
}
```

---

## Часи пар (за замовчуванням)

| Пара | Час |
|------|-----|
| 1    | 08:00–09:35 |
| 2    | 09:50–11:25 |
| 3    | 11:40–13:15 |
| 4    | 14:00–15:35 |
| 5    | 15:50–17:25 |
| 6    | 17:40–19:15 |

Якщо розклад дзвінків відрізняється — змін `LESSON_TIMES` у `schedule_parser.py`.

---

## Автозапуск через systemd

Щоб бот стартував автоматично разом із системою:

```bash
sudo nano /etc/systemd/system/ztk-bot.service
```

```ini
[Unit]
Description=ZTK Schedule Bot
After=network.target

[Service]
User=your_user
WorkingDirectory=/home/your_user/ztk_bot
ExecStart=/home/your_user/ztk_bot/.venv/bin/python bot.py
Restart=on-failure
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

> Заміни `your_user` на своє ім'я користувача. Перевір шлях командою `pwd` з папки проєкту AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA.

```bash
sudo systemctl daemon-reload
sudo systemctl enable ztk-bot
sudo systemctl start ztk-bot

# Перевірити статус / логи
sudo systemctl status ztk-bot
journalctl -u ztk-bot -f
```