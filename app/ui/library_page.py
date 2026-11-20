"""Library tab: saved items, search by name, rename, export, delete."""
import os
import shutil

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QFileDialog, QGridLayout, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QVBoxLayout, QWidget)

from .common import OutlinePreview, button, card, label


class LibraryPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.setObjectName("Page")
        self.main, self.t, self.lib, self.p = main, main.t, main.library, main.palette
        self.current = None
        self.row_labels = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(14)

        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.t("search"))
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(520)
        self.search.textChanged.connect(lambda _: self.reload())
        self.count = label("", "Muted")
        top.addWidget(self.search, 1)
        top.addWidget(self.count)
        top.addStretch(1)
        outer.addLayout(top)

        body = QHBoxLayout()
        body.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(0)
        head = QWidget()
        hg = QGridLayout(head)
        hg.setContentsMargins(18, 8, 18, 8)
        for col, key in enumerate(("col_name", "col_size", "col_files")):
            hg.addWidget(label(self.t(key), "SectionTitle"), 0, col)
        hg.setColumnStretch(0, 4)
        hg.setColumnStretch(1, 4)
        hg.setColumnStretch(2, 3)
        left.addWidget(head)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self.on_select)
        left.addWidget(self.list, 1)
        self.empty = label("", "Muted", wrap=True)
        self.empty.setContentsMargins(18, 18, 18, 18)
        left.addWidget(self.empty)
        lw = QWidget()
        lw.setLayout(left)
        body.addWidget(lw, 3)

        self.detail, dl = card(spacing=12)
        dl.addWidget(label(self.t("name_label"), "SectionTitle"))
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("NameEdit")
        self.name_edit.textEdited.connect(self.on_rename)
        dl.addWidget(self.name_edit)
        dl.addWidget(label(self.t("rename_hint"), "Hint", wrap=True))
        self.preview = OutlinePreview(self.p["accent"], self.p["bg"], self.p["rs"])
        dl.addWidget(self.preview)
        dims = QGridLayout()
        self.dim_vals = {}
        for col, key in enumerate(("length", "width", "height")):
            dims.addWidget(label(self.t(key), "Hint"), 0, col)
            v = label("", "MidValue")
            dims.addWidget(v, 1, col)
            self.dim_vals[key] = v
        dl.addLayout(dims)
        self.files = label("", "Mono", wrap=True)
        dl.addWidget(self.files)
        dl.addWidget(button(self.t("export_dxf"), "Primary", self.on_export))
        row = QHBoxLayout()
        row.addWidget(button(self.t("open_folder"), on_click=self.on_open_folder))
        row.addWidget(button(self.t("delete"), "Danger", self.on_delete))
        dl.addLayout(row)
        dl.addStretch(1)
        self.detail.setMinimumWidth(320)
        self.detail.setMaximumWidth(440)
        body.addWidget(self.detail, 2)
        outer.addLayout(body, 1)

    def showEvent(self, e):
        super().showEvent(e)
        self.reload()

    # ---------- list ----------
    def _row_widget(self, item):
        w = QWidget()
        w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        g = QGridLayout(w)
        g.setContentsMargins(15, 0, 18, 0)
        name = label(item["display_name"])
        named = bool((item.get("name") or "").strip())
        name.setStyleSheet("font-weight: 600;" + ("" if named else f" color: {self.p['muted']};"))
        h = item["height_mm"]
        size = f"{item['length_mm']:.1f} × {item['width_mm']:.1f} × " + (f"{h:.1f}" if h is not None else self.t("empty_value"))
        sz = label(size, "")
        sz.setStyleSheet("font-family: Consolas, monospace;")
        files = label(f"item{item['id']}.dxf" + (" · .json" if item.get("json_path") else ""), "Mono")
        g.addWidget(name, 0, 0)
        g.addWidget(sz, 0, 1)
        g.addWidget(files, 0, 2)
        g.setColumnStretch(0, 4)
        g.setColumnStretch(1, 4)
        g.setColumnStretch(2, 3)
        return w, name

    def reload(self):
        keep = self.current["id"] if self.current else None
        items = self.lib.all(self.search.text())
        total = self.lib.count()
        self.list.blockSignals(True)
        self.list.clear()
        self.row_labels = {}
        select_row = 0
        for n, it in enumerate(items):
            li = QListWidgetItem()
            li.setData(Qt.ItemDataRole.UserRole, it["id"])
            li.setSizeHint(QSize(100, 54))
            self.list.addItem(li)
            w, name_label = self._row_widget(it)
            self.list.setItemWidget(li, w)
            self.row_labels[it["id"]] = name_label
            if it["id"] == keep:
                select_row = n
        self.list.blockSignals(False)
        self.count.setText(self.t("items_count", shown=len(items), total=total))
        has = bool(items)
        self.list.setVisible(has)
        self.empty.setVisible(not has)
        self.empty.setText(self.t("library_empty") if total == 0 else self.t("no_match"))
        self.detail.setVisible(has)
        if has:
            self.list.setCurrentRow(select_row)
            self.on_select(self.list.currentItem(), None)
        else:
            self.current = None

    def on_select(self, li, _prev=None):
        if li is None:
            return
        self.current = self.lib.get(li.data(Qt.ItemDataRole.UserRole))
        it = self.current
        if not it:
            return
        self.name_edit.setText(it.get("name") or "")
        self.name_edit.setPlaceholderText(f"item{it['id']}")
        self.preview.set_points(it["outline"])
        e = self.t("empty_value")
        self.dim_vals["length"].setText(f"{it['length_mm']:.1f}")
        self.dim_vals["width"].setText(f"{it['width_mm']:.1f}")
        self.dim_vals["height"].setText(f"{it['height_mm']:.1f}" if it["height_mm"] is not None else e)
        names = [os.path.basename(p) for p in (it.get("dxf_path"), it.get("json_path")) if p]
        self.files.setText("\n".join(names))

    # ---------- actions ----------
    def on_rename(self, text):
        if not self.current:
            return
        self.current = self.lib.rename(self.current["id"], text)
        lab = self.row_labels.get(self.current["id"])
        if lab is not None:
            lab.setText(self.current["display_name"])
            named = bool(text.strip())
            lab.setStyleSheet("font-weight: 600;" + ("" if named else f" color: {self.p['muted']};"))

    def on_export(self):
        it = self.current
        if not it or not it.get("dxf_path") or not os.path.exists(it["dxf_path"]):
            return
        safe = "".join(c for c in it["display_name"] if c not in '\\/:*?"<>|').strip() or f"item{it['id']}"
        path, _ = QFileDialog.getSaveFileName(self, self.t("export_dxf"),
                                              os.path.join(os.path.expanduser("~"), safe + ".dxf"), "DXF (*.dxf)")
        if path:
            if not path.lower().endswith(".dxf"):
                path += ".dxf"
            shutil.copyfile(it["dxf_path"], path)

    def on_open_folder(self):
        folder = os.path.dirname(self.current["dxf_path"]) if self.current and self.current.get("dxf_path") \
            else self.main.settings.get("export_folder")
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def on_delete(self):
        it = self.current
        if not it:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(self.t("delete"))
        box.setText(self.t("delete_confirm", name=it["display_name"]))
        yes = box.addButton(self.t("delete"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(self.t("cancel"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is yes:
            self.lib.delete(it["id"])
            self.current = None
            self.reload()
