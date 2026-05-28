"""
app.py — PayrollPro Desktop Application
========================================
Professional native desktop payroll software.
Run with:  python app.py
"""

import os, sys, csv, datetime, threading, tempfile

if getattr(sys, 'frozen', False):
    os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = os.path.join(
        sys._MEIPASS, 'PyQt6', 'Qt6', 'plugins', 'platforms'
    )

from version import APP_NAME, APP_VERSION
from backup_manager import BackupManager
from lan_sync import LanSync

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QPushButton, QStackedWidget,
                             QScrollArea, QFrame, QComboBox, QLineEdit, QTableWidget,
                             QTableWidgetItem, QHeaderView, QAbstractItemView, QTabWidget,
                             QMessageBox, QFileDialog, QInputDialog, QStyledItemDelegate)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize, QThread, pyqtSlot, QEvent, QMetaObject
from PyQt6.QtGui import QColor, QFont, QIcon, QBrush, QAction, QPalette

from schema import Worker, AttendanceRecord, CompanyConfig, SKILL_CATEGORIES
from database import (
    init_db, get_all_workers, get_all_skill_wages, get_skill_wages_dict,
    upsert_skill_wage,
    get_attendance, upsert_attendance, bulk_upsert_attendance,
    delete_attendance_for_worker,
    upsert_worker, deactivate_worker, reactivate_worker,
    delete_worker, get_worker_by_id,
    get_config, save_config, get_months_with_data,
    get_workers_by_unit, import_attendance_from_csv, import_workers_from_csv,
    get_all_units, add_unit, rename_unit, delete_unit,
    unit_worker_count,
    get_all_banks, add_bank, update_bank, delete_bank,
    get_workers_and_attendance,
    close_thread_conn,
    DB_PATH,
)
from payroll_engine import calculate_payroll, payroll_summary
from pdf_generator import generate_bulk_pdfs, generate_slip_pdf
from schema import SkillWage

# --- Global Exception Hook to prevent crashes from unhandled slot exceptions ---
def global_excepthook(exc_type, exc_value, exc_tb):
    import traceback
    import logging
    tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    print(tb_str, file=sys.stderr)
    logging.critical("Uncaught Exception: %s", tb_str)
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance():
            QMessageBox.critical(
                None,
                "Unexpected Error",
                f"An unexpected error occurred:\n\n{exc_value}\n\n"
                f"The application will attempt to continue."
            )
    except Exception as e:
        print(f"Error in global excepthook: {e}", file=sys.stderr)

sys.excepthook = global_excepthook


# ── Theme ─────────────────────────────────────────────────────────────────────
ACCENT          = "#3B82F6"      # Electric blue
ACCENT_HOVER    = "#2563EB"
ACCENT_DARK     = "#1D4ED8"
SUCCESS         = "#22C55E"      # Emerald
DANGER          = "#EF4444"      # Red
WARNING_CLR     = "#F59E0B"      # Amber
SURFACE         = "#131320"      # Deep navy
SURFACE_2       = "#18183A"      # Slightly lighter
SURFACE_3       = "#1E1E40"      # Card surface
CARD_BG         = "#23234A"      # Card background
CARD_BORDER     = "#35356A"      # Subtle border tint
TEXT_PRIMARY    = "#F1F5FF"      # Near white
TEXT_SECONDARY  = "#94A3C4"      # Cool grey-blue
TEXT_MUTED      = "#4A5070"      # Dim
SIDEBAR_BG      = "#0A0A18"      # Deep black-blue
SIDEBAR_HOVER   = "#131326"
GLAS            = "#191932"      # Glassmorphism surface

FONT_FAMILY      = "Segoe UI"

QSS = f"""
QWidget {{
    background-color: {SURFACE};
    color: {TEXT_PRIMARY};
    font-family: "{FONT_FAMILY}";
}}
QFrame#card {{
    background-color: {CARD_BG};
    border-radius: 10px;
    border: 1px solid {CARD_BORDER};
}}
QFrame#sidebar {{
    background-color: {SIDEBAR_BG};
}}
QFrame#surface2 {{
    background-color: {SURFACE_2};
    border-radius: 10px;
}}
QFrame#header_accent {{
    background-color: {ACCENT};
}}
QPushButton {{
    background-color: {ACCENT};
    color: {TEXT_PRIMARY};
    border-radius: 6px;
    padding: 6px;
    font-weight: bold;
}}
QPushButton:hover {{
    background-color: {ACCENT_HOVER};
}}
QPushButton#sidebarBtn {{
    background-color: transparent;
    color: {TEXT_SECONDARY};
    text-align: left;
    padding: 10px;
    border-radius: 10px;
    font-size: 14px;
}}
QPushButton#sidebarBtn:hover {{
    background-color: {SIDEBAR_HOVER};
}}
QPushButton#sidebarBtn[active="true"] {{
    background-color: {ACCENT};
    color: white;
}}
QLineEdit, QComboBox {{
    background-color: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 5px;
    padding: 6px 10px;
    color: {TEXT_PRIMARY};
}}
QLineEdit:focus, QComboBox:focus {{
    border: 1px solid {ACCENT};
    background-color: rgba(255, 255, 255, 0.05);
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background-color: {SURFACE_3};
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT};
    border-radius: 4px;
    border: 1px solid {CARD_BORDER};
}}
QTableWidget {{
    background-color: {SURFACE_3};
    alternate-background-color: #151522;
    gridline-color: rgba(255, 255, 255, 0.03);
    border: none;
    outline: none;
}}
QTableWidget::item {{
    padding: 4px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.02);
}}
QTableWidget::item:selected {{
    background-color: rgba(66, 165, 245, 0.15);
}}
QHeaderView::section {{
    background-color: #0B1D33;
    color: #90CAF9;
    font-weight: bold;
    border: none;
    border-bottom: 2px solid #1E3A5F;
    padding: 8px 6px;
}}
QTabWidget::pane {{
    border: none;
    background-color: transparent;
}}
QTabBar::tab {{
    background-color: {SURFACE_3};
    color: {TEXT_SECONDARY};
    padding: 8px 16px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background-color: {ACCENT};
    color: white;
}}
QScrollBar:vertical {{
    background-color: {SURFACE_3};
    width: 12px;
}}
QScrollBar::handle:vertical {{
    background-color: {TEXT_MUTED};
    border-radius: 6px;
}}
QLabel {{
    background-color: transparent;
}}
QLabel#title {{
    font-size: 22px;
    font-weight: bold;
}}
QLabel#subtitle {{
    font-size: 12px;
    color: {TEXT_SECONDARY};
}}
QLabel#section {{
    font-size: 15px;
    font-weight: bold;
    color: {ACCENT};
}}
QLabel#metric_val {{
    font-size: 22px;
    font-weight: bold;
}}
QLabel#metric_lbl {{
    font-size: 12px;
    color: {TEXT_SECONDARY};
}}
"""

# ── Helpers ───────────────────────────────────────────────────────────────────
# Fix #5 — cache month_options() to avoid hitting DB on every page load
_month_options_cache: list = []
_month_options_ts: float = 0.0
_MONTH_OPTIONS_TTL = 15.0   # seconds

def month_options():
    import time as _time
    global _month_options_cache, _month_options_ts
    now = _time.monotonic()
    if _month_options_cache and (now - _month_options_ts) < _MONTH_OPTIONS_TTL:
        return _month_options_cache
    today = datetime.date.today()
    m_set = set()
    for i in range(11, -3, -1):  # Include 11 past months, current month (0), and 2 future months (-1, -2)
        y, m = today.year, today.month - i
        while m <= 0: m += 12; y -= 1
        while m > 12: m -= 12; y += 1
        m_set.add(f"{y}-{m:02d}")
    # Include any historical months that have attendance data
    try:
        existing = get_months_with_data()
        if existing:
            m_set.update(existing)
    except Exception:
        pass
    _month_options_cache = sorted(list(m_set))
    _month_options_ts = now
    return _month_options_cache

def _invalidate_month_options_cache():
    """Call after bulk_upsert_attendance to refresh the cache on next access."""
    global _month_options_ts
    _month_options_ts = 0.0

def fmt_inr(amount):
    s = f"{abs(amount):,.2f}"; p = s.split(".")
    n = p[0].replace(",", "")
    if len(n) <= 3: fmt = n
    else:
        last3 = n[-3:]; rest = n[:-3]; grps = []
        while len(rest) > 2: grps.insert(0, rest[-2:]); rest = rest[:-2]
        if rest: grps.insert(0, rest)
        fmt = ",".join(grps) + "," + last3
    result = f"₹{fmt}.{p[1]}"
    return ("-" + result) if amount < 0 else result

def _unit_list():
    b = get_all_units(); return b if b else ["(No units)"]

def _unit_filter_list():
    b = get_all_units(); return ["All"] + b if b else ["All"]

def _bank_names():
    b = get_all_banks(); return b if b else ["(No banks — add in Settings)"]

def sync_combo(cb, items, keep_current=True):
    cur = cb.currentText()
    cb.blockSignals(True)
    cb.clear()
    cb.addItems(items)
    if keep_current and cur in items: cb.setCurrentText(cur)
    elif items: cb.setCurrentIndex(0)
    cb.blockSignals(False)

def _page_header(layout, title, subtitle):
    row = QHBoxLayout()
    row.setContentsMargins(28, 14, 28, 6)
    accent = QFrame()
    accent.setObjectName("header_accent")
    accent.setFixedSize(4, 46)
    row.addWidget(accent)
    info = QVBoxLayout()
    info.setContentsMargins(14, 0, 0, 0)
    info.setSpacing(2)
    t = QLabel(title); t.setObjectName("title"); info.addWidget(t)
    s = QLabel(subtitle); s.setObjectName("subtitle"); info.addWidget(s)
    row.addLayout(info)
    row.addStretch()
    layout.addLayout(row)

def _section_label(layout, text):
    row = QHBoxLayout()
    row.setContentsMargins(0, 10, 0, 2)
    lbl = QLabel(text); lbl.setObjectName("section")
    row.addWidget(lbl)
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"background-color: {SURFACE_3};")
    row.addWidget(line, 1)
    layout.addLayout(row)

class MetricCard(QFrame):
    def __init__(self, label, value, color=ACCENT, icon="", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        top = QFrame()
        top.setFixedHeight(4)
        top.setStyleSheet(f"background-color: {color}; border-top-left-radius: 10px; border-top-right-radius: 10px;")
        layout.addWidget(top)
        inner = QVBoxLayout()
        inner.setContentsMargins(18, 12, 18, 16)
        if icon:
            ic = QLabel(icon)
            ic.setStyleSheet(f"font-size: 20px; color: {color};")
            inner.addWidget(ic)
        val = QLabel(str(value))
        val.setObjectName("metric_val")
        val.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 22px;")
        inner.addWidget(val)
        lbl = QLabel(label)
        lbl.setObjectName("metric_lbl")
        inner.addWidget(lbl)
        layout.addLayout(inner)

class PieChartWidget(QWidget):
    """Custom pie chart drawn with QPainter — no external libs needed."""
    PIE_COLORS = ["#3B82F6","#22C55E","#F59E0B","#EF4444","#A78BFA","#38BDF8","#FB923C","#34D399"]

    def __init__(self, data: dict, parent=None):
        """data: {label: value}"""
        super().__init__(parent)
        self.data = data
        self.setMinimumHeight(220)

    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter, QColor, QPen, QFont
        from PyQt6.QtCore import QRectF, Qt
        import math
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        total = sum(self.data.values()) or 1
        items = [(k, v) for k, v in self.data.items()]
        items.sort(key=lambda x: -x[1])

        w, h = self.width(), self.height()
        legend_w = max(200, w // 3)
        pie_size = min(h - 20, w - legend_w - 20)
        pie_rect = QRectF((w - legend_w - pie_size) / 2, (h - pie_size) / 2, pie_size, pie_size)

        angle = 90 * 16  # start at top
        for i, (label, val) in enumerate(items):
            span = int(round((val / total) * 360 * 16))
            color = QColor(self.PIE_COLORS[i % len(self.PIE_COLORS)])
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPie(pie_rect, angle, span)
            angle += span

        # Draw inner circle for donut effect
        inner_r = pie_size * 0.38
        cx, cy = pie_rect.center().x(), pie_rect.center().y()
        painter.setBrush(QColor("#23234A"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(cx - inner_r, cy - inner_r, inner_r * 2, inner_r * 2))

        # Center label
        painter.setPen(QColor("#F1F5FF"))
        fnt = QFont("Segoe UI", 9, QFont.Weight.Bold)
        painter.setFont(fnt)
        painter.drawText(pie_rect, Qt.AlignmentFlag.AlignCenter, f"{len(items)}\nUnits")

        # Legend
        lx = int(w - legend_w + 10)
        ly = int((h - len(items) * 26) / 2)
        fnt2 = QFont("Segoe UI", 8)
        painter.setFont(fnt2)
        for i, (label, val) in enumerate(items):
            color = QColor(self.PIE_COLORS[i % len(self.PIE_COLORS)])
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(lx, ly + i * 26, 12, 12, 3, 3)
            painter.setPen(QColor("#F1F5FF"))
            pct = (val / total) * 100
            disp = label if label else "Unassigned"
            painter.drawText(lx + 18, ly + i * 26 + 11, f"{disp}  {pct:.1f}%")
        painter.end()

class SidebarButton(QPushButton):
    def __init__(self, text, icon, key, parent=None):
        super().__init__(f"  {icon}   {text}", parent)
        self.key = key
        self.setObjectName("sidebarBtn")
        self.setFixedHeight(46)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_active(self, a):
        self.setProperty("active", "true" if a else "false")
        self.style().unpolish(self)
        self.style().polish(self)

class WorkerDelegate(QStyledItemDelegate):
    def __init__(self, parent=None, db_update_cb=None):
        super().__init__(parent)
        self.db_update_cb = db_update_cb
        
    def createEditor(self, parent, option, index):
        col_name = self.parent().horizontalHeaderItem(index.column()).text()
        if col_name in ("ID", "Status"):
            return None
        if col_name in ("Unit", "Skill", "Bank"):
            cb = QComboBox(parent)
            cb.setStyleSheet(
                f"background-color: {SURFACE_3}; color: {TEXT_PRIMARY}; "
                f"border: 1px solid {ACCENT}; border-radius: 3px;"
            )
            if col_name == "Unit": cb.addItems(_unit_list())
            elif col_name == "Skill": cb.addItems(SKILL_CATEGORIES)
            elif col_name == "Bank": cb.addItems(get_all_banks() or ["(No banks — add in Settings)"])
            return cb
        editor = QLineEdit(parent)
        editor.setStyleSheet(
            f"background-color: {SURFACE_3}; color: {TEXT_PRIMARY}; "
            f"border: 1px solid {ACCENT}; border-radius: 3px; padding: 0px 4px;"
        )
        return editor

    def setEditorData(self, editor, index):
        val = index.model().data(index, Qt.ItemDataRole.EditRole)
        if isinstance(editor, QComboBox):
            editor.setCurrentText(str(val))
        else:
            editor.setText(str(val))
            editor.selectAll()
            
    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QComboBox):
            val = editor.currentText()
        else:
            val = editor.text()
        model.setData(index, val, Qt.ItemDataRole.EditRole)
        if self.db_update_cb:
            self.db_update_cb(index.row())

class StyledTable(QTableWidget):
    def __init__(self, columns, column_widths=None, parent=None, editable=False, db_update_cb=None, stretch_last=True):
        super().__init__(parent)
        self.setColumnCount(len(columns))
        self.setHorizontalHeaderLabels(columns)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        self.horizontalHeader().setStretchLastSection(stretch_last)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        if column_widths:
            for i, w in enumerate(column_widths):
                if stretch_last and i == len(columns) - 1:
                    continue
                self.setColumnWidth(i, w)
        if editable:
            self.delegate = WorkerDelegate(self, db_update_cb)
            self.setItemDelegate(self.delegate)
            self.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        else:
            self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

    def insert_rows(self, rows, tags=None, checkable_col=None):
        self.setUpdatesEnabled(False)   # batch all repaints
        self.setRowCount(0)
        self.setRowCount(len(rows))
        for r_idx, row in enumerate(rows):
            for c_idx, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                if checkable_col is not None and c_idx == checkable_col:
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Unchecked)
                if tags and r_idx < len(tags):
                    tag = tags[r_idx]
                    if tag == "skilled": item.setForeground(QColor("#80CBC4"))
                    elif tag == "semi": item.setForeground(QColor("#FFD54F"))
                    elif tag == "unskilled": item.setForeground(QColor("white"))
                    elif tag == "inactive": item.setForeground(QColor(TEXT_MUTED))
                self.setItem(r_idx, c_idx, item)
        self.setUpdatesEnabled(True)    # flush all repaints at once

class FetchThread(QThread):
    result_ready = pyqtSignal(object)
    error_ready = pyqtSignal(Exception)
    def __init__(self, fetch_fn):
        super().__init__()
        self.fetch_fn = fetch_fn
    def run(self):
        try:
            res = self.fetch_fn()
            self.result_ready.emit(res)
        except Exception as e:
            self.error_ready.emit(e)
        finally:
            # Fix #14: close the thread-local SQLite connection to avoid file-handle leaks
            close_thread_conn()

# ══════════════════════════════════════════════════════════════════════════════
class PayrollApp(QMainWindow):
    backup_sync_signal = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self._active_threads = set()   # Fix #10: set instead of list for safe discard
        self._page_cache: dict = {}     # Fix #9: cache built pages to avoid full rebuild on nav
        self._nav_generation = 0        # Fix #1: invalidate in-flight renders on navigation
        self.backup_sync_signal.connect(self._update_backup_label)
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION} — Professional Payroll Management")
        self.resize(1300, 800)
        self.setMinimumSize(1050, 650)
        self.setStyleSheet(QSS)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self._build_sidebar()
        self._build_main_area()

        # LAN sync: discover role before init_db so DB path is resolved first
        from schema import DB_PATH as _local_db_path
        self._lan_role   = "detecting"
        self._lan_peer   = None
        self._backup_mgr = None   # created in _finish_init after path is resolved
        self._lan_sync   = LanSync(_local_db_path, self._on_lan_role_decided)
        self._lan_sync.start()
        self._show_detecting_overlay()

    def closeEvent(self, event):
        self._lan_sync.stop()
        if self._backup_mgr is not None:
            self._backup_mgr.stop()
        event.accept()

    # ── LAN sync callbacks ────────────────────────────────────────────────────

    def _on_lan_role_decided(self, role: str, db_path: str, peer_name: str | None):
        """Called from the LanSync background thread when role is negotiated."""
        from schema import set_active_db_path
        set_active_db_path(db_path)
        self._lan_role = role
        self._lan_peer = peer_name
        # init_db must run on the main thread via Qt's queued connection
        QMetaObject.invokeMethod(
            self, "_finish_init", Qt.ConnectionType.QueuedConnection
        )

    @pyqtSlot()
    def _finish_init(self):
        """Runs on the main thread: initialises DB, starts backup manager, navigates home."""
        from schema import get_active_db_path
        from database import init_db
        db = get_active_db_path()
        # Seed only when this PC owns the DB (not when connecting to host's DB)
        init_db(db, seed=(self._lan_role != "client"))
        self._backup_mgr = BackupManager(db_path=db, on_sync=self._on_backup_sync)
        self._backup_mgr.start()
        def _prewarm():
            try:
                get_all_workers(); get_skill_wages_dict(); get_all_units(); get_config()
            except Exception:
                pass
        threading.Thread(target=_prewarm, daemon=True).start()
        self._navigate("dashboard")
        self._update_sync_badge()

    def _show_detecting_overlay(self):
        """Show a subtle status message while LAN role is being determined."""
        self.set_message("🔍 Detecting network sync… (up to 3 s)", ACCENT)

    def _update_sync_badge(self):
        """Update the sync status label in the sidebar footer."""
        if not hasattr(self, '_sync_lbl') or self._sync_lbl is None:
            return
        role = self._lan_role
        peer = self._lan_peer
        if role == "host":
            self._sync_lbl.setText("🟢 Sync: Hosting")
            self._sync_lbl.setStyleSheet(
                f"color: {SUCCESS}; font-size: 11px; padding: 2px 8px;"
            )
            self._sync_lbl.setToolTip(
                "This PC is hosting the shared database.\n"
                "Other PCs on the LAN connect to this one."
            )
        elif role == "client":
            self._sync_lbl.setText(f"🔵 Sync: {peer or 'Host PC'}")
            self._sync_lbl.setStyleSheet(
                f"color: {ACCENT}; font-size: 11px; padding: 2px 8px;"
            )
            self._sync_lbl.setToolTip(
                f"Connected to shared database on {peer}.\n"
                "Changes sync in real time."
            )
        else:
            self._sync_lbl.setText("⚪ Sync: Offline")
            self._sync_lbl.setStyleSheet(
                f"color: {TEXT_MUTED}; font-size: 11px; padding: 2px 8px;"
            )
            self._sync_lbl.setToolTip(
                "No other PayrollPro PC found on the network.\n"
                "Running in standalone mode."
            )

    def _on_backup_sync(self, status: str, timestamp: str):
        self.backup_sync_signal.emit(status, timestamp)

    def _update_backup_label(self, status: str, timestamp: str):
        if "Error" in status or "⚠" in status:
            self.backup_lbl.setText(f"  🔴 Backup: {timestamp}  ")
            self.backup_lbl.setStyleSheet(f"color: {DANGER};")
        else:
            self.backup_lbl.setText(f"  🟢 Backup: {timestamp}  ")
            self.backup_lbl.setStyleSheet(f"color: {SUCCESS};")

    def _build_sidebar(self):
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(230)
        sl = QVBoxLayout(self.sidebar)
        sl.setContentsMargins(0, 0, 0, 0)
        
        logo = QFrame()
        logo.setStyleSheet(f"background-color: {GLAS};")
        ll = QHBoxLayout(logo)
        ll.setContentsMargins(18, 22, 18, 18)
        ll.addWidget(QLabel("<span style='font-size:30px;'>💼</span>"))
        b_info = QVBoxLayout()
        t = QLabel("PayrollPro")
        t.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {TEXT_PRIMARY};")
        b_info.addWidget(t)
        s = QLabel("Enterprise Edition")
        s.setStyleSheet(f"font-size: 10px; color: {ACCENT};")
        b_info.addWidget(s)
        ll.addLayout(b_info)
        ll.addStretch()
        sl.addWidget(logo)
        
        sl.addWidget(self._h_line(CARD_BORDER))
        
        nav_frame = QFrame()
        nl = QVBoxLayout(nav_frame)
        nl.setContentsMargins(10, 14, 10, 0)
        nav = [
            ("Dashboard",      "📊", "dashboard"),
            ("Attendance",     "📋", "attendance"),
            ("Workers",        "👷", "workers"),
            ("Units",          "🏢", "units"),
            ("Wage Rates",     "💰", "wages"),
            ("Payroll",        "🧾", "payroll"),
            ("Generate Slips", "📄", "slips"),
            ("Settings",       "⚙️",  "settings"),
        ]
        self._nav_buttons = {}
        for text, icon, key in nav:
            btn = SidebarButton(text, icon, key)
            btn.clicked.connect(lambda checked, k=key: self._navigate(k))
            nl.addWidget(btn)
            self._nav_buttons[key] = btn
            
        sl.addWidget(nav_frame)
        sl.addStretch()
        sl.addWidget(self._h_line(CARD_BORDER))
        
        # LAN sync status badge
        self._sync_lbl = QLabel("🔍 Detecting...")
        self._sync_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 11px; padding: 2px 8px;"
        )
        self._sync_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sl.addWidget(self._sync_lbl)

        foot = QFrame()
        foot.setStyleSheet("background-color: #191932;")
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(16, 10, 16, 14)
        f1 = QLabel("🟢 Zero-Cost Payroll System")
        f1.setStyleSheet(f"font-size: 10px; font-weight: bold; color: {SUCCESS};")
        fl.addWidget(f1)
        f2 = QLabel("Python • SQLite • 2026")
        f2.setStyleSheet(f"font-size: 10px; color: {TEXT_MUTED};")
        fl.addWidget(f2)
        sl.addWidget(foot)

        self.main_layout.addWidget(self.sidebar)

    def _h_line(self, color):
        f = QFrame(); f.setFixedHeight(1); f.setStyleSheet(f"background-color: {color};")
        return f

    def _build_main_area(self):
        v = QVBoxLayout()
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        
        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)
        
        # Status Bar
        sb = QFrame()
        sb.setFixedHeight(30)
        sb.setStyleSheet(f"background-color: {SIDEBAR_BG};")
        sbl = QHBoxLayout(sb)
        sbl.setContentsMargins(0, 0, 0, 0)
        
        acc = QFrame(); acc.setFixedWidth(3); acc.setStyleSheet(f"background-color: {ACCENT};")
        sbl.addWidget(acc)
        
        self.status_lbl = QLabel("  Ready")
        self.status_lbl.setStyleSheet(f"font-size: 10px; color: {TEXT_MUTED};")
        sbl.addWidget(self.status_lbl)
        sbl.addStretch()
        
        s_info = QLabel(f"PayrollPro v2.1  •  {os.path.abspath(DB_PATH)}  ")
        s_info.setStyleSheet(f"font-size: 10px; color: {TEXT_MUTED};")
        sbl.addWidget(s_info)
        
        self.backup_lbl = QLabel("  🔄 Backup: Starting…  ")
        self.backup_lbl.setStyleSheet(f"font-size: 10px; color: {TEXT_MUTED};")
        sbl.addWidget(self.backup_lbl)
        
        v.addWidget(sb)
        self.main_layout.addLayout(v, 1)

    def set_message(self, msg: str, color: str = TEXT_MUTED, auto_clear: bool = True):
        self.status_lbl.setText(f"  {msg}")
        self.status_lbl.setStyleSheet(f"font-size: 10px; color: {color};")
        if auto_clear and color != DANGER:
            QTimer.singleShot(4000, lambda: self.set_message("Ready", TEXT_MUTED, False))

    def _navigate(self, key):
        self._nav_generation += 1          # Fix #1: invalidate all in-flight renders
        for k, btn in self._nav_buttons.items():
            btn.set_active(k == key)

        # Fix #4: serve from page cache to avoid full rebuild on every nav click
        if key in self._page_cache:
            cached_page = self._page_cache[key]
            try:
                cached_page.isWidgetType()   # Fix #1: check not deleted
                if self.stack.indexOf(cached_page) == -1:
                    self.stack.addWidget(cached_page)
                self.stack.setCurrentWidget(cached_page)
                self.set_message(f"Viewing: {key.replace('_',' ').title()}")
                return
            except RuntimeError:
                del self._page_cache[key]   # stale cache entry — rebuild

        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)

        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa_content = QWidget()
        sa.setWidget(sa_content)
        self.page_layout = QVBoxLayout(sa_content)
        self.page_layout.setContentsMargins(0, 0, 0, 0)
        self.page_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        pl.addWidget(sa)

        self.stack.addWidget(page)
        self._page_cache[key] = page   # Fix #4: cache the built page

        {"dashboard": self._page_dashboard, "attendance": self._page_attendance,
         "workers": self._page_workers, "units": self._page_units,
         "wages": self._page_wages, "slips": self._page_slips,
         "payroll": self._page_payroll,
         "settings": self._page_settings}.get(key, lambda l: None)(self.page_layout)

        self.set_message(f"Viewing: {key.replace('_',' ').title()}")

    def _async_load(self, fetch_fn, render_fn):
        generation = self._nav_generation          # Fix #1: capture at dispatch time
        def guarded_render(result):
            if self._nav_generation != generation:
                return                             # page was navigated away — discard
            try:
                render_fn(result)
            except RuntimeError:
                pass                               # widget deleted between check and render
        thread = FetchThread(fetch_fn)
        thread.result_ready.connect(guarded_render)
        thread.error_ready.connect(lambda e: self.set_message(f"⚠️ Load error: {e}", DANGER))
        thread.finished.connect(lambda t=thread: self._active_threads.discard(t))
        self._active_threads.add(thread)   # Fix #10: add instead of append
        thread.start()

    # ══════════════════════════════════════════════════════════════════════
    #   DASHBOARD
    # ══════════════════════════════════════════════════════════════════════
    def _page_dashboard(self, layout):
        _page_header(layout, "📊  Payroll Dashboard", "Overview of payroll calculations for the selected period")
        
        ctrl = QFrame(); ctrl.setObjectName("surface2")
        cl = QHBoxLayout(ctrl); cl.setContentsMargins(16, 10, 16, 10)
        cl.addWidget(QLabel("<b>Month:</b>"))
        m_cb = QComboBox(); m_cb.addItems(month_options()); m_cb.setFixedWidth(140); cl.addWidget(m_cb)
        cl.addSpacing(20)
        cl.addWidget(QLabel("<b>Unit:</b>"))
        u_cb = QComboBox(); u_cb.addItems(_unit_filter_list()); u_cb.setFixedWidth(140); cl.addWidget(u_cb)
        cl.addStretch()
        
        exp_btn = QPushButton("📤 Export Yearly Stats")
        exp_btn.setStyleSheet(f"background-color: {SURFACE_3};")
        def export_yearly():
            import datetime
            cur_year = m_cb.currentText()[:4] if m_cb.currentText() else str(datetime.datetime.now().year)
            year, ok = QInputDialog.getText(self, "Export Yearly Stats", "Enter Year (YYYY):", text=cur_year)
            if not ok or not year.strip(): return
            year = year.strip()

            fp, _ = QFileDialog.getSaveFileName(self, "Save Yearly Stats", f"Yearly_Stats_{year}.csv", "CSV (*.csv)")
            if not fp: return

            self.set_message("⏳ Generating yearly stats...", ACCENT)

            def do_export():
                months = [m for m in get_months_with_data() if m.startswith(year)]
                months.sort()
                if not months: return f"No data found for year {year}"
                cfg = get_config(); sw = get_skill_wages_dict()
                rows = [["Month", "Total Workers", "Total Gross", "Total EPF", "Total ESI", "Total Net Pay"]]
                for m in months:
                    workers, att_dict = get_workers_and_attendance(m)
                    results, _ = calculate_payroll(workers, sw, list(att_dict.values()), m, cfg)
                    s = payroll_summary(results)
                    rows.append([m, str(s["total_workers"]), str(s["total_gross"]), str(s["total_epf"]), str(s["total_esi"]), str(s["total_net"])])
                import csv
                with open(fp, "w", newline="", encoding="utf-8-sig") as f:
                    csv.writer(f).writerows(rows)
                return f"Saved yearly stats to {fp}"

            def _on_export_done(msg): self.set_message(f"✅ {msg}" if "Saved" in msg else f"⚠️ {msg}", SUCCESS if "Saved" in msg else WARNING_CLR)
            def _on_export_error(e): self.set_message(f"⚠️ Failed: {e}", WARNING_CLR)

            exp_thread = FetchThread(do_export)
            exp_thread.result_ready.connect(_on_export_done)
            exp_thread.error_ready.connect(_on_export_error)
            exp_thread.finished.connect(lambda t=exp_thread: self._active_threads.discard(t))
            self._active_threads.add(exp_thread)
            exp_thread.start()

        exp_btn.clicked.connect(export_yearly)
        cl.addWidget(exp_btn)
        
        ref_btn = QPushButton("🔄 Refresh")
        ref_btn.setStyleSheet(f"background-color: {SURFACE_3};")
        cl.addWidget(ref_btn)
        
        cw = QWidget()
        cwl = QHBoxLayout(cw); cwl.setContentsMargins(28, 4, 28, 14)
        cwl.addWidget(ctrl)
        layout.addWidget(cw)
        
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 0, 28, 20)
        layout.addWidget(content)

        def refresh():
            sync_combo(m_cb, month_options())
            sync_combo(u_cb, _unit_filter_list())
            while content_layout.count():
                it = content_layout.takeAt(0)
                if it.widget(): it.widget().deleteLater()
            
            lbl = QLabel("⏳  Loading..."); content_layout.addWidget(lbl)
            
            month = m_cb.currentText()
            unit = u_cb.currentText()
            
            def _fetch():
                workers, att_dict = get_workers_and_attendance(month)
                sw = get_skill_wages_dict()
                return workers, sw, list(att_dict.values()), month, unit
            
            def _render(data):
                # Guard: bail out if the user navigated away before fetch completed
                try:
                    content_layout.count()
                except RuntimeError:
                    return

                workers, sw, att, month, unit = data
                while content_layout.count():
                    it = content_layout.takeAt(0)
                    if it.widget(): it.widget().deleteLater()
                    
                if unit != "All": workers = [w for w in workers if w.unit == unit]
                results, warnings = calculate_payroll(workers, sw, att, month, get_config())
                
                if warnings:
                    wf = QFrame(); wf.setStyleSheet("background-color: #3D2F00; border-radius: 8px;")
                    wfl = QVBoxLayout(wf); wfl.addWidget(QLabel(f"⚠️ {len(warnings)} warning(s): {warnings[0]}", styleSheet=f"color: {WARNING_CLR};"))
                    content_layout.addWidget(wf)
                    
                if not results:
                    ef = QFrame(); ef.setObjectName("card")
                    efl = QVBoxLayout(ef); efl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    efl.addWidget(QLabel("📭", styleSheet="font-size: 40px;"), alignment=Qt.AlignmentFlag.AlignCenter)
                    efl.addWidget(QLabel("No payroll data for this period", styleSheet=f"color: {TEXT_SECONDARY}; font-size: 15px; font-weight: bold;"), alignment=Qt.AlignmentFlag.AlignCenter)
                    content_layout.addWidget(ef)
                    return
                
                s = payroll_summary(results)
                
                # ── Pie chart: unit-wise net pay ───────────────────────────
                unit_totals = {}
                for r in results:
                    unit_totals[r.unit or "Unassigned"] = unit_totals.get(r.unit or "Unassigned", 0) + r.net_pay

                chart_w = QFrame(); chart_w.setObjectName("card")
                chart_l = QVBoxLayout(chart_w)
                chart_l.setContentsMargins(16, 12, 16, 12)
                chart_l.addWidget(QLabel("🥧  Unit-wise Net Pay", styleSheet="font-size: 14px; font-weight: bold; color: #7F9DB9;"))
                pie = PieChartWidget(unit_totals)
                chart_l.addWidget(pie)
                content_layout.addWidget(chart_w)

                # ── Action buttons row ─────────────────────────────────────
                snap_lay = QHBoxLayout()
                snap_btn = QPushButton("💾 Snapshot / Save Payroll Run")
                snap_btn.setStyleSheet(f"background-color: {SUCCESS}; height: 32px; font-weight: bold;")
                def save_snapshot():
                    import json, datetime
                    from database import save_payroll_run
                    rj = json.dumps([r.to_dict() for r in results])
                    save_payroll_run(month, datetime.datetime.now().isoformat(), s["total_gross"], s["total_net"], s["total_workers"], rj)
                    self.set_message("✅ Payroll run snapshot saved!", SUCCESS)
                snap_btn.clicked.connect(save_snapshot)

                hist_btn = QPushButton("📚 View Audit Logs")
                hist_btn.setStyleSheet("height: 32px;")
                hist_btn.clicked.connect(self._show_audit_logs)

                pr_btn = QPushButton("🧾 Open Payroll Breakdown")
                pr_btn.setStyleSheet(f"background-color: {SURFACE_3}; height: 32px;")
                pr_btn.clicked.connect(lambda: self._navigate("payroll"))

                snap_lay.addWidget(hist_btn)
                snap_lay.addWidget(pr_btn)
                snap_lay.addStretch()
                snap_lay.addWidget(snap_btn)
                content_layout.addLayout(snap_lay)

                # ── Primary KPI cards ──────────────────────────────────────
                cards = QWidget()
                cl = QHBoxLayout(cards)
                cl.setContentsMargins(0, 0, 0, 0)
                cl.addWidget(MetricCard("Workers", s["total_workers"], ACCENT, "👷"))
                cl.addWidget(MetricCard("Total Gross", fmt_inr(s["total_gross"]), "#26A69A", "💰"))
                cl.addWidget(MetricCard("Total EPF", fmt_inr(s["total_epf"]), WARNING_CLR, "🏦"))
                cl.addWidget(MetricCard("Total ESI", fmt_inr(s["total_esi"]), "#AB47BC", "🏥"))
                cl.addWidget(MetricCard("Total Net Pay", fmt_inr(s["total_net"]), SUCCESS, "✅"))
                content_layout.addWidget(cards)

                # ── Secondary stats row ────────────────────────────────────
                avg_net = s["total_net"] / max(s["total_workers"], 1)
                top_r = max(results, key=lambda r: r.net_pay, default=None)
                zero_pay = sum(1 for r in results if r.net_pay <= 0)
                total_ded = s["total_epf"] + s["total_esi"]
                ded_pct = (total_ded / max(s["total_gross"], 1)) * 100
                skilled_c   = sum(1 for r in results if r.skill_category == "Skilled")
                semi_c      = sum(1 for r in results if r.skill_category == "Semi-Skilled")
                unskilled_c = sum(1 for r in results if r.skill_category == "Unskilled")

                stats2 = QWidget()
                s2l = QHBoxLayout(stats2); s2l.setContentsMargins(0, 0, 0, 0)
                s2l.addWidget(MetricCard("Avg Net Pay", fmt_inr(avg_net), "#38BDF8", "📈"))
                s2l.addWidget(MetricCard("Top Earner", top_r.worker_name.split()[0] if top_r else "—", "#A78BFA", "🏆"))
                s2l.addWidget(MetricCard("Zero-Pay Workers", zero_pay, DANGER, "⚠️"))
                s2l.addWidget(MetricCard("Deduction %", f"{ded_pct:.1f}%", WARNING_CLR, "🔻"))
                content_layout.addWidget(stats2)

                stats3 = QWidget()
                s3l = QHBoxLayout(stats3); s3l.setContentsMargins(0, 0, 0, 0)
                s3l.addWidget(MetricCard("Skilled", skilled_c, "#22C55E", "🎓"))
                s3l.addWidget(MetricCard("Semi-Skilled", semi_c, "#F59E0B", "🔧"))
                s3l.addWidget(MetricCard("Unskilled", unskilled_c, "#94A3C4", "👤"))
                s3l.addWidget(MetricCard("Active Units", len(unit_totals), "#FB923C", "🏢"))
                content_layout.addWidget(stats3)
                
            self._async_load(_fetch, _render)
            
        m_cb.currentTextChanged.connect(refresh)
        u_cb.currentTextChanged.connect(refresh)
        ref_btn.clicked.connect(refresh)
        refresh()

    # ══════════════════════════════════════════════════════════════════════
    #   ATTENDANCE
    # ══════════════════════════════════════════════════════════════════════
    def _page_attendance(self, layout):
        _page_header(layout, "📋  Attendance & Earnings Entry", "Enter daily attendance and manage per-worker allowances / deductions")
        tabs = QTabWidget()
        cw = QWidget(); cwl = QVBoxLayout(cw); cwl.setContentsMargins(28, 0, 28, 20); cwl.addWidget(tabs); layout.addWidget(cw, 1)
        
        tab_man = QWidget(); tm_l = QVBoxLayout(tab_man)
        tab_csv = QWidget(); tc_l = QVBoxLayout(tab_csv)
        tabs.addTab(tab_man, "✍️ Manual Entry")
        tabs.addTab(tab_csv, "📁 CSV Import")
        
        self._build_att_manual(tm_l)
        self._build_att_csv(tc_l)

    def _build_att_manual(self, layout):
        from PyQt6.QtWidgets import QCheckBox, QScrollArea

        # ── Control bar ──────────────────────────────────────────────────
        ctrl = QWidget(); cl = QHBoxLayout(ctrl); cl.setContentsMargins(12, 12, 12, 8)
        cl.addWidget(QLabel("<b>Month:</b>"))
        m_cb = QComboBox(); m_cb.addItems(month_options()); m_cb.setFixedWidth(140); cl.addWidget(m_cb)
        cl.addSpacing(20)
        cl.addWidget(QLabel("<b>Unit:</b>"))
        u_cb = QComboBox(); u_cb.addItems(_unit_filter_list()); u_cb.setFixedWidth(140); cl.addWidget(u_cb)
        cl.addSpacing(20)
        s_ent = QLineEdit(); s_ent.setPlaceholderText("Search Name/ID..."); s_ent.setFixedWidth(140); cl.addWidget(s_ent)
        cl.addStretch()
        layout.addWidget(ctrl)

        # ── Scrollable worker list ────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # Fix #8: removed the original list_widget/list_layout variables (they were
        # reassigned inside _do_refresh with nonlocal, which was vestigial/confusing).
        # The inner _do_refresh creates and swaps the widget directly on the scroll area.
        _list_container = QWidget()
        _list_container_layout = QVBoxLayout(_list_container)
        _list_container_layout.setSpacing(3)
        _list_container_layout.setContentsMargins(4, 4, 4, 4)
        scroll.setWidget(_list_container)
        layout.addWidget(scroll, 1)

        self._att_workers = []
        _row_data = []          # Fix #7: per-refresh row data
        _refresh_token = [0]    # Fix #7: incremented on each refresh() call
        _last_worker_ids = []   # Fix #1: track last rendered set to avoid full rebuild

        # ── Helpers ───────────────────────────────────────────────────────
        def _le(val, w=58):
            e = QLineEdit(str(val))
            e.setFixedWidth(w)
            e.setStyleSheet(
                f"background-color: {SURFACE_2}; border: 1px solid {CARD_BORDER}; "
                f"border-radius: 3px; padding: 2px 4px; color: {TEXT_PRIMARY}; font-size: 11px;"
            )
            return e

        def _lbl(text, width=None, muted=True):
            lb = QLabel(str(text))
            lb.setStyleSheet(
                f"color: {TEXT_SECONDARY if muted else TEXT_PRIMARY}; font-size: 11px; "
                "background: transparent; border: none;"
            )
            if width: lb.setFixedWidth(width)
            return lb

        def _mini_lbl(text):
            lb = QLabel(text)
            lb.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 9px; background: transparent; border: none;")
            return lb

        # ── Debounce timer for search ─────────────────────────────────────
        _att_search_timer = QTimer()
        _att_search_timer.setSingleShot(True)
        _att_search_timer.setInterval(300)

        # ── Card builder (Fix #2+#3) ──────────────────────────────────────
        def _build_card(w, att):
            """Create and return the card QFrame for one worker row."""
            card = QFrame()
            card.setStyleSheet(
                f"QFrame {{ background-color: {SURFACE_3}; border-radius: 6px; "
                f"border: 1px solid {CARD_BORDER}; }}"
            )
            card_l = QVBoxLayout(card)
            card_l.setContentsMargins(4, 3, 4, 3)
            card_l.setSpacing(0)

            # ── Compact top row ────────────────────────────────────────
            top = QWidget()
            top.setStyleSheet("background: transparent; border: none;")
            tl = QHBoxLayout(top)
            tl.setContentsMargins(2, 2, 2, 2)
            tl.setSpacing(6)

            arrow = QPushButton("\u25b6")
            arrow.setFixedSize(22, 22)
            arrow.setToolTip("Expand extras: DA, HRA, CCA, Bonus, Arrears, Adv Repay, Fine, Loss/Dmg, Other Ded")
            arrow.setStyleSheet(
                f"QPushButton {{ background-color: {SURFACE_2}; color: {ACCENT}; "
                f"border-radius: 4px; font-size: 9px; font-weight: bold; border: 1px solid {CARD_BORDER}; }}"
                f"QPushButton:hover {{ background-color: {ACCENT}; color: white; }}"
            )
            arrow.setCursor(Qt.CursorShape.PointingHandCursor)
            tl.addWidget(arrow)

            tl.addWidget(_lbl(w.worker_id, 62, muted=False))
            tl.addWidget(_lbl(w.name, 150, muted=False))
            tl.addWidget(_lbl(w.unit, 82))
            tl.addWidget(_lbl(w.designation or w.skill_category, 110))

            tl.addWidget(_lbl("Days", 28))
            e_days = _le(att.days_present, 56); tl.addWidget(e_days)
            tl.addWidget(_lbl("OT", 18))
            e_ot   = _le(att.overtime_hours, 50); tl.addWidget(e_ot)

            from PyQt6.QtWidgets import QCheckBox as _QCB
            esi_cb = _QCB("ESI")
            esi_cb.setChecked(bool(att.esi_applicable))
            esi_cb.setStyleSheet(
                f"color: {TEXT_SECONDARY}; font-size: 10px; background: transparent; "
                "border: none; margin-left: 6px;"
            )
            tl.addWidget(esi_cb)
            tl.addStretch()
            card_l.addWidget(top)

            # ── Expandable extras row (hidden by default) ──────────────
            expand = QFrame()
            expand.setVisible(False)
            expand.setStyleSheet(
                f"background-color: {SURFACE_2}; border-top: 1px solid {CARD_BORDER}; "
                "border-radius: 0; border-bottom-left-radius: 5px; border-bottom-right-radius: 5px;"
            )
            el = QHBoxLayout(expand)
            el.setContentsMargins(30, 5, 8, 5)
            el.setSpacing(10)

            def _field(lbl_txt, val):
                vbox = QVBoxLayout(); vbox.setSpacing(1)
                vbox.addWidget(_mini_lbl(lbl_txt))
                e = _le(val, 65)
                vbox.addWidget(e)
                el.addLayout(vbox)
                return e

            e_da      = _field("DA",        att.da)
            e_hra     = _field("HRA",       att.hra)
            e_cca     = _field("CCA",       att.cca)
            e_bonus   = _field("Bonus",     att.bonus)
            e_arrears = _field("Arrears",   att.arrears)
            e_advrep  = _field("Adv Repay", att.advance_repayment)
            e_fine    = _field("Fine",      att.fine)
            e_loss    = _field("Loss/Dmg",  att.loss_damages)
            e_other   = _field("Other Ded", att.other_deductions)
            el.addStretch()
            card_l.addWidget(expand)

            def _toggle(_, exp=expand, btn=arrow):
                vis = not exp.isVisible()
                exp.setVisible(vis)
                btn.setText("\u25bc" if vis else "\u25b6")
            arrow.clicked.connect(_toggle)

            row = {
                "wid": w.worker_id,
                "days": e_days, "ot": e_ot, "esi": esi_cb,
                "da": e_da, "hra": e_hra, "cca": e_cca,
                "bonus": e_bonus, "arrears": e_arrears, "advrep": e_advrep,
                "fine": e_fine, "loss": e_loss, "other": e_other,
            }
            return card, row

        # ── Build worker rows ─────────────────────────────────────────────
        def _do_refresh(workers, existing, token, month_snap):
            """
            Fix #1: Runs on the main thread.
            Fix #3: Renders cards in batches using QTimer.singleShot(0) to
                    yield between batches and keep the UI responsive.
            Fix #7: Validates token before touching _row_data.
            Fix #8: No more vestigial nonlocal list_layout/list_widget.
            """
            nonlocal _row_data, _last_worker_ids

            # Fix #7: abort if a newer refresh has already started
            if token != _refresh_token[0]:
                return

            new_wids = [w.worker_id for w in workers]

            # Fix #1: skip full rebuild when the worker list hasn't changed
            if new_wids == _last_worker_ids and _row_data:
                # Just update existing field values without destroying widgets
                existing_map = {d["wid"]: d for d in _row_data}
                for w in workers:
                    att = existing.get(w.worker_id, AttendanceRecord(w.worker_id, month_snap))
                    d = existing_map.get(w.worker_id)
                    if d:
                        d["days"].setText(str(att.days_present))
                        d["ot"].setText(str(att.overtime_hours))
                        d["esi"].setChecked(bool(att.esi_applicable))
                        d["da"].setText(str(att.da))
                        d["hra"].setText(str(att.hra))
                        d["cca"].setText(str(att.cca))
                        d["bonus"].setText(str(att.bonus))
                        d["arrears"].setText(str(att.arrears))
                        d["advrep"].setText(str(att.advance_repayment))
                        d["fine"].setText(str(att.fine))
                        d["loss"].setText(str(att.loss_damages))
                        d["other"].setText(str(att.other_deductions))
                self._att_workers = workers
                return

            # Full rebuild — clear existing widgets
            _row_data = []
            _last_worker_ids = []
            while _list_container_layout.count():
                it = _list_container_layout.takeAt(0)
                if it.widget(): it.widget().deleteLater()

            # Fix #3: batch card insertion to yield to the event loop between batches
            BATCH_SIZE = 15
            worker_batches = [workers[i:i+BATCH_SIZE] for i in range(0, len(workers), BATCH_SIZE)]

            def _insert_batch(batch_idx):
                if token != _refresh_token[0]:
                    return  # Fix #7: abort if outdated
                if batch_idx >= len(worker_batches):
                    # All done — add stretch and finalise
                    _list_container_layout.addStretch()
                    _last_worker_ids[:] = [w.worker_id for w in workers]
                    return
                batch = worker_batches[batch_idx]
                for w in batch:
                    att = existing.get(w.worker_id, AttendanceRecord(w.worker_id, month_snap))
                    card, row = _build_card(w, att)
                    _list_container_layout.addWidget(card)
                    _row_data.append(row)
                QTimer.singleShot(0, lambda bi=batch_idx+1: _insert_batch(bi))

            _insert_batch(0)
            self._att_workers = workers

        def refresh():
            nonlocal _last_worker_ids
            _refresh_token[0] += 1          # Fix #7: invalidate any in-flight render
            token = _refresh_token[0]
            # Reset last_worker_ids so next _do_refresh always checks fresh
            sync_combo(m_cb, month_options())
            sync_combo(u_cb, _unit_filter_list())
            month = m_cb.currentText()
            unit  = u_cb.currentText()
            q     = s_ent.text().strip().lower()
            month_snap = month   # Fix #6 insurance: capture month at fetch time

            def _fetch():
                workers  = get_all_workers()
                existing = {a.worker_id: a for a in get_attendance(month_snap)}
                if unit != "All":
                    workers = [w for w in workers if w.unit == unit]
                if q:
                    workers = [w for w in workers if q in w.name.lower() or q in w.worker_id.lower()]
                return workers, existing, token, month_snap

            self._async_load(_fetch, lambda data: _do_refresh(*data))

        # ── Save ─────────────────────────────────────────────────────────
        def save_all():
            month = m_cb.currentText()

            # Fix #7: validate that displayed rows match the current month
            if not _row_data:
                self.set_message("⚠️ Nothing to save — try refreshing first.", WARNING_CLR)
                return

            existing_db = {a.worker_id: a for a in get_attendance(month)}
            records = []
            def _f(e):
                try: return float(e.text())
                except: return 0.0
            for d in _row_data:
                att = existing_db.get(d["wid"], AttendanceRecord(d["wid"], month))
                att.days_present      = _f(d["days"])
                att.overtime_hours    = _f(d["ot"])
                att.da                = _f(d["da"])
                att.hra               = _f(d["hra"])
                att.cca               = _f(d["cca"])
                att.bonus             = _f(d["bonus"])
                att.arrears           = _f(d["arrears"])
                att.advance_repayment = _f(d["advrep"])
                att.fine              = _f(d["fine"])
                att.loss_damages      = _f(d["loss"])
                att.other_deductions  = _f(d["other"])
                att.esi_applicable    = d["esi"].isChecked()
                records.append(att)
            bulk_upsert_attendance(records)
            _invalidate_month_options_cache()   # Fix #5: refresh month list after save
            self.set_message(f"✅ Saved {len(records)} records for {month}", SUCCESS)

        m_cb.currentTextChanged.connect(refresh)
        u_cb.currentTextChanged.connect(refresh)
        # Debounce: only fire refresh 300 ms after the user stops typing
        _att_search_timer.timeout.connect(refresh)
        s_ent.textChanged.connect(lambda: _att_search_timer.start())

        btn = QPushButton("💾 Save All Attendance")
        btn.setStyleSheet(f"background-color: {SUCCESS}; height: 30px;")
        btn.clicked.connect(save_all)
        layout.addWidget(btn)

        refresh()

    def _build_att_csv(self, layout):
        layout.addWidget(QLabel("Upload a CSV to import attendance data in bulk.", styleSheet=f"color: {TEXT_SECONDARY};"))
        info = QFrame(); info.setObjectName("card"); il = QVBoxLayout(info)
        il.addWidget(QLabel("<b>Supported columns:</b>"))
        il.addWidget(QLabel("worker_id, days_present, da, hra, cca, overtime_hours,\nbonus, arrears, advance_repayment, epf_override, esi_override ...", styleSheet=f"color: {TEXT_MUTED}; font-size: 10px;"))
        layout.addWidget(info)
        
        def dl():
            workers = get_all_workers()
            path, _ = QFileDialog.getSaveFileName(self, "Save Template", "attendance_template.csv", "CSV (*.csv)")
            if path:
                with open(path, "w", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["worker_id","days_present","da","bonus","overtime_hours","advance_repayment"])
                    for wr in workers: w.writerow([wr.worker_id, 0, 0, 0, 0, 0])
        b1 = QPushButton("📥 Download Template")
        b1.setStyleSheet(f"background-color: {SURFACE_3};")
        b1.clicked.connect(dl)
        b1.setFixedWidth(160)
        layout.addWidget(b1)
        
        ctrl = QWidget(); cl = QHBoxLayout(ctrl)
        cl.addWidget(QLabel("<b>Import for Month:</b>"))
        m_cb = QComboBox(); m_cb.addItems(month_options()); cl.addWidget(m_cb)
        
        def imp():
            fp, _ = QFileDialog.getOpenFileName(self, "Open CSV", "", "CSV (*.csv)")
            if fp:
                try:
                    res = import_attendance_from_csv(fp, m_cb.currentText())
                    if res["errors"]:
                        err_path = os.path.join(os.path.dirname(fp), "import_errors.txt")
                        with open(err_path, "w") as f:
                            f.write("\n".join(res["errors"]))
                        QMessageBox.warning(self, "Import Errors", f"Imported {res['imported']} records.\nEncountered {len(res['errors'])} errors.\n\nDetails saved to: {err_path}")
                    else:
                        self.set_message(f"✅ Imported {res['imported']} records.", SUCCESS)
                    self._navigate("attendance")
                except Exception as e:
                    QMessageBox.critical(self, "Import Failed", f"An error occurred during import:\n{e}")

        b2 = QPushButton("📁 Import CSV")
        b2.clicked.connect(imp)
        cl.addWidget(b2); cl.addStretch()
        layout.addWidget(ctrl)
        layout.addStretch()

    # ══════════════════════════════════════════════════════════════════════
    #   WORKERS
    # ══════════════════════════════════════════════════════════════════════
    def _page_workers(self, layout):
        _page_header(layout, "👷  Worker Master Data", "Add, edit, or delete workers — double click a row to edit inline")
        tabs = QTabWidget()
        cw = QWidget(); cwl = QVBoxLayout(cw); cwl.setContentsMargins(28, 0, 28, 20); cwl.addWidget(tabs); layout.addWidget(cw, 1)
        
        tab_all = QWidget(); tl = QVBoxLayout(tab_all)
        tab_add = QWidget(); al = QVBoxLayout(tab_add)
        tab_csv = QWidget(); cl = QVBoxLayout(tab_csv)
        tabs.addTab(tab_all, "👥 All Workers")
        tabs.addTab(tab_add, "➕ Add New Worker")
        tabs.addTab(tab_csv, "📁 CSV Import")
        
        # All Workers
        fc = QFrame(); fc.setObjectName("surface2")
        fcl = QHBoxLayout(fc); fcl.setContentsMargins(14, 10, 14, 10)
        fcl.addWidget(QLabel("<b>Unit:</b>"))
        u_cb = QComboBox(); u_cb.addItems(_unit_filter_list()); u_cb.setFixedWidth(140); fcl.addWidget(u_cb)
        fcl.addSpacing(20)
        s_ent = QLineEdit(); s_ent.setPlaceholderText("Search by Name or ID..."); s_ent.setFixedWidth(200); fcl.addWidget(s_ent)
        fcl.addStretch()
        tl.addWidget(fc)
        
        def _db_cb(row):
            try:
                item_id = table.item(row, 1)
                item_name = table.item(row, 2)
                if not item_id or not item_name: return
                wid = item_id.text().strip()
                name = item_name.text().strip()
                if not name or not wid: return
                w_obj = get_worker_by_id(wid)
                bname_item = table.item(row, 6)
                bname = bname_item.text().strip() if bname_item else ""
                if bname.startswith("(No"): bname = ""
                
                def _get_txt(col):
                    it = table.item(row, col)
                    return it.text().strip() if it else ""
                
                upsert_worker(Worker(
                    worker_id=wid, name=name, unit=_get_txt(3),
                    skill_category=_get_txt(4),
                    designation=_get_txt(5),
                    bank_name=bname, bank_account=_get_txt(7),
                    ifsc_code=_get_txt(8),
                    uan_number=_get_txt(9),
                    esic_number=_get_txt(10),
                    joining_date=w_obj.joining_date if w_obj else "",
                    active=w_obj.active if w_obj else True))
                self.set_message(f"✅ {wid} auto-saved!", SUCCESS)
            except Exception as e:
                self.set_message(f"⚠️ Auto-save failed: {e}", DANGER)


        cols = ("Sel", "ID", "Name", "Unit", "Skill", "Designation", "Bank", "A/C", "IFSC", "UAN", "ESIC", "Status")
        widths = [30, 55, 140, 80, 80, 90, 100, 110, 95, 85, 75, 70]
        table = StyledTable(cols, widths, editable=True, db_update_cb=_db_cb, stretch_last=True)
        tl.addWidget(table, 1)
        
        act_bar = QFrame(); act_bar.setStyleSheet("background-color: #0D2A4E; border-radius: 8px;"); act_bar.setFixedHeight(42)
        abl = QHBoxLayout(act_bar)
        lbl_ab = QLabel("Bulk Actions (Use checkboxes or Shift+Click rows):"); lbl_ab.setStyleSheet(f"color: {TEXT_SECONDARY}; font-weight: bold;"); abl.addWidget(lbl_ab); abl.addStretch()
        
        def _sync_checkboxes():
            table.blockSignals(True)
            sel_rows = set(r.row() for r in table.selectionModel().selectedRows())
            for i in range(table.rowCount()):
                item = table.item(i, 0)
                if item:
                    item.setCheckState(Qt.CheckState.Checked if i in sel_rows else Qt.CheckState.Unchecked)
            table.blockSignals(False)
        table.itemSelectionChanged.connect(_sync_checkboxes)

        def _item_changed(item):
            if item.column() == 0:
                table.blockSignals(True)
                from PyQt6.QtCore import QItemSelectionModel
                idx = table.model().index(item.row(), 0)
                if item.checkState() == Qt.CheckState.Checked:
                    table.selectionModel().select(idx, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
                else:
                    table.selectionModel().select(idx, QItemSelectionModel.SelectionFlag.Deselect | QItemSelectionModel.SelectionFlag.Rows)
                table.blockSignals(False)
        table.itemChanged.connect(_item_changed)
        
        def get_selected_wids():
            wids = set()
            for i in range(table.rowCount()):
                if table.item(i, 0).checkState() == Qt.CheckState.Checked:
                    wids.add(table.item(i, 1).text())
            for r in table.selectionModel().selectedRows():
                wids.add(table.item(r.row(), 1).text())
            return list(wids)

        def bulk_toggle():
            wids = get_selected_wids()
            if wids and QMessageBox.question(self, "Bulk Toggle", f"Toggle status for {len(wids)} workers?") == QMessageBox.StandardButton.Yes:
                for wid in wids:
                    w = get_worker_by_id(wid)
                    if w.active: deactivate_worker(wid)
                    else: reactivate_worker(wid)
                refresh()
                self.set_message(f"✅ Toggled {len(wids)} workers", SUCCESS)
                
        def bulk_del():
            wids = get_selected_wids()
            if wids and QMessageBox.question(self, "Bulk Delete", f"Permanently delete {len(wids)} workers?") == QMessageBox.StandardButton.Yes:
                for wid in wids: delete_worker(wid)
                refresh()
                self.set_message(f"✅ Deleted {len(wids)} workers", SUCCESS)
                
        b_tgl = QPushButton("⏸ Bulk Toggle"); b_tgl.setStyleSheet(f"background-color: {WARNING_CLR};"); b_tgl.clicked.connect(bulk_toggle); abl.addWidget(b_tgl)
        b_del = QPushButton("🗑️ Bulk Delete"); b_del.setStyleSheet(f"background-color: {DANGER};"); b_del.clicked.connect(bulk_del); abl.addWidget(b_del)
        act_bar.setVisible(True)
        tl.addWidget(act_bar)

        # Add Worker
        form = QFrame(); form.setObjectName("card")
        fl = QVBoxLayout(form); fl.setContentsMargins(16, 16, 16, 16)
        
        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("New Worker Registration", styleSheet="font-size: 15px; font-weight: bold;"))
        btn_clr = QPushButton("🧹 Clear"); btn_clr.setStyleSheet(f"background-color: {SURFACE_3};"); hdr.addWidget(btn_clr, alignment=Qt.AlignmentFlag.AlignRight)
        fl.addLayout(hdr)
        
        grid = QWidget(); gl = QVBoxLayout(grid); gl.setContentsMargins(0, 10, 0, 10)
        def mk_row(items):
            r = QHBoxLayout()
            for l, w in items:
                v = QVBoxLayout()
                v.addWidget(QLabel(l, styleSheet=f"color: {TEXT_SECONDARY}; font-size: 10px;"))
                v.addWidget(w)
                r.addLayout(v)
            gl.addLayout(r)
            
        e_id = QLineEdit(); e_name = QLineEdit(); e_desig = QLineEdit()
        mk_row([("Worker ID *", e_id), ("Full Name *", e_name), ("Designation", e_desig)])
        
        e_unit = QComboBox(); e_unit.addItems(_unit_list())
        e_skill = QComboBox(); e_skill.addItems(SKILL_CATEGORIES)
        e_join = QLineEdit(datetime.date.today().strftime("%d/%m/%Y"))
        mk_row([("Unit *", e_unit), ("Skill Category *", e_skill), ("Joining Date", e_join)])
        
        e_bank_acc = QLineEdit(); e_bank_name = QComboBox(); e_bank_name.addItems(_bank_names())
        e_ifsc = QLineEdit()
        mk_row([("Bank Account", e_bank_acc), ("Bank Name", e_bank_name), ("IFSC", e_ifsc)])
        
        e_uan = QLineEdit(); e_esic = QLineEdit()
        mk_row([("UAN", e_uan), ("ESIC", e_esic), ("", QWidget())])
        
        fl.addWidget(grid)

        def refresh():
            sync_combo(u_cb, _unit_filter_list())
            sync_combo(e_unit, _unit_list())
            sync_combo(e_bank_name, _bank_names())
            workers = get_all_workers(active_only=False)
            filt = u_cb.currentText()
            q = s_ent.text().strip().lower()
            if filt != "All": workers = [w for w in workers if w.unit == filt]
            if q: workers = [w for w in workers if q in w.name.lower() or q in w.worker_id.lower()]
            
            tags = []
            rows = []
            for w in workers:
                rows.append(["", w.worker_id, w.name, w.unit, w.skill_category,
                             w.designation, w.bank_name, w.bank_account, w.ifsc_code,
                             w.uan_number, w.esic_number, "● Active" if w.active else "○ Inactive"])
                if not w.active: tags.append("inactive")
                elif w.skill_category == "Skilled": tags.append("skilled")
                elif "Semi" in w.skill_category: tags.append("semi")
                else: tags.append("unskilled")
            table.insert_rows(rows, tags, checkable_col=0)
            act_bar.setVisible(True)

        u_cb.currentTextChanged.connect(refresh)
        # Debounce: only fire refresh 300 ms after the user stops typing
        _wk_search_timer = QTimer()
        _wk_search_timer.setSingleShot(True)
        _wk_search_timer.setInterval(300)
        _wk_search_timer.timeout.connect(refresh)
        s_ent.textChanged.connect(lambda: _wk_search_timer.start())
        refresh()


        btn_sv = QPushButton("💾 Save Worker")
        btn_sv.setStyleSheet(f"background-color: {SUCCESS}; height: 35px;")
        
        def clr():
            for e in (e_id, e_name, e_desig, e_bank_acc, e_ifsc, e_uan, e_esic): e.clear()
        btn_clr.clicked.connect(clr)
        
        def sv():
            wid = e_id.text().strip().upper(); name = e_name.text().strip()
            if not wid or not name: return
            bname = e_bank_name.currentText()
            if bname.startswith("(No"): bname = ""
            upsert_worker(Worker(
                worker_id=wid, name=name, designation=e_desig.text().strip(),
                bank_account=e_bank_acc.text().strip(), bank_name=bname,
                ifsc_code=e_ifsc.text().strip(), uan_number=e_uan.text().strip(),
                esic_number=e_esic.text().strip(), joining_date=e_join.text().strip(),
                active=True, unit=e_unit.currentText(), skill_category=e_skill.currentText()))
            self.set_message(f"✅ Worker {wid} saved!", SUCCESS)
            clr(); refresh()
            
        btn_sv.clicked.connect(sv)
        fl.addWidget(btn_sv)
        al.addWidget(form); al.addStretch()
        
        self._build_workers_csv(cl)

    def _build_workers_csv(self, layout):
        layout.addWidget(QLabel("Upload a CSV to import new workers in bulk.", styleSheet=f"color: {TEXT_SECONDARY};"))
        info = QFrame(); info.setObjectName("card"); il = QVBoxLayout(info)
        il.addWidget(QLabel("<b>Supported columns:</b>"))
        il.addWidget(QLabel("worker_id, name, designation, bank_account, bank_name, ifsc_code,\nuan_number, esic_number, joining_date, active, unit, skill_category", styleSheet=f"color: {TEXT_MUTED}; font-size: 10px;"))
        layout.addWidget(info)
        
        def dl():
            path, _ = QFileDialog.getSaveFileName(self, "Save Template", "workers_template.csv", "CSV (*.csv)")
            if path:
                with open(path, "w", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["worker_id","name","designation","bank_account","bank_name","ifsc_code",
                                "uan_number","esic_number","joining_date","active","unit","skill_category"])
                    w.writerow(["EMP001","John Doe","Helper","123456789","SBI","SBIN0001234",
                                "100000000000","2000000000","01/01/2026","1","Unit A","Unskilled"])
        b1 = QPushButton("📥 Download Template")
        b1.setStyleSheet(f"background-color: {SURFACE_3};")
        b1.clicked.connect(dl)
        b1.setFixedWidth(160)
        layout.addWidget(b1)
        
        def imp():
            fp, _ = QFileDialog.getOpenFileName(self, "Open CSV", "", "CSV (*.csv)")
            if fp:
                try:
                    res = import_workers_from_csv(fp)
                    if res["errors"]:
                        err_path = os.path.join(os.path.dirname(fp), "import_errors.txt")
                        with open(err_path, "w") as f:
                            f.write("\n".join(res["errors"]))
                        QMessageBox.warning(self, "Import Errors", f"Imported {res['imported']} workers.\nEncountered {len(res['errors'])} errors.\n\nDetails saved to: {err_path}")
                    else:
                        self.set_message(f"✅ Imported {res['imported']} workers.", SUCCESS)
                    self._navigate("workers")
                except Exception as e:
                    QMessageBox.critical(self, "Import Failed", f"An error occurred during import:\n{e}")

                
        b2 = QPushButton("📁 Import CSV")
        b2.clicked.connect(imp)
        b2.setFixedWidth(160)
        layout.addWidget(b2)
        layout.addStretch()

    # ══════════════════════════════════════════════════════════════════════
    #   UNITS
    # ══════════════════════════════════════════════════════════════════════
    def _page_units(self, layout):
        _page_header(layout, "🏢  Unit Management", "Add, rename, or remove company units")
        cw = QWidget(); cwl = QVBoxLayout(cw); cwl.setContentsMargins(28, 0, 28, 20); layout.addWidget(cw, 1)
        
        add_card = QFrame(); add_card.setObjectName("card")
        al = QVBoxLayout(add_card); al.setContentsMargins(20, 16, 20, 16)
        al.addWidget(QLabel("➕ New Unit", styleSheet="font-size: 15px; font-weight: bold;"))
        rl = QHBoxLayout()
        e_new = QLineEdit(); e_new.setPlaceholderText("Unit name..."); rl.addWidget(e_new)
        b_add = QPushButton("➕ Add Unit"); b_add.setStyleSheet(f"background-color: {SUCCESS};")
        def add():
            n = e_new.text().strip()
            if n:
                try: add_unit(n); e_new.clear(); refresh()
                except: pass
        b_add.clicked.connect(add); rl.addWidget(b_add)
        al.addLayout(rl)
        cwl.addWidget(add_card)
        
        list_w = QWidget(); ll = QVBoxLayout(list_w); ll.setContentsMargins(0, 10, 0, 0)
        cwl.addWidget(list_w, 1)
        
        def refresh():
            while ll.count():
                it = ll.takeAt(0)
                if it.widget(): it.widget().deleteLater()
            units = get_all_units()
            counts = unit_worker_count()
            for b in units:
                c = counts.get(b, 0)
                cf = QFrame(); cf.setObjectName("card")
                cfl = QHBoxLayout(cf); cfl.setContentsMargins(14, 12, 14, 12)
                vi = QVBoxLayout()
                vi.addWidget(QLabel(f"📍 {b}", styleSheet="font-weight: bold;"))
                vi.addWidget(QLabel(f"{c} worker(s)", styleSheet=f"color: {SUCCESS if c > 0 else TEXT_MUTED}; font-size: 10px;"))
                cfl.addLayout(vi); cfl.addStretch()
                
                def ren(bn=b):
                    nn, ok = QInputDialog.getText(self, "Rename", f"Rename '{bn}' to:")
                    if ok and nn.strip(): rename_unit(bn, nn.strip()); refresh()
                def rem(bn=b, cnt=c):
                    if QMessageBox.question(self, "Delete", f"Delete '{bn}'?") == QMessageBox.StandardButton.Yes:
                        delete_unit(bn); refresh()
                br = QPushButton("✏️ Rename"); br.clicked.connect(ren); cfl.addWidget(br)
                bd = QPushButton("🗑️"); bd.setStyleSheet(f"background-color: {DANGER};"); bd.clicked.connect(rem); cfl.addWidget(bd)
                ll.addWidget(cf)
            ll.addStretch()
        refresh()

    # ══════════════════════════════════════════════════════════════════════
    #   WAGE RATES
    # ══════════════════════════════════════════════════════════════════════
    def _page_wages(self, layout):
        _page_header(layout, "💰  Wage Rates by Skill", "Set daily wage and overtime rate per skill level")
        cw = QWidget(); cwl = QVBoxLayout(cw); cwl.setContentsMargins(28, 0, 28, 20); layout.addWidget(cw, 1)

        wages = get_skill_wages_dict()
        entries = {}

        def _save_one(cat, ed, eo):
            """Auto-save a single skill-wage row (called on field focus-out)."""
            try:
                dw = float(ed.text() or 0)
                ot = float(eo.text() or 0)
                upsert_skill_wage(SkillWage(cat, dw, ot))
                self.set_message(f"✅ {cat} wage auto-saved!", SUCCESS)
            except Exception as exc:
                self.set_message(f"⚠️ Failed to save {cat}: {exc}", DANGER)

        for cat in SKILL_CATEGORIES:
            sw = wages.get(cat, SkillWage(cat, 0, 0))
            cf = QFrame(); cf.setObjectName("card")
            cfl = QHBoxLayout(cf); cfl.setContentsMargins(22, 18, 22, 18)
            vi = QVBoxLayout()
            vi.addWidget(QLabel(cat, styleSheet="font-size: 15px; font-weight: bold; color: white;"))
            vi.addWidget(QLabel("Skill Category", styleSheet="font-size: 10px; color: white;"))
            cfl.addLayout(vi); cfl.addStretch()
            vd = QVBoxLayout(); vd.addWidget(QLabel("Daily Wage (₹)", styleSheet="font-size: 10px; color: white;"))
            ed = QLineEdit(str(sw.daily_wage)); ed.setFixedWidth(110); vd.addWidget(ed); cfl.addLayout(vd)
            vo = QVBoxLayout(); vo.addWidget(QLabel("OT Rate (₹/hr)", styleSheet="font-size: 10px; color: white;"))
            eo = QLineEdit(str(sw.ot_rate)); eo.setFixedWidth(110); vo.addWidget(eo); cfl.addLayout(vo)
            entries[cat] = {"dw": ed, "ot": eo}
            # Auto-save when the user leaves either field (Tab / click away / Enter)
            ed.editingFinished.connect(lambda c=cat, d=ed, o=eo: _save_one(c, d, o))
            eo.editingFinished.connect(lambda c=cat, d=ed, o=eo: _save_one(c, d, o))
            cwl.addWidget(cf)

        def sv():
            saved, failed = 0, 0
            for cat, e in entries.items():
                try:
                    dw = float(e["dw"].text() or 0)
                    ot = float(e["ot"].text() or 0)
                    upsert_skill_wage(SkillWage(cat, dw, ot))
                    saved += 1
                except Exception as exc:
                    failed += 1
                    self.set_message(f"⚠️ Error saving {cat}: {exc}", DANGER)
            if not failed:
                self.set_message(f"✅ All {saved} wage rates saved!", SUCCESS)

        bs = QPushButton("💾 Save All Wage Rates")
        bs.setStyleSheet(f"background-color: {SUCCESS}; height: 35px;")
        bs.clicked.connect(sv)
        cwl.addWidget(bs); cwl.addStretch()

    # ══════════════════════════════════════════════════════════════════════
    #   SLIPS
    # ══════════════════════════════════════════════════════════════════════
    def _page_slips(self, layout):
        _page_header(layout, "📄  Generate Salary Slips", "Generate PDF salary slips — per unit or for all workers")
        ctrl = QFrame(); ctrl.setObjectName("surface2")
        cl = QHBoxLayout(ctrl); cl.setContentsMargins(16, 10, 16, 10)
        cl.addWidget(QLabel("<b>Month:</b>"))
        m_cb = QComboBox(); m_cb.addItems(month_options()); m_cb.setFixedWidth(140); cl.addWidget(m_cb)
        cl.addSpacing(20)
        cl.addWidget(QLabel("<b>Unit:</b>"))
        u_cb = QComboBox(); u_cb.addItems(_unit_filter_list()); u_cb.setFixedWidth(140); cl.addWidget(u_cb)
        cl.addSpacing(20)
        s_ent = QLineEdit(); s_ent.setPlaceholderText("Search Name / ID…"); s_ent.setFixedWidth(170); cl.addWidget(s_ent)
        cl.addStretch()
        ref_btn = QPushButton("🔄 Refresh")
        ref_btn.setStyleSheet(f"background-color: {SURFACE_3};")
        cl.addWidget(ref_btn)
        
        cw = QWidget()
        cwl = QHBoxLayout(cw); cwl.setContentsMargins(28, 4, 28, 14)
        cwl.addWidget(ctrl)
        layout.addWidget(cw)
        
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 0, 28, 20)
        layout.addWidget(content)
        
        _all_results_cache = []

        def refresh():
            sync_combo(m_cb, month_options())
            sync_combo(u_cb, _unit_filter_list())
            while content_layout.count():
                it = content_layout.takeAt(0)
                if it.widget(): it.widget().deleteLater()
                
            lbl = QLabel("⏳  Loading..."); content_layout.addWidget(lbl)
            month = m_cb.currentText(); unit = u_cb.currentText()
            
            def _fetch():
                workers, att_dict = get_workers_and_attendance(month)
                sw = get_skill_wages_dict()
                return workers, sw, list(att_dict.values()), month, unit
                
            def _render(data):
                # Guard: bail out if the user navigated away before fetch completed
                try:
                    content_layout.count()
                except RuntimeError:
                    return

                nonlocal _all_results_cache
                workers, sw, att, month, unit = data
                while content_layout.count():
                    it = content_layout.takeAt(0)
                    if it.widget(): it.widget().deleteLater()
                if unit != "All": workers = [w for w in workers if w.unit == unit]
                results, _ = calculate_payroll(workers, sw, att, month, get_config())
                _all_results_cache = results

                if not results:
                    empty = QLabel("📭  No payroll data for this period.")
                    empty.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 14px; margin: 40px;")
                    empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    content_layout.addWidget(empty)
                    return

                # ── Summary strip ──────────────────────────────────────────
                from PyQt6.QtWidgets import QCheckBox
                q = s_ent.text().strip().lower()
                filtered = [r for r in results if q in r.worker_name.lower() or q in r.worker_id.lower()] if q else results

                summary = QFrame()
                summary.setStyleSheet(f"background-color: {SURFACE_2}; border-radius: 8px; border: 1px solid {CARD_BORDER};")
                sl = QHBoxLayout(summary); sl.setContentsMargins(16, 10, 16, 10)
                unit_label = unit if unit != "All" else "All Units"
                sl.addWidget(QLabel(f"📅 <b>{month}</b>", styleSheet=f"color: {TEXT_PRIMARY}; font-size: 13px;"))
                sl.addSpacing(20)
                sl.addWidget(QLabel(f"🏢 <b>{unit_label}</b>", styleSheet=f"color: {ACCENT}; font-size: 13px;"))
                sl.addSpacing(20)
                sl.addWidget(QLabel(f"👷 <b>{len(filtered)}</b> worker(s)", styleSheet=f"color: {SUCCESS}; font-size: 13px;"))
                sl.addStretch()
                content_layout.addWidget(summary)

                # ── Action bar ─────────────────────────────────────────────
                act = QFrame()
                act.setStyleSheet(f"background-color: {SURFACE_3}; border-radius: 8px; border: 1px solid {CARD_BORDER};")
                al = QHBoxLayout(act); al.setContentsMargins(12, 8, 12, 8); al.setSpacing(8)

                hint = QLabel("☑  Tick workers → Generate Selected   |   Leave all unticked → use All as ZIP")
                hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
                al.addWidget(hint); al.addStretch()

                sel_all_btn  = QPushButton("☑ Select All")
                sel_none_btn = QPushButton("☐ Clear")
                for b in (sel_all_btn, sel_none_btn):
                    b.setStyleSheet(f"background-color: {SURFACE_2}; color: {TEXT_SECONDARY}; padding: 5px 12px; border-radius: 5px; font-size: 11px;")
                    b.setFixedHeight(30)

                gen_sel_btn = QPushButton("📄  Generate Selected")
                gen_sel_btn.setStyleSheet(
                    f"background-color: {SUCCESS}; color: white; font-weight: bold; "
                    f"padding: 6px 20px; border-radius: 6px; font-size: 12px;"
                )
                gen_sel_btn.setFixedHeight(34)

                gen_all_btn = QPushButton("📦  All as ZIP")
                gen_all_btn.setStyleSheet(
                    f"background-color: {ACCENT}; color: white; font-weight: bold; "
                    f"padding: 6px 16px; border-radius: 6px; font-size: 12px;"
                )
                gen_all_btn.setFixedHeight(34)

                al.addWidget(sel_all_btn)
                al.addWidget(sel_none_btn)
                al.addSpacing(12)
                al.addWidget(gen_sel_btn)
                al.addWidget(gen_all_btn)
                content_layout.addWidget(act)

                # ── Worker table (Print? checkbox + info only) ─────────────
                slip_table = StyledTable(
                    ("Print?", "ID", "Name", "Unit", "Skill", "Designation", "Net Pay (₹)"),
                    [55, 72, 160, 110, 95, 140, 120],
                    stretch_last=True
                )
                slip_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
                slip_table.setRowCount(len(filtered))

                _print_checks = []

                for i, r in enumerate(filtered):
                    chk = QCheckBox()
                    chk.setChecked(False)
                    chk.setStyleSheet("margin-left: 16px;")
                    slip_table.setCellWidget(i, 0, chk)
                    _print_checks.append(chk)

                    net_color = SUCCESS if r.net_pay > 0 else DANGER
                    for c, val in enumerate([r.worker_id, r.worker_name, r.unit,
                                             r.skill_category, r.profile_title, fmt_inr(r.net_pay)]):
                        cell = QTableWidgetItem(str(val))
                        cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        if c == 5:  # Net Pay column
                            cell.setForeground(QColor(net_color))
                            cell.setFont(QFont(FONT_FAMILY, 9, QFont.Weight.Bold))
                        slip_table.setItem(i, c + 1, cell)

                content_layout.addWidget(slip_table, 1)

                # ── Bulk toggles ───────────────────────────────────────────
                sel_all_btn.clicked.connect(lambda: [cb.setChecked(True)  for cb in _print_checks])
                sel_none_btn.clicked.connect(lambda: [cb.setChecked(False) for cb in _print_checks])

                # ── Generate Selected ──────────────────────────────────────
                def gen_selected():
                    chosen = [filtered[i] for i in range(len(filtered)) if _print_checks[i].isChecked()]
                    if not chosen:
                        QMessageBox.information(self, "Nothing Selected",
                                                "Please tick at least one worker in the Print? column.")
                        return
                    od = QFileDialog.getExistingDirectory(self, "Output Folder for Slips")
                    if not od: return
                    self.set_message(f"⏳ Generating {len(chosen)} slip(s)...", ACCENT)
                    cfg = get_config()
                    def do():
                        return [generate_slip_pdf(r, cfg, od) for r in chosen]
                    self._pdf_thread = FetchThread(do)
                    self._pdf_thread.result_ready.connect(
                        lambda paths: self.set_message(f"✅ {len(paths)} slip(s) saved → {od}", SUCCESS))
                    self._pdf_thread.start()

                # ── All as ZIP ─────────────────────────────────────────────
                def gen_all():
                    unit_tag = unit if unit != "All" else "All"
                    path, _ = QFileDialog.getSaveFileName(self, "Save ZIP",
                                                          f"SalarySlips_{month}_{unit_tag}.zip", "ZIP (*.zip)")
                    if not path: return
                    snap = list(filtered)
                    self.set_message(f"⏳ Generating {len(snap)} slip(s)...", ACCENT)
                    def do():
                        import shutil
                        td = tempfile.mkdtemp()
                        gen = generate_bulk_pdfs(snap, get_config(), td, zip_output=True, zip_only=True)
                        if gen.get("zip_path"): shutil.move(gen["zip_path"], path)
                        return True
                    self._pdf_zip_thread = FetchThread(do)
                    self._pdf_zip_thread.result_ready.connect(
                        lambda _: self.set_message(f"✅ ZIP saved — {len(snap)} slips!", SUCCESS))
                    self._pdf_zip_thread.start()

                gen_sel_btn.clicked.connect(gen_selected)
                gen_all_btn.clicked.connect(gen_all)

            self._async_load(_fetch, _render)

        m_cb.currentTextChanged.connect(refresh)
        u_cb.currentTextChanged.connect(refresh)
        # Fix #12: debounce slips search — fires refresh 300ms after user stops typing
        _slips_search_timer = QTimer()
        _slips_search_timer.setSingleShot(True)
        _slips_search_timer.setInterval(300)
        _slips_search_timer.timeout.connect(refresh)
        s_ent.textChanged.connect(lambda _: _slips_search_timer.start())
        ref_btn.clicked.connect(refresh)
        refresh()

    # ══════════════════════════════════════════════════════════════════════
    #   SETTINGS
    # ══════════════════════════════════════════════════════════════════════
    def _page_settings(self, layout):
        _page_header(layout, "⚙️  Company Settings", "Company information, working days, and system configuration")
        cw = QWidget(); cwl = QVBoxLayout(cw); cwl.setContentsMargins(28, 0, 28, 20); layout.addWidget(cw, 1)
        cfg = get_config()
        
        cf = QFrame(); cf.setObjectName("card"); cfl = QVBoxLayout(cf); cfl.setContentsMargins(20, 16, 20, 16)
        cfl.addWidget(QLabel("🏢 Company Information", styleSheet="font-size: 15px; font-weight: bold;"))
        gl = QVBoxLayout()
        e_cn = QLineEdit(cfg.company_name); gl.addWidget(QLabel("Company Name")); gl.addWidget(e_cn)
        r1 = QHBoxLayout(); e_a1 = QLineEdit(cfg.address_line1); e_a2 = QLineEdit(cfg.address_line2)
        v1 = QVBoxLayout(); v1.addWidget(QLabel("Address 1")); v1.addWidget(e_a1); r1.addLayout(v1)
        v2 = QVBoxLayout(); v2.addWidget(QLabel("Address 2")); v2.addWidget(e_a2); r1.addLayout(v2)
        gl.addLayout(r1)
        r2 = QHBoxLayout(); e_ph = QLineEdit(cfg.phone); e_em = QLineEdit(cfg.email)
        v3 = QVBoxLayout(); v3.addWidget(QLabel("Phone")); v3.addWidget(e_ph); r2.addLayout(v3)
        v4 = QVBoxLayout(); v4.addWidget(QLabel("Email")); v4.addWidget(e_em); r2.addLayout(v4)
        gl.addLayout(r2)
        cfl.addLayout(gl)
        
        cfl.addWidget(QLabel("⚖️ Statutory Rates", styleSheet="font-size: 15px; font-weight: bold; margin-top: 10px;"))
        gl2 = QVBoxLayout()
        r3 = QHBoxLayout()
        e_epf = QLineEdit(str(cfg.epf_rate)); v6 = QVBoxLayout(); v6.addWidget(QLabel("EPF Rate (%)")); v6.addWidget(e_epf); r3.addLayout(v6)
        e_esi = QLineEdit(str(cfg.esi_rate)); v7 = QVBoxLayout(); v7.addWidget(QLabel("ESI Rate (%)")); v7.addWidget(e_esi); r3.addLayout(v7)
        gl2.addLayout(r3)
        cfl.addLayout(gl2)
        
        bs = QPushButton("💾 Save Settings"); bs.setStyleSheet(f"background-color: {SUCCESS}; height: 35px;")
        def sv():
            try:
                epf = float(e_epf.text())
                esi = float(e_esi.text())
            except: return
            save_config(CompanyConfig(e_cn.text(), e_a1.text(), e_a2.text(), e_ph.text(), e_em.text(), 26, epf, esi, cfg.esi_ceiling, ""))
            self.set_message("✅ Settings saved!", SUCCESS)
        bs.clicked.connect(sv); cfl.addWidget(bs)

        # Bank Management Section
        bf = QFrame(); bf.setObjectName("card")
        bfl = QVBoxLayout(bf); bfl.setContentsMargins(20, 16, 20, 16)
        bfl.addWidget(QLabel("🏦 Bank Management", styleSheet="font-size: 15px; font-weight: bold;"))
        
        add_b_lay = QHBoxLayout()
        e_b_new = QLineEdit(); e_b_new.setPlaceholderText("New Bank name..."); add_b_lay.addWidget(e_b_new)
        btn_b_add = QPushButton("➕ Add Bank"); btn_b_add.setStyleSheet(f"background-color: {SUCCESS};")
        add_b_lay.addWidget(btn_b_add)
        bfl.addLayout(add_b_lay)
        
        bank_list_w = QWidget()
        bank_list_lay = QVBoxLayout(bank_list_w)
        bank_list_lay.setContentsMargins(0, 10, 0, 0)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(bank_list_w)
        bfl.addWidget(scroll, 1)
        
        def refresh_banks():
            while bank_list_lay.count():
                it = bank_list_lay.takeAt(0)
                if it.widget(): it.widget().deleteLater()
            banks = get_all_banks()
            for b in banks:
                b_row = QFrame()
                b_row_lay = QHBoxLayout(b_row); b_row_lay.setContentsMargins(0, 4, 0, 4)
                b_row_lay.addWidget(QLabel(f"🏦 {b}", styleSheet="font-weight: bold;"))
                b_row_lay.addStretch()
                
                def ren(bn=b):
                    nn, ok = QInputDialog.getText(self, "Rename Bank", f"Rename '{bn}' to:")
                    if ok and nn.strip(): update_bank(bn, nn.strip()); refresh_banks()
                def rem(bn=b):
                    if QMessageBox.question(self, "Delete Bank", f"Delete '{bn}'?") == QMessageBox.StandardButton.Yes:
                        delete_bank(bn); refresh_banks()
                br = QPushButton("✏️ Rename"); br.clicked.connect(ren); b_row_lay.addWidget(br)
                bd = QPushButton("🗑️"); bd.setStyleSheet(f"background-color: {DANGER};"); bd.clicked.connect(rem); b_row_lay.addWidget(bd)
                bank_list_lay.addWidget(b_row)
            bank_list_lay.addStretch()
            
        def add_bank_action():
            n = e_b_new.text().strip()
            if n:
                try: add_bank(n); e_b_new.clear(); refresh_banks()
                except Exception as e: QMessageBox.warning(self, "Error", str(e))
                
        btn_b_add.clicked.connect(add_bank_action)
        refresh_banks()
        
        tabs = QTabWidget()
        tabs.addTab(cf, "🏢 General Settings")
        tabs.addTab(bf, "🏦 Bank Management")
        cwl.addWidget(tabs, 1)

    # ══════════════════════════════════════════════════════════════════════
    #   PAYROLL BREAKDOWN PAGE
    # ══════════════════════════════════════════════════════════════════════
    def _page_payroll(self, layout):
        _page_header(layout, "🧾  Payroll Breakdown", "Detailed per-employee payroll calculations for the selected period")

        ctrl = QFrame(); ctrl.setObjectName("surface2")
        cl = QHBoxLayout(ctrl); cl.setContentsMargins(16, 10, 16, 10)
        cl.addWidget(QLabel("<b>Month:</b>"))
        m_cb = QComboBox(); m_cb.addItems(month_options()); m_cb.setFixedWidth(140); cl.addWidget(m_cb)
        cl.addSpacing(20)
        cl.addWidget(QLabel("<b>Unit:</b>"))
        u_cb = QComboBox(); u_cb.addItems(_unit_filter_list()); u_cb.setFixedWidth(140); cl.addWidget(u_cb)
        cl.addSpacing(20)
        s_ent = QLineEdit(); s_ent.setPlaceholderText("Search Name / ID…"); s_ent.setFixedWidth(160); cl.addWidget(s_ent)
        cl.addStretch()
        ref_btn = QPushButton("🔄 Refresh"); ref_btn.setStyleSheet(f"background-color: {SURFACE_3};"); cl.addWidget(ref_btn)

        cw = QWidget(); cwl = QHBoxLayout(cw); cwl.setContentsMargins(28, 4, 28, 4); cwl.addWidget(ctrl)
        layout.addWidget(cw)

        # Summary banner
        summary_bar = QFrame(); summary_bar.setObjectName("surface2")
        sbl = QHBoxLayout(summary_bar); sbl.setContentsMargins(28, 6, 28, 6)
        self._pr_lbl_workers = QLabel("Workers: —"); self._pr_lbl_workers.setStyleSheet(f"color:{TEXT_SECONDARY}; font-size:11px;")
        self._pr_lbl_gross   = QLabel("Gross: —");   self._pr_lbl_gross.setStyleSheet(f"color:{TEXT_SECONDARY}; font-size:11px;")
        self._pr_lbl_net     = QLabel("Net: —");     self._pr_lbl_net.setStyleSheet(f"color:{SUCCESS}; font-size:11px; font-weight:bold;")
        for lbl in (self._pr_lbl_workers, self._pr_lbl_gross, self._pr_lbl_net):
            sbl.addWidget(lbl)
        sbl.addStretch()
        layout.addWidget(summary_bar)

        cols = ("ID","Name","Unit","Skill","Designation","Days","Gross (₹)","EPF (₹)","ESI (₹)","Net Pay (₹)")
        widths = [60,140,90,80,130,45,100,80,75,110]
        table = StyledTable(cols, widths)
        cw2 = QWidget(); cw2l = QVBoxLayout(cw2); cw2l.setContentsMargins(28, 0, 28, 4); cw2l.addWidget(table, 1)
        layout.addWidget(cw2, 1)

        btn_row = QWidget(); brl = QHBoxLayout(btn_row); brl.setContentsMargins(28, 0, 28, 14)
        exp_btn = QPushButton("⬇️ Export CSV"); exp_btn.setFixedWidth(130)
        brl.addWidget(exp_btn); brl.addStretch()
        layout.addWidget(btn_row)

        _results_cache = []

        def refresh():
            sync_combo(m_cb, month_options())
            sync_combo(u_cb, _unit_filter_list())
            month = m_cb.currentText()
            unit  = u_cb.currentText()
            q     = s_ent.text().strip().lower()
            self._pr_lbl_workers.setText("Workers: ⏳"); self._pr_lbl_gross.setText(""); self._pr_lbl_net.setText("")

            def _fetch():
                workers, att_dict = get_workers_and_attendance(month)
                sw = get_skill_wages_dict()
                return workers, sw, list(att_dict.values()), month, unit, q

            def _render(data):
                # Guard: bail out if the user navigated away before fetch completed
                try:
                    table.isWidgetType()
                except RuntimeError:
                    return

                workers, sw, att, month, unit, q = data
                nonlocal _results_cache
                if unit != "All": workers = [w for w in workers if w.unit == unit]
                results, _ = calculate_payroll(workers, sw, att, month, get_config())
                if q:
                    results = [r for r in results if q in r.worker_name.lower() or q in r.worker_id.lower()]
                _results_cache = results
                s = payroll_summary(results)
                self._pr_lbl_workers.setText(f"  👷 Workers: {s['total_workers']}")
                self._pr_lbl_gross.setText(f"   💰 Gross: {fmt_inr(s['total_gross'])}")
                self._pr_lbl_net.setText(f"   ✅ Net Pay: {fmt_inr(s['total_net'])}")
                table.insert_rows([
                    (r.worker_id, r.worker_name, r.unit, r.skill_category,
                     r.profile_title, r.days_present, fmt_inr(r.gross),
                     fmt_inr(r.epf_deduction), fmt_inr(r.esi_deduction),
                     fmt_inr(r.net_pay)) for r in results
                ])

            self._async_load(_fetch, _render)

        def exp():
            month = m_cb.currentText()
            path, _ = QFileDialog.getSaveFileName(self, "Save CSV", f"Payroll_{month}.csv", "CSV (*.csv)")
            if path:
                try:
                    with open(path, "w", newline="", encoding="utf-8-sig") as f:
                        writer = csv.writer(f)
                        writer.writerow(["Emp name", "Total Sal", "IFSC Code", "Account Number"])
                        for r in _results_cache:
                            writer.writerow([r.worker_name, round(r.net_pay, 2), r.ifsc_code, r.bank_account])
                    self.set_message(f"✅ CSV → {path}", SUCCESS)
                except Exception as e:
                    self.set_message(f"⚠️ Export error: {e}", DANGER)

        exp_btn.clicked.connect(exp)
        m_cb.currentTextChanged.connect(refresh)
        u_cb.currentTextChanged.connect(refresh)
        # Debounce payroll search — same 300ms pattern as other pages
        _pr_search_timer = QTimer()
        _pr_search_timer.setSingleShot(True)
        _pr_search_timer.setInterval(300)
        _pr_search_timer.timeout.connect(refresh)
        s_ent.textChanged.connect(lambda: _pr_search_timer.start())
        ref_btn.clicked.connect(refresh)
        refresh()

    def _show_audit_logs(self):
        from PyQt6.QtWidgets import QDialog, QTableWidget, QTableWidgetItem, QHeaderView, QVBoxLayout, QPushButton, QHBoxLayout, QWidget, QMessageBox, QFileDialog
        from database import get_payroll_runs, get_payroll_run
        import json
        from pdf_generator import generate_bulk_pdfs
        from schema import PayrollResult
        
        dlg = QDialog(self)
        dlg.setWindowTitle("Payroll Audit Logs / History")
        dlg.resize(850, 450)
        lay = QVBoxLayout(dlg)
        
        runs = get_payroll_runs()
        if not runs:
            lay.addWidget(QLabel("No payroll runs saved yet."))
            dlg.exec()
            return
            
        table = QTableWidget(len(runs), 6)
        table.setHorizontalHeaderLabels(["ID", "Month", "Run Date", "Workers", "Total Net Pay", "Actions"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.setColumnWidth(0, 50)
        table.setColumnWidth(1, 100)
        table.setColumnWidth(2, 120)
        table.setColumnWidth(3, 80)
        table.setColumnWidth(4, 150)
        table.horizontalHeader().setStretchLastSection(True)
        
        for i, r in enumerate(runs):
            table.setItem(i, 0, QTableWidgetItem(str(r["id"])))
            table.setItem(i, 1, QTableWidgetItem(r["month"]))
            table.setItem(i, 2, QTableWidgetItem(r["run_date"].split("T")[0]))
            table.setItem(i, 3, QTableWidgetItem(str(r["worker_count"])))
            table.setItem(i, 4, QTableWidgetItem(fmt_inr(r["total_net"])))
            
            w = QWidget()
            wl = QHBoxLayout(w)
            wl.setContentsMargins(4, 2, 4, 2)
            
            btn_view = QPushButton("📦 Re-download ZIP")
            btn_view.setStyleSheet("background-color: #3B82F6; color: white; padding: 4px; border-radius: 4px;")
            
            def view_run(run_id=r["id"]):
                run_data = get_payroll_run(run_id)
                if not run_data: return
                od = QFileDialog.getExistingDirectory(dlg, "Output Folder for Re-downloaded ZIP")
                if not od: return
                try:
                    res_dicts = json.loads(run_data["results_json"])
                    results = [PayrollResult(**d) for d in res_dicts]
                    generate_bulk_pdfs(results, get_config(), od, zip_output=True, zip_only=True)
                    QMessageBox.information(dlg, "Success", f"ZIP successfully re-generated from the snapshot into:\n{od}")
                except Exception as e:
                    QMessageBox.warning(dlg, "Error", f"Failed to restore: {e}")
                    
            btn_view.clicked.connect(view_run)
            wl.addWidget(btn_view)
            table.setCellWidget(i, 5, w)
            
        lay.addWidget(table)
        dlg.exec()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PayrollApp()
    window.show()
    sys.exit(app.exec())
