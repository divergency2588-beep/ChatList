"""Логика работы с нейросетями (таблица models)."""

from __future__ import annotations

from dataclasses import dataclass

from db import Database


@dataclass
class Model:
    id: int
    name: str
    api_url: str
    api_id: str
    is_active: bool

    @classmethod
    def from_row(cls, row) -> "Model":
        return cls(
            id=int(row["id"]),
            name=str(row["name"]),
            api_url=str(row["api_url"]),
            api_id=str(row["api_id"]),
            is_active=bool(row["is_active"]),
        )


class ModelService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def all(self) -> list[Model]:
        return [Model.from_row(row) for row in self.db.list_models()]

    def active(self) -> list[Model]:
        return [Model.from_row(row) for row in self.db.list_active_models()]

    def add(self, name: str, api_url: str, api_id: str, is_active: bool = True) -> Model:
        model_id = self.db.add_model(name, api_url, api_id, is_active)
        return Model(model_id, name.strip(), api_url.strip(), api_id.strip(), is_active)

    def update(
        self,
        model_id: int,
        name: str,
        api_url: str,
        api_id: str,
        is_active: bool,
    ) -> None:
        self.db.update_model(model_id, name, api_url, api_id, is_active)

    def delete(self, model_id: int) -> None:
        self.db.delete_model(model_id)

    def set_active(self, model_id: int, is_active: bool) -> None:
        self.db.set_model_active(model_id, is_active)
