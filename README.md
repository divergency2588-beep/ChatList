# ChatList

Python-приложение на PyQt6: один промт отправляется в несколько нейросетей, ответы сравниваются во временной таблице. Отмеченные строки сохраняются в SQLite.

Спецификация: [PROJECT.md](PROJECT.md).

## Возможности

- Ввод нового промта или выбор сохранённого
- Отправка в активные модели (OpenAI, DeepSeek, Groq и другие OpenAI-совместимые API)
- Временная таблица результатов с чекбоксами
- Сохранение выбранных ответов в постоянную БД
- Поиск и сортировка в таблицах
- Экспорт в Markdown и JSON

API-ключи хранятся только в `.env`. В таблице моделей указывается имя переменной (`api-id`), а не сам ключ.

## Установка и запуск

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
python main.py
```

В `.env` заполните ключи, затем на вкладке **Модели** включите нужные сети.

## Сборка exe

```powershell
pip install pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name ChatList main.py
.\dist\ChatList.exe
```
