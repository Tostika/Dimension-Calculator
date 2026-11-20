"""Library of saved items (SQLite). New items are named item1, item2, ... until renamed.
Files always keep the itemN name, so a Georgian or long name never breaks a file path."""
import json
import os
import sqlite3
import time

from . import export


class Library:
    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                length_mm REAL NOT NULL,
                width_mm REAL NOT NULL,
                height_mm REAL,
                outline_json TEXT NOT NULL,
                dxf_path TEXT,
                json_path TEXT,
                created_at REAL NOT NULL
            )"""
        )
        self.conn.commit()

    @staticmethod
    def default_name(item_id):
        return f"item{item_id}"

    def _row(self, r):
        d = dict(r)
        d["display_name"] = (d.get("name") or "").strip() or self.default_name(d["id"])
        d["outline"] = json.loads(d.pop("outline_json"))
        return d

    def add(self, length, width, height, outline_mm, export_folder, save_json=True):
        cur = self.conn.execute(
            "INSERT INTO items (name, length_mm, width_mm, height_mm, outline_json, created_at) VALUES (NULL, ?, ?, ?, ?, ?)",
            (float(length), float(width), None if height is None else float(height), json.dumps(outline_mm), time.time()),
        )
        item_id = cur.lastrowid
        os.makedirs(export_folder, exist_ok=True)
        base = os.path.join(export_folder, self.default_name(item_id))
        dxf_path = base + ".dxf"
        export.write_dxf(dxf_path, outline_mm, length, width, height)
        json_path = None
        if save_json:
            json_path = base + ".json"
            export.write_json(json_path, self.default_name(item_id), length, width, height, outline_mm)
        self.conn.execute("UPDATE items SET dxf_path = ?, json_path = ? WHERE id = ?", (dxf_path, json_path, item_id))
        self.conn.commit()
        return self.get(item_id)

    def get(self, item_id):
        r = self.conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return self._row(r) if r else None

    def all(self, search=""):
        rows = [self._row(r) for r in self.conn.execute("SELECT * FROM items ORDER BY id DESC")]
        q = (search or "").strip().lower()
        if q:
            rows = [r for r in rows if q in r["display_name"].lower() or q in self.default_name(r["id"])]
        return rows

    def count(self):
        return self.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]

    def rename(self, item_id, name):
        name = (name or "").strip() or None
        self.conn.execute("UPDATE items SET name = ? WHERE id = ?", (name, item_id))
        self.conn.commit()
        item = self.get(item_id)
        if item and item.get("json_path") and os.path.exists(item["json_path"]):
            export.write_json(item["json_path"], item["display_name"], item["length_mm"], item["width_mm"],
                              item["height_mm"], item["outline"])
        return item

    def delete(self, item_id):
        item = self.get(item_id)
        if not item:
            return
        for p in (item.get("dxf_path"), item.get("json_path")):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        self.conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        self.conn.commit()

    def close(self):
        self.conn.close()
