"""Просмотр SQLite: список таблиц, пагинация и CRUD."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

PAGE_SIZE = 50

STYLE = """
QMainWindow, QDialog { background: #e6edf5; }
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
QLineEdit, QPlainTextEdit, QListWidget {
    border: 1px solid #7c93ad;
    border-radius: 6px;
    padding: 6px;
    background: #fff4d6;
    color: #111827;
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
    font-weight: 600;
}
QStatusBar { background: #c5d4e6; color: #1e293b; }
"""


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


class Column:
    def __init__(self, cid: int, name: str, col_type: str, notnull: bool, default, pk: int) -> None:
        self.cid = cid
        self.name = name
        self.col_type = col_type or ""
        self.notnull = notnull
        self.default = default
        self.pk = pk

    @property
    def is_integer_pk(self) -> bool:
        return self.pk > 0 and "INT" in self.col_type.upper()


class RowDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        columns: list[Column],
        values: dict[str, str] | None = None,
        skip_auto_pk: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 420)
        self.editors: dict[str, QLineEdit | QPlainTextEdit] = {}

        form = QFormLayout()
        for col in columns:
            if skip_auto_pk and col.is_integer_pk and not values:
                continue
            current = "" if values is None else values.get(col.name, "")
            if col.col_type.upper() in {"TEXT", ""} or "CHAR" in col.col_type.upper():
                editor: QLineEdit | QPlainTextEdit = QPlainTextEdit()
                editor.setPlainText(current)
                editor.setMinimumHeight(70)
            else:
                editor = QLineEdit()
                editor.setText(current)
            hint = col.col_type or "TEXT"
            if col.notnull:
                hint += ", NOT NULL"
            if col.pk:
                hint += ", PK"
            form.addRow(f"{col.name} ({hint})", editor)
            self.editors[col.name] = editor

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for name, editor in self.editors.items():
            if isinstance(editor, QPlainTextEdit):
                result[name] = editor.toPlainText()
            else:
                result[name] = editor.text()
        return result


class DbViewer(QMainWindow):
    def __init__(self, db_path: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("test-db — просмотр SQLite")
        self.resize(1100, 720)

        self.conn: sqlite3.Connection | None = None
        self.db_path: Path | None = None
        self.current_table = ""
        self.columns: list[Column] = []
        self.pk_columns: list[str] = []
        self.page = 0
        self.total_rows = 0

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Путь к файлу .db / .sqlite")
        self.path_edit.setReadOnly(True)

        browse_btn = QPushButton("Выбрать файл")
        browse_btn.clicked.connect(self.choose_file)

        self.tables = QListWidget()
        self.tables.itemDoubleClicked.connect(self.open_table)

        open_btn = QPushButton("Открыть")
        open_btn.clicked.connect(self.open_table)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Таблицы"))
        left_layout.addWidget(self.tables, 1)
        left_layout.addWidget(open_btn)

        self.title_label = QLabel("Таблица не открыта")
        self.grid = QTableWidget(0, 0)
        self.grid.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grid.setAlternatingRowColors(True)
        self.grid.verticalHeader().setVisible(False)
        self.grid.horizontalHeader().setStretchLastSection(True)
        self.grid.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)

        add_btn = QPushButton("Добавить")
        add_btn.clicked.connect(self.add_row)
        edit_btn = QPushButton("Изменить")
        edit_btn.setObjectName("secondary")
        edit_btn.clicked.connect(self.edit_row)
        del_btn = QPushButton("Удалить")
        del_btn.setObjectName("secondary")
        del_btn.clicked.connect(self.delete_row)
        refresh_btn = QPushButton("Обновить")
        refresh_btn.setObjectName("secondary")
        refresh_btn.clicked.connect(self.reload_page)

        crud = QHBoxLayout()
        crud.addWidget(add_btn)
        crud.addWidget(edit_btn)
        crud.addWidget(del_btn)
        crud.addWidget(refresh_btn)
        crud.addStretch()

        self.prev_btn = QPushButton("Назад")
        self.prev_btn.setObjectName("secondary")
        self.prev_btn.clicked.connect(self.prev_page)
        self.next_btn = QPushButton("Вперёд")
        self.next_btn.setObjectName("secondary")
        self.next_btn.clicked.connect(self.next_page)
        self.page_label = QLabel("Страница 0 / 0")

        pager = QHBoxLayout()
        pager.addWidget(self.prev_btn)
        pager.addWidget(self.page_label)
        pager.addWidget(self.next_btn)
        pager.addStretch()

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(self.title_label)
        right_layout.addLayout(crud)
        right_layout.addWidget(self.grid, 1)
        right_layout.addLayout(pager)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 860])

        top = QHBoxLayout()
        top.addWidget(QLabel("Файл"))
        top.addWidget(self.path_edit, 1)
        top.addWidget(browse_btn)

        central = QWidget()
        root = QVBoxLayout(central)
        root.addLayout(top)
        root.addWidget(splitter, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("Выберите SQLite-файл")

        start = db_path or Path(__file__).resolve().parent / "chatlist.db"
        if start.exists():
            self.open_database(start)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.conn is not None:
            self.conn.close()
        super().closeEvent(event)

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Открыть SQLite",
            str(Path(__file__).resolve().parent),
            "SQLite (*.db *.sqlite *.sqlite3);;Все файлы (*.*)",
        )
        if path:
            self.open_database(Path(path))

    def open_database(self, path: Path) -> None:
        try:
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
        except sqlite3.Error as exc:
            QMessageBox.critical(self, "test-db", f"Не удалось открыть файл:\n{exc}")
            return

        if self.conn is not None:
            self.conn.close()
        self.conn = conn
        self.db_path = path
        self.path_edit.setText(str(path))
        self.current_table = ""
        self.columns = []
        self.pk_columns = []
        self.page = 0
        self.total_rows = 0
        self.grid.setRowCount(0)
        self.grid.setColumnCount(0)
        self.title_label.setText("Таблица не открыта")
        self._load_table_names()
        self.statusBar().showMessage(f"Открыт файл: {path.name}")

    def _load_table_names(self) -> None:
        self.tables.clear()
        if self.conn is None:
            return
        rows = self.conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name COLLATE NOCASE
            """
        ).fetchall()
        for row in rows:
            self.tables.addItem(str(row["name"]))

    def open_table(self) -> None:
        item = self.tables.currentItem()
        if item is None:
            QMessageBox.information(self, "test-db", "Выберите таблицу в списке.")
            return
        self.current_table = item.text()
        self.page = 0
        self._load_schema()
        self.reload_page()

    def _load_schema(self) -> None:
        assert self.conn is not None
        info = self.conn.execute(f"PRAGMA table_info({quote_ident(self.current_table)})").fetchall()
        self.columns = [
            Column(
                int(row["cid"]),
                str(row["name"]),
                str(row["type"] or ""),
                bool(row["notnull"]),
                row["dflt_value"],
                int(row["pk"]),
            )
            for row in info
        ]
        self.pk_columns = [col.name for col in sorted(self.columns, key=lambda c: c.pk) if col.pk > 0]
        if not self.pk_columns:
            self.pk_columns = ["rowid"]

    def reload_page(self) -> None:
        if self.conn is None or not self.current_table:
            return

        table = quote_ident(self.current_table)
        self.total_rows = int(self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        pages = max(1, (self.total_rows + PAGE_SIZE - 1) // PAGE_SIZE)
        if self.page >= pages:
            self.page = pages - 1
        if self.page < 0:
            self.page = 0

        select_cols = ", ".join(quote_ident(col.name) for col in self.columns)
        if self.pk_columns == ["rowid"]:
            sql = (
                f"SELECT rowid AS rowid, {select_cols} FROM {table} "
                f"ORDER BY rowid LIMIT ? OFFSET ?"
            )
            headers = ["rowid"] + [col.name for col in self.columns]
        else:
            sql = f"SELECT {select_cols} FROM {table} ORDER BY {quote_ident(self.pk_columns[0])} LIMIT ? OFFSET ?"
            headers = [col.name for col in self.columns]

        rows = self.conn.execute(sql, (PAGE_SIZE, self.page * PAGE_SIZE)).fetchall()
        self.grid.setSortingEnabled(False)
        self.grid.setColumnCount(len(headers))
        self.grid.setHorizontalHeaderLabels(headers)
        self.grid.setRowCount(0)
        for row in rows:
            r = self.grid.rowCount()
            self.grid.insertRow(r)
            for c, name in enumerate(headers):
                value = row[name]
                text = "" if value is None else str(value)
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, value)
                self.grid.setItem(r, c, item)

        self.title_label.setText(
            f"Таблица: {self.current_table}  •  строк: {self.total_rows}  •  PK: {', '.join(self.pk_columns)}"
        )
        self.page_label.setText(f"Страница {self.page + 1} / {pages}")
        self.prev_btn.setEnabled(self.page > 0)
        self.next_btn.setEnabled(self.page + 1 < pages)
        self.statusBar().showMessage(
            f"{self.current_table}: показано {len(rows)} из {self.total_rows}"
        )

    def prev_page(self) -> None:
        self.page -= 1
        self.reload_page()

    def next_page(self) -> None:
        self.page += 1
        self.reload_page()

    def _selected_values(self) -> dict[str, object] | None:
        row = self.grid.currentRow()
        if row < 0:
            return None
        values: dict[str, object] = {}
        for col in range(self.grid.columnCount()):
            header = self.grid.horizontalHeaderItem(col)
            item = self.grid.item(row, col)
            if header is None:
                continue
            values[header.text()] = None if item is None else item.data(Qt.ItemDataRole.UserRole)
        return values

    def add_row(self) -> None:
        if not self._ready():
            return
        dialog = RowDialog(self, "Добавить строку", self.columns, skip_auto_pk=True)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.values()
        names = [name for name, value in data.items() if value != ""]
        if not names:
            QMessageBox.information(self, "test-db", "Заполните хотя бы одно поле.")
            return
        placeholders = ", ".join("?" for _ in names)
        sql = (
            f"INSERT INTO {quote_ident(self.current_table)} "
            f"({', '.join(quote_ident(n) for n in names)}) VALUES ({placeholders})"
        )
        try:
            assert self.conn is not None
            self.conn.execute(sql, [data[n] for n in names])
            self.conn.commit()
        except sqlite3.Error as exc:
            QMessageBox.critical(self, "test-db", str(exc))
            return
        self.reload_page()

    def edit_row(self) -> None:
        if not self._ready():
            return
        selected = self._selected_values()
        if selected is None:
            QMessageBox.information(self, "test-db", "Выберите строку.")
            return
        current = {col.name: "" if selected.get(col.name) is None else str(selected.get(col.name)) for col in self.columns}
        dialog = RowDialog(self, "Изменить строку", self.columns, current)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.values()
        assignments = ", ".join(f"{quote_ident(col.name)}=?" for col in self.columns)
        where, params = self._pk_clause(selected)
        sql = f"UPDATE {quote_ident(self.current_table)} SET {assignments} WHERE {where}"
        try:
            assert self.conn is not None
            self.conn.execute(sql, [data[col.name] for col in self.columns] + params)
            self.conn.commit()
        except sqlite3.Error as exc:
            QMessageBox.critical(self, "test-db", str(exc))
            return
        self.reload_page()

    def delete_row(self) -> None:
        if not self._ready():
            return
        selected = self._selected_values()
        if selected is None:
            QMessageBox.information(self, "test-db", "Выберите строку.")
            return
        answer = QMessageBox.question(
            self,
            "test-db",
            "Удалить выбранную строку?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        where, params = self._pk_clause(selected)
        sql = f"DELETE FROM {quote_ident(self.current_table)} WHERE {where}"
        try:
            assert self.conn is not None
            self.conn.execute(sql, params)
            self.conn.commit()
        except sqlite3.Error as exc:
            QMessageBox.critical(self, "test-db", str(exc))
            return
        self.reload_page()

    def _pk_clause(self, selected: dict[str, object]) -> tuple[str, list[object]]:
        parts = []
        params: list[object] = []
        for name in self.pk_columns:
            parts.append(f"{quote_ident(name)}=?")
            params.append(selected.get(name))
        return " AND ".join(parts), params

    def _ready(self) -> bool:
        if self.conn is None or not self.current_table:
            QMessageBox.information(self, "test-db", "Сначала откройте таблицу кнопкой «Открыть».")
            return False
        return True


def main() -> None:
    app = QApplication(sys.argv)
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Text, QColor("#111827"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#fff4d6"))
    app.setPalette(palette)
    app.setStyleSheet(STYLE)

    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    window = DbViewer(db_path)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
