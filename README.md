# ChatList

Python-приложение на PyQt6: один промт отправляется в несколько нейросетей, ответы сравниваются во временной таблице. Отмеченные строки сохраняются в SQLite.

Спецификация: [PROJECT.md](PROJECT.md). План: [PLAN.md](PLAN.md). Схема БД: [DATABASE.md](DATABASE.md).

## Возможности

- Ввод нового промта или выбор сохранённого
- Отправка в активные модели (OpenRouter, OpenAI, DeepSeek, Groq и другие OpenAI-совместимые API)
- Временная таблица результатов с чекбоксами
- Сохранение выбранных ответов в постоянную БД
- Поиск и сортировка в таблицах
- Экспорт в Markdown и JSON
- Журнал запросов

API-ключи хранятся в `.env` и `.env.local`. В таблице моделей указывается имя переменной (`api-id`), не сам ключ.

## Установка и запуск

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
python main.py
```

Для OpenRouter достаточно `OPENROUTER_API_KEY` в `.env` или `.env.local`. Модели OpenRouter включаются автоматически.

## Сборка exe

```powershell
pip install pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name ChatList main.py
.\dist\ChatList.exe
```

Рядом с `ChatList.exe` положите `.env` или `.env.local`.
