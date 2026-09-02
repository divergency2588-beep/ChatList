"""ChatList: один промт → несколько нейросетей → сравнение ответов → сохранение выбранных строк в SQLite."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values
from PyQt6.QtCore import Qt, QThread
from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from db import Database, app_root, load_app_env
from models import Model, ModelService
from network import send_to_models

ROOT = app_root()
load_app_env()

STYLE = """
QMainWindow, QDialog { background: #e6edf5; }
QTabWidget::pane { border: 1px solid #9bb0c7; background: #eef3f8; top: -1px; }
QTabBar::tab {
    padding: 8px 16px;
    background: #c5d4e6;
    color: #1e293b;
    border: 1px solid #9bb0c7;
    border-bottom: none;
    margin-right: 4px;
}
QTabBar::tab:selected { background: #eef3f8; font-weight: 600; }
QPushButton {
    background: #1d4ed8;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: 600;
}
QPushButton:hover { background: #1e40af; }
QPushButton:disabled { background: #94a3b8; color: #e2e8f0; }
QPushButton#secondary {
    background: #0f766e;
    color: #ffffff;
}
QPushButton#secondary:hover { background: #0d5e58; }
QLineEdit, QPlainTextEdit, QComboBox {
    border: 1px solid #7c93ad;
    border-radius: 6px;
    padding: 6px;
    background: #fff4d6;
    color: #111827;
    selection-background-color: #f59e0b;
    selection-color: #111827;
}
QLineEdit::placeholder, QPlainTextEdit[placeholderText] {
    color: #6b7280;
}
QComboBox {
    background: #ffe8b3;
    color: #111827;
}
QComboBox QAbstractItemView {
    background: #fff4d6;
    color: #111827;
    selection-background-color: #f59e0b;
}
QPlainTextEdit#preview, QTextBrowser#preview {
    background: #dcefe4;
    color: #14532d;
    border: 1px solid #6aa084;
}
QTextBrowser#markdownView {
    background: #fffef6;
    color: #111827;
    border: 1px solid #c4b896;
    padding: 16px;
    font-size: 14px;
}
QTableWidget {
    border: 1px solid #7c93ad;
    background: #fff4d6;
    alternate-background-color: #ffe9b8;
    gridline-color: #d6c089;
    color: #111827;
    selection-background-color: #fbbf24;
    selection-color: #111827;
}
QHeaderView::section {
    background: #c5d4e6;
    color: #1e293b;
    padding: 6px;
    border: none;
    border-right: 1px solid #9bb0c7;
    border-bottom: 1px solid #9bb0c7;
    font-weight: 600;
}
QStatusBar { background: #c5d4e6; color: #1e293b; }
"""


@dataclass
class TempRow:
    model_name: str
    response_text: str
    ok: bool
    selected: bool = False
    pending: bool = False


class QueryWorker(QThread):
    def __init__(
        self,
        models: list[Model],
        prompt: str,
        timeout: float,
        temperature: float,
    ) -> None:
        super().__init__()
        self.models = models
        self.prompt = prompt
        self.timeout = timeout
        self.temperature = temperature
        self.rows: list[tuple[str, str, bool]] = []
        self.error: str | None = None

    def run(self) -> None:
        try:
            self.rows = send_to_models(
                self.models,
                self.prompt,
                timeout=self.timeout,
                temperature=self.temperature,
            )
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
            self.rows = []


MARKDOWN_CSS = """
h1 { font-size: 22pt; font-weight: 700; color: #0f172a; margin: 8px 0 12px; }
h2 { font-size: 16pt; font-weight: 700; color: #1e3a5f; margin: 14px 0 8px; }
h3 { font-size: 13pt; font-weight: 600; color: #1e3a5f; margin: 12px 0 6px; }
p, li { font-size: 12pt; line-height: 1.45; color: #111827; }
code { background-color: #efe6c9; font-family: Consolas, 'Courier New', monospace; }
pre { background-color: #efe6c9; margin: 8px 0; padding: 8px; }
blockquote { color: #334155; margin-left: 12px; }
a { color: #1d4ed8; }
"""


class MarkdownViewDialog(QDialog):
    def __init__(self, parent: QWidget | None, title: str, markdown_text: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 720)
        self.setWindowFlag(Qt.WindowType.Window, True)

        view = QTextBrowser()
        view.setObjectName("markdownView")
        view.setOpenExternalLinks(True)
        view.document().setDefaultStyleSheet(MARKDOWN_CSS)
        view.setMarkdown(markdown_text.strip() or "_Нет текста._")

        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.close)

        layout = QVBoxLayout(self)
        layout.addWidget(view)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)


class ModelDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, model: Model | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Модель" if model else "Новая модель")
        self.resize(520, 220)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("gpt-4o-mini")
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://api.openai.com/v1/chat/completions")
        self.api_id_edit = QLineEdit()
        self.api_id_edit.setPlaceholderText("OPENAI_API_KEY")
        self.active_check = QCheckBox("Активна")
        self.active_check.setChecked(True)

        if model is not None:
            self.name_edit.setText(model.name)
            self.url_edit.setText(model.api_url)
            self.api_id_edit.setText(model.api_id)
            self.active_check.setChecked(model.is_active)

        form = QFormLayout()
        form.addRow("Имя модели (model id)", self.name_edit)
        form.addRow("API URL", self.url_edit)
        form.addRow("Переменная ключа", self.api_id_edit)
        form.addRow("", self.active_check)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "API-ключ не хранится в БД. Укажите имя переменной из файла .env."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str, str, bool]:
        return (
            self.name_edit.text().strip(),
            self.url_edit.text().strip(),
            self.api_id_edit.text().strip(),
            self.active_check.isChecked(),
        )

    def accept(self) -> None:
        name, url, api_id, _ = self.values()
        if not name or not url or not api_id:
            QMessageBox.warning(self, "ChatList", "Заполните имя, URL и переменную ключа.")
            return
        super().accept()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ChatList")
        self.resize(1100, 740)

        self.db = Database()
        self.model_service = ModelService(self.db)
        self.worker: QueryWorker | None = None
        self.current_prompt_id: int | None = None
        self.current_prompt_text = ""
        self.temp_rows: list[TempRow] = []
        self._md_dialogs: list[MarkdownViewDialog] = []

        tabs = QTabWidget()
        tabs.addTab(self._build_query_tab(), "Запрос")
        tabs.addTab(self._build_prompts_tab(), "Промты")
        tabs.addTab(self._build_models_tab(), "Модели")
        tabs.addTab(self._build_results_tab(), "Результаты")
        tabs.addTab(self._build_settings_tab(), "Настройки")
        tabs.addTab(self._build_logs_tab(), "Журнал")
        self.tabs = tabs
        self.setCentralWidget(tabs)
        self.statusBar().showMessage("Готово")

        self.refresh_all()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.prompt_edit.setFocus()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.db.close()
        super().closeEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not getattr(self, "_splitter_ready", False):
            self._splitter_ready = True
            self.query_splitter.setSizes([340, 360])
            self.prompt_edit.setFocus()

    def _on_tab_changed(self, index: int) -> None:
        if index == 0:
            self.prompt_edit.setFocus()

    # --- tabs ---

    def _build_query_tab(self) -> QWidget:
        tab = QWidget()
        root = QVBoxLayout(tab)

        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setPlaceholderText("Введите промт…")
        self.prompt_edit.setMinimumHeight(140)
        self.prompt_edit.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        font = QFont(self.prompt_edit.font())
        font.setPointSize(11)
        self.prompt_edit.setFont(font)

        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("теги через запятую")
        self.prompt_combo = QComboBox()
        self.prompt_combo.currentIndexChanged.connect(self._on_prompt_combo)

        self.send_btn = QPushButton("Отправить")
        self.send_btn.clicked.connect(self.send_prompt)
        self.save_temp_btn = QPushButton("Сохранить выбранные")
        self.save_temp_btn.clicked.connect(self.save_selected)
        self.export_md_btn = QPushButton("Экспорт Markdown")
        self.export_md_btn.setObjectName("secondary")
        self.export_md_btn.clicked.connect(lambda: self.export_temp("md"))
        self.export_json_btn = QPushButton("Экспорт JSON")
        self.export_json_btn.setObjectName("secondary")
        self.export_json_btn.clicked.connect(lambda: self.export_temp("json"))
        self.open_md_btn = QPushButton("Открыть")
        self.open_md_btn.clicked.connect(self.open_temp_markdown)

        buttons = QHBoxLayout()
        buttons.addWidget(self.send_btn)
        buttons.addWidget(self.save_temp_btn)
        buttons.addWidget(self.export_md_btn)
        buttons.addWidget(self.export_json_btn)
        buttons.addWidget(self.open_md_btn)
        buttons.addStretch()

        form = QFormLayout()
        form.addRow("Сохранённый промт", self.prompt_combo)
        form.addRow("Теги", self.tags_edit)

        self.temp_table = self._make_table(["Выбрать", "Модель", "Ответ", "Статус"])
        self.temp_table.setColumnWidth(0, 80)
        self.temp_table.setColumnWidth(1, 220)
        self.temp_table.setColumnWidth(3, 90)
        self.temp_table.itemChanged.connect(self._on_temp_item_changed)

        self.preview = QTextBrowser()
        self.preview.setObjectName("preview")
        self.preview.setOpenExternalLinks(True)
        self.preview.setPlaceholderText("Ответ модели. Нажмите «Открыть», чтобы увидеть Markdown.")
        self.preview.setMinimumHeight(180)
        self.temp_table.itemSelectionChanged.connect(self._show_temp_preview)
        self.temp_table.doubleClicked.connect(self.open_temp_markdown)

        splitter = QSplitter(Qt.Orientation.Vertical)
        top = QWidget()
        top.setMinimumHeight(260)
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addWidget(QLabel("Промт — пишите запрос здесь"))
        top_layout.addWidget(self.prompt_edit, 1)
        top_layout.addLayout(form)
        top_layout.addLayout(buttons)

        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        answer_header = QHBoxLayout()
        answer_header.addWidget(QLabel("Ответ"))
        answer_header.addStretch()
        open_answer_btn = QPushButton("Открыть")
        open_answer_btn.clicked.connect(self.open_temp_markdown)
        answer_header.addWidget(open_answer_btn)

        bottom_layout.addWidget(QLabel("Временные результаты"))
        bottom_layout.addWidget(self.temp_table, 1)
        bottom_layout.addLayout(answer_header)
        bottom_layout.addWidget(self.preview, 2)

        splitter.addWidget(top)
        splitter.addWidget(bottom)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 380])
        self.query_splitter = splitter
        root.addWidget(splitter)
        return tab

    def _build_prompts_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.prompts_search = QLineEdit()
        self.prompts_search.setPlaceholderText("Поиск по промтам…")
        self.prompts_search.textChanged.connect(
            lambda text: self._filter_table(self.prompts_table, text)
        )
        self.prompts_table = self._make_table(["ID", "Дата", "Промт", "Теги"])
        self.prompts_table.doubleClicked.connect(self.load_prompt_from_table)

        load_btn = QPushButton("Подставить в запрос")
        load_btn.clicked.connect(self.load_prompt_from_table)
        del_btn = QPushButton("Удалить")
        del_btn.setObjectName("secondary")
        del_btn.clicked.connect(self.delete_prompt)

        row = QHBoxLayout()
        row.addWidget(load_btn)
        row.addWidget(del_btn)
        row.addStretch()

        layout.addWidget(self.prompts_search)
        layout.addWidget(self.prompts_table)
        layout.addLayout(row)
        return tab

    def _build_models_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.models_search = QLineEdit()
        self.models_search.setPlaceholderText("Поиск по моделям…")
        self.models_search.textChanged.connect(
            lambda text: self._filter_table(self.models_table, text)
        )
        self.models_table = self._make_table(
            ["ID", "Имя", "API URL", "Переменная ключа", "Активна"]
        )

        add_btn = QPushButton("Добавить")
        add_btn.clicked.connect(self.add_model)
        edit_btn = QPushButton("Изменить")
        edit_btn.setObjectName("secondary")
        edit_btn.clicked.connect(self.edit_model)
        toggle_btn = QPushButton("Вкл/Выкл")
        toggle_btn.setObjectName("secondary")
        toggle_btn.clicked.connect(self.toggle_model)
        del_btn = QPushButton("Удалить")
        del_btn.setObjectName("secondary")
        del_btn.clicked.connect(self.delete_model)

        row = QHBoxLayout()
        row.addWidget(add_btn)
        row.addWidget(edit_btn)
        row.addWidget(toggle_btn)
        row.addWidget(del_btn)
        row.addStretch()

        layout.addWidget(self.models_search)
        layout.addWidget(self.models_table)
        layout.addLayout(row)
        return tab

    def _build_results_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.results_search = QLineEdit()
        self.results_search.setPlaceholderText("Поиск по сохранённым результатам…")
        self.results_search.textChanged.connect(
            lambda text: self._filter_table(self.results_table, text)
        )
        self.results_table = self._make_table(
            ["ID", "Дата", "Модель", "Промт", "Ответ"]
        )
        self.results_preview = QPlainTextEdit()
        self.results_preview.setReadOnly(True)
        self.results_preview.setMinimumHeight(180)
        self.results_table.itemSelectionChanged.connect(self._show_result_preview)
        self.results_table.doubleClicked.connect(self.open_saved_markdown)

        export_md = QPushButton("Экспорт Markdown")
        export_md.clicked.connect(lambda: self.export_saved("md"))
        export_json = QPushButton("Экспорт JSON")
        export_json.setObjectName("secondary")
        export_json.clicked.connect(lambda: self.export_saved("json"))
        open_btn = QPushButton("Открыть")
        open_btn.setObjectName("secondary")
        open_btn.clicked.connect(self.open_saved_markdown)
        del_btn = QPushButton("Удалить")
        del_btn.setObjectName("secondary")
        del_btn.clicked.connect(self.delete_result)

        row = QHBoxLayout()
        row.addWidget(export_md)
        row.addWidget(export_json)
        row.addWidget(open_btn)
        row.addWidget(del_btn)
        row.addStretch()

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.results_table)
        splitter.addWidget(self.results_preview)
        splitter.setStretchFactor(0, 2)

        layout.addWidget(self.results_search)
        layout.addWidget(splitter)
        layout.addLayout(row)
        return tab

    def _build_settings_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.timeout_edit = QLineEdit()
        self.temperature_edit = QLineEdit()
        form = QFormLayout()
        form.addRow("Таймаут запроса, сек", self.timeout_edit)
        form.addRow("Temperature", self.temperature_edit)

        save_btn = QPushButton("Сохранить настройки")
        save_btn.clicked.connect(self.save_settings)

        hint = QLabel(self._env_hint_text())
        hint.setWordWrap(True)

        layout.addLayout(form)
        layout.addWidget(save_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addSpacing(12)
        layout.addWidget(hint)
        layout.addStretch()
        return tab

    def _build_logs_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.logs_search = QLineEdit()
        self.logs_search.setPlaceholderText("Поиск по журналу…")
        self.logs_search.textChanged.connect(
            lambda text: self._filter_table(self.logs_table, text)
        )
        self.logs_table = self._make_table(["ID", "Дата", "Модель", "Статус", "Сообщение"])
        clear_btn = QPushButton("Очистить журнал")
        clear_btn.setObjectName("secondary")
        clear_btn.clicked.connect(self.clear_logs)
        layout.addWidget(self.logs_search)
        layout.addWidget(self.logs_table)
        layout.addWidget(clear_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        return tab

    def _make_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSortingEnabled(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.setAlternatingRowColors(True)
        return table

    # --- data refresh ---

    def refresh_all(self) -> None:
        self.refresh_prompts()
        self.refresh_models()
        self.refresh_results()
        self.refresh_settings()
        self.refresh_logs()

    def refresh_prompts(self) -> None:
        rows = self.db.list_prompts()
        self._fill_table(
            self.prompts_table,
            [
                [str(r["id"]), r["created_at"], r["prompt"], r["tags"]]
                for r in rows
            ],
        )
        self._filter_table(self.prompts_table, self.prompts_search.text())
        self._refresh_prompt_combo()

    def refresh_models(self) -> None:
        rows = self.model_service.all()
        self._fill_table(
            self.models_table,
            [
                [
                    str(m.id),
                    m.name,
                    m.api_url,
                    m.api_id,
                    "да" if m.is_active else "нет",
                ]
                for m in rows
            ],
        )
        self._filter_table(self.models_table, self.models_search.text())

    def refresh_results(self) -> None:
        rows = self.db.list_results()
        self._fill_table(
            self.results_table,
            [
                [
                    str(r["id"]),
                    r["created_at"],
                    r["model_name"],
                    r["prompt_text"],
                    r["response_text"],
                ]
                for r in rows
            ],
        )
        self._filter_table(self.results_table, self.results_search.text())

    def refresh_settings(self) -> None:
        self.timeout_edit.setText(self.db.get_setting("request_timeout", "60"))
        self.temperature_edit.setText(self.db.get_setting("temperature", "0.7"))

    def refresh_logs(self) -> None:
        rows = self.db.list_logs()
        self._fill_table(
            self.logs_table,
            [
                [str(r["id"]), r["created_at"], r["model_name"], r["status"], r["message"]]
                for r in rows
            ],
        )
        self._filter_table(self.logs_table, self.logs_search.text())

    def _fill_table(self, table: QTableWidget, rows: list[list[str]]) -> None:
        table.setSortingEnabled(False)
        table.setRowCount(0)
        for values in rows:
            row = table.rowCount()
            table.insertRow(row)
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0 and value.isdigit():
                    item.setData(Qt.ItemDataRole.DisplayRole, int(value))
                table.setItem(row, col, item)
        table.setSortingEnabled(True)

    def _refresh_prompt_combo(self) -> None:
        self.prompt_combo.blockSignals(True)
        self.prompt_combo.clear()
        self.prompt_combo.addItem("— новый промт —", None)
        for row in self.db.list_prompts():
            preview = " ".join(str(row["prompt"]).split())[:70]
            self.prompt_combo.addItem(f"#{row['id']}  {preview}", int(row["id"]))
        self.prompt_combo.blockSignals(False)

    def _on_prompt_combo(self, index: int) -> None:
        prompt_id = self.prompt_combo.itemData(index)
        if not prompt_id:
            return
        row = self.db.get_prompt(int(prompt_id))
        if row is None:
            return
        self.prompt_edit.setPlainText(row["prompt"])
        self.tags_edit.setText(row["tags"])

    def _env_hint_text(self) -> str:
        merged: dict[str, str | None] = {}
        merged.update(dotenv_values(ROOT / ".env"))
        merged.update(dotenv_values(ROOT / ".env.local"))
        status_lines = []
        for key in sorted(k for k in merged if k):
            filled = "задан" if (merged[key] or "").strip() else "пустой"
            status_lines.append(f"{key}: {filled}")
        status = "\n".join(status_lines) if status_lines else "файлы пустые"
        return (
            f"API-ключи хранятся в:\n{ROOT / '.env'}\n{ROOT / '.env.local'}\n\n"
            f"{status}\n\n"
            "В таблице моделей указывается только имя переменной (api-id), не сам ключ."
        )

    def _filter_table(self, table: QTableWidget, text: str) -> None:
        needle = text.strip().lower()
        for row in range(table.rowCount()):
            if not needle:
                table.setRowHidden(row, False)
                continue
            parts = []
            for col in range(table.columnCount()):
                item = table.item(row, col)
                if item is not None:
                    parts.append(item.text())
            table.setRowHidden(row, needle not in " ".join(parts).lower())

    def _selected_id(self, table: QTableWidget) -> int | None:
        ids = self._selected_ids(table)
        return ids[0] if ids else None

    def _selected_ids(self, table: QTableWidget) -> list[int]:
        rows = {item.row() for item in table.selectedItems()}
        if not rows and table.currentRow() >= 0:
            rows = {table.currentRow()}
        ids: list[int] = []
        for row in sorted(rows):
            item = table.item(row, 0)
            if item is None:
                continue
            try:
                ids.append(int(item.text()))
            except ValueError:
                continue
        return ids

    # --- query flow ---

    def send_prompt(self) -> None:
        prompt = self.prompt_edit.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "ChatList", "Введите промт.")
            return

        models = self.model_service.active()
        if not models:
            QMessageBox.warning(
                self,
                "ChatList",
                "Нет активных моделей. Включите хотя бы одну на вкладке «Модели».",
            )
            return

        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "ChatList", "Дождитесь завершения текущего запроса.")
            return

        self.current_prompt_id = self.db.add_prompt(prompt, self.tags_edit.text())
        self.current_prompt_text = prompt
        self.temp_rows = [
            TempRow(model_name=item.name, response_text="", ok=False, pending=True)
            for item in models
        ]
        self._render_temp_table()
        self.refresh_prompts()

        timeout = float(self.db.get_setting("request_timeout", "60") or 60)
        temperature = float(self.db.get_setting("temperature", "0.7") or 0.7)

        self.worker = QueryWorker(models, prompt, timeout, temperature)
        self.worker.finished.connect(self._on_worker_finished)
        self.send_btn.setEnabled(False)
        self.statusBar().showMessage(f"Отправка в {len(models)} моделей…")
        self.worker.start()

    def _on_worker_finished(self) -> None:
        self.send_btn.setEnabled(True)
        worker = self.worker
        if worker is None:
            return
        if worker.error:
            self.statusBar().showMessage("Ошибка запроса")
            QMessageBox.critical(self, "ChatList", worker.error)
            return

        self.temp_rows = [
            TempRow(model_name=name, response_text=text or "", ok=ok)
            for name, text, ok in worker.rows
        ]
        for row in self.temp_rows:
            self.db.add_log(
                row.model_name,
                "ok" if row.ok else "error",
                row.response_text[:500],
            )
        self._render_temp_table()
        self.refresh_logs()
        ok_count = sum(1 for row in self.temp_rows if row.ok)
        self.statusBar().showMessage(
            f"Получено ответов: {ok_count} из {len(self.temp_rows)}"
        )
        if not self.temp_rows:
            QMessageBox.warning(self, "ChatList", "Модели не вернули результат.")
        elif ok_count == 0:
            details = "\n\n".join(
                f"{row.model_name}: {row.response_text[:400]}" for row in self.temp_rows
            )
            QMessageBox.warning(
                self,
                "ChatList",
                "Все запросы завершились с ошибкой.\n\n" + details,
            )

    def _render_temp_table(self) -> None:
        self.temp_table.blockSignals(True)
        self.temp_table.setSortingEnabled(False)
        self.temp_table.setRowCount(0)
        for row_data in self.temp_rows:
            row = self.temp_table.rowCount()
            self.temp_table.insertRow(row)

            check = QTableWidgetItem()
            check.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            check.setCheckState(
                Qt.CheckState.Checked if row_data.selected else Qt.CheckState.Unchecked
            )
            self.temp_table.setItem(row, 0, check)
            self.temp_table.setItem(row, 1, QTableWidgetItem(row_data.model_name))
            preview = (row_data.response_text or "").replace("\n", " ")
            if len(preview) > 180:
                preview = preview[:180] + "…"
            answer = QTableWidgetItem(preview)
            answer.setData(Qt.ItemDataRole.UserRole, row_data.response_text or "")
            self.temp_table.setItem(row, 2, answer)
            if row_data.pending:
                status = "ожидание…"
            elif row_data.ok:
                status = "ок"
            else:
                status = "ошибка"
            self.temp_table.setItem(row, 3, QTableWidgetItem(status))
        self.temp_table.setSortingEnabled(True)
        self.temp_table.blockSignals(False)
        self.preview.clear()

    def _on_temp_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        row = item.row()
        name_item = self.temp_table.item(row, 1)
        if name_item is None:
            return
        name = name_item.text()
        checked = item.checkState() == Qt.CheckState.Checked
        for temp in self.temp_rows:
            if temp.model_name == name:
                temp.selected = checked
                break

    def _show_temp_preview(self) -> None:
        row = self.temp_table.currentRow()
        if row < 0:
            self.preview.clear()
            return
        item = self.temp_table.item(row, 2)
        if item is None:
            self.preview.clear()
            return
        text = item.data(Qt.ItemDataRole.UserRole)
        markdown = text if text else item.text()
        self.preview.document().setDefaultStyleSheet(MARKDOWN_CSS)
        self.preview.setMarkdown(markdown or "")

    def _current_temp_answer(self) -> tuple[str, str] | None:
        row = self.temp_table.currentRow()
        if row < 0:
            return None
        name_item = self.temp_table.item(row, 1)
        answer_item = self.temp_table.item(row, 2)
        if name_item is None or answer_item is None:
            return None
        text = answer_item.data(Qt.ItemDataRole.UserRole) or answer_item.text()
        if not str(text).strip():
            return None
        return name_item.text(), str(text)

    def open_temp_markdown(self, *_args) -> None:
        current = self._current_temp_answer()
        if current is None:
            QMessageBox.information(
                self, "ChatList", "Выберите строку с ответом, затем нажмите «Открыть»."
            )
            return
        model_name, text = current
        dialog = MarkdownViewDialog(
            self,
            f"Ответ — {model_name}",
            f"# {model_name}\n\n{text}",
        )
        self._md_dialogs.append(dialog)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def open_saved_markdown(self) -> None:
        row = self.results_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "ChatList", "Выберите сохранённый результат.")
            return
        model_item = self.results_table.item(row, 2)
        prompt_item = self.results_table.item(row, 3)
        answer_item = self.results_table.item(row, 4)
        model_name = model_item.text() if model_item else "Модель"
        prompt = prompt_item.text() if prompt_item else ""
        answer = answer_item.text() if answer_item else ""
        if not answer.strip():
            QMessageBox.information(self, "ChatList", "В этой строке нет текста ответа.")
            return
        markdown = f"# {model_name}\n\n**Промт:** {prompt}\n\n{answer}"
        dialog = MarkdownViewDialog(self, f"Ответ — {model_name}", markdown)
        self._md_dialogs.append(dialog)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def save_selected(self) -> None:
        selected = [row for row in self.temp_rows if row.selected]
        if not selected:
            QMessageBox.information(
                self, "ChatList", "Отметьте строки, которые нужно сохранить."
            )
            return

        for row in selected:
            self.db.add_result(
                self.current_prompt_id,
                row.model_name,
                self.current_prompt_text,
                row.response_text,
            )

        self.temp_rows = []
        self._render_temp_table()
        self.refresh_results()
        self.statusBar().showMessage(f"Сохранено результатов: {len(selected)}")
        self.tabs.setCurrentIndex(3)

    def export_temp(self, fmt: str) -> None:
        rows = [row for row in self.temp_rows if row.selected] or self.temp_rows
        payload = [
            {
                "model": row.model_name,
                "ok": row.ok,
                "response": row.response_text,
                "prompt": self.current_prompt_text,
            }
            for row in rows
        ]
        self._export(payload, fmt)

    def export_saved(self, fmt: str) -> None:
        selected_ids = set(self._selected_ids(self.results_table))
        rows = self.db.list_results()
        if selected_ids:
            rows = [row for row in rows if int(row["id"]) in selected_ids]
        payload = [
            {
                "id": int(row["id"]),
                "created_at": row["created_at"],
                "model": row["model_name"],
                "prompt": row["prompt_text"],
                "response": row["response_text"],
            }
            for row in rows
        ]
        self._export(payload, fmt)

    def _export(self, payload: list[dict], fmt: str) -> None:
        if not payload:
            QMessageBox.information(self, "ChatList", "Нечего экспортировать.")
            return
        if fmt == "json":
            path, _ = QFileDialog.getSaveFileName(
                self, "Экспорт JSON", str(ROOT / "export.json"), "JSON (*.json)"
            )
            if not path:
                return
            Path(path).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        else:
            path, _ = QFileDialog.getSaveFileName(
                self, "Экспорт Markdown", str(ROOT / "export.md"), "Markdown (*.md)"
            )
            if not path:
                return
            chunks = ["# ChatList\n"]
            for item in payload:
                chunks.append(f"## {item.get('model', '')}\n")
                if item.get("prompt"):
                    chunks.append(f"**Промт:** {item['prompt']}\n")
                chunks.append(f"{item.get('response', '')}\n")
            Path(path).write_text("\n".join(chunks), encoding="utf-8")
        self.statusBar().showMessage(f"Экспортировано: {path}")

    # --- prompts ---

    def load_prompt_from_table(self) -> None:
        prompt_id = self._selected_id(self.prompts_table)
        if prompt_id is None:
            QMessageBox.information(self, "ChatList", "Выберите промт.")
            return
        row = self.db.get_prompt(prompt_id)
        if row is None:
            return
        self.prompt_edit.setPlainText(row["prompt"])
        self.tags_edit.setText(row["tags"])
        self.tabs.setCurrentIndex(0)

    def delete_prompt(self) -> None:
        prompt_id = self._selected_id(self.prompts_table)
        if prompt_id is None:
            return
        if self._confirm("Удалить выбранный промт?"):
            self.db.delete_prompt(prompt_id)
            self.refresh_prompts()

    # --- models ---

    def add_model(self) -> None:
        dialog = ModelDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, url, api_id, active = dialog.values()
        self.model_service.add(name, url, api_id, active)
        self.refresh_models()

    def edit_model(self) -> None:
        model_id = self._selected_id(self.models_table)
        if model_id is None:
            QMessageBox.information(self, "ChatList", "Выберите модель.")
            return
        current = next((m for m in self.model_service.all() if m.id == model_id), None)
        if current is None:
            return
        dialog = ModelDialog(self, current)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, url, api_id, active = dialog.values()
        self.model_service.update(model_id, name, url, api_id, active)
        self.refresh_models()

    def toggle_model(self) -> None:
        model_id = self._selected_id(self.models_table)
        if model_id is None:
            QMessageBox.information(self, "ChatList", "Выберите модель.")
            return
        current = next((m for m in self.model_service.all() if m.id == model_id), None)
        if current is None:
            return
        self.model_service.set_active(model_id, not current.is_active)
        self.refresh_models()

    def delete_model(self) -> None:
        model_id = self._selected_id(self.models_table)
        if model_id is None:
            return
        if self._confirm("Удалить выбранную модель?"):
            self.model_service.delete(model_id)
            self.refresh_models()

    # --- results / settings ---

    def _show_result_preview(self) -> None:
        row = self.results_table.currentRow()
        if row < 0:
            self.results_preview.clear()
            return
        prompt_item = self.results_table.item(row, 3)
        answer_item = self.results_table.item(row, 4)
        prompt = prompt_item.text() if prompt_item else ""
        answer = answer_item.text() if answer_item else ""
        self.results_preview.setPlainText(f"Промт:\n{prompt}\n\nОтвет:\n{answer}")

    def delete_result(self) -> None:
        ids = self._selected_ids(self.results_table)
        if not ids:
            return
        if self._confirm(f"Удалить записей: {len(ids)}?"):
            for result_id in ids:
                self.db.delete_result(result_id)
            self.refresh_results()
            self.results_preview.clear()

    def clear_logs(self) -> None:
        if self._confirm("Очистить журнал запросов?"):
            self.db.clear_logs()
            self.refresh_logs()

    def save_settings(self) -> None:
        timeout = self.timeout_edit.text().strip()
        temperature = self.temperature_edit.text().strip()
        try:
            if float(timeout) <= 0:
                raise ValueError
            float(temperature)
        except ValueError:
            QMessageBox.warning(self, "ChatList", "Проверьте таймаут и temperature.")
            return
        self.db.set_setting("request_timeout", timeout)
        self.db.set_setting("temperature", temperature)
        self.statusBar().showMessage("Настройки сохранены")

    def _confirm(self, text: str) -> bool:
        answer = QMessageBox.question(
            self,
            "ChatList",
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes


def main() -> None:
    app = QApplication(sys.argv)
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#5b4a1e"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#111827"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#fff4d6"))
    app.setPalette(palette)
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
