"""
app.py — PayrollPro Desktop Application
========================================
Professional native desktop payroll software.
Run with:  python app.py
"""

import os, sys, csv, datetime, threading, tempfile
from backup_manager import BackupManager

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QPushButton, QStackedWidget,
                             QScrollArea, QFrame, QComboBox, QLineEdit, QTableWidget,
                             QTableWidgetItem, QHeaderView, QAbstractItemView, QTabWidget,
                             QMessageBox, QFileDialog, QInputDialog, QStyledItemDelegate)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize, QThread, pyqtSlot, QEvent
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
    DB_PATH,
)
from payroll_engine import calculate_payroll, payroll_summary
from pdf_generator import generate_bulk_pdfs, generate_slip_pdf
from schema import SkillWage

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
    background-color: {SURFACE};
    border: 1px solid {TEXT_MUTED};
    border-radius: 4px;
    padding: 4px;
    color: {TEXT_PRIMARY};
}}
QComboBox::drop-down {{
    border: none;
}}
QComboBox QAbstractItemView {{
    background-color: {SURFACE_3};
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT};
}}
QTableWidget {{
    background-color: {SURFACE_3};
    alternate-background-color: #1A1A2E;
    gridline-color: {CARD_BORDER};
    border: none;
}}
QHeaderView::section {{
    background-color: #0D2A4E;
    color: #90CAF9;
    font-weight: bold;
    border: none;
    padding: 4px;
}}
QTabWidget::pane {{
    border: none;
    background-color: {SURFACE_2};
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
def month_options():
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
        
    return sorted(list(m_set))

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
            if col_name == "Unit": cb.addItems(_unit_list())
            elif col_name == "Skill": cb.addItems(SKILL_CATEGORIES)
            elif col_name == "Bank": cb.addItems(get_all_banks() or ["(No banks — add in Settings)"])
            return cb
        return QLineEdit(parent)
        
    def setEditorData(self, editor, index):
        val = index.model().data(index, Qt.ItemDataRole.EditRole)
        if isinstance(editor, QComboBox):
            editor.setCurrentText(str(val))
        else:
            editor.setText(str(val))
            
    def setModelData(self, editor, model, index):
        if isinstance(editor, QComboBox):
            val = editor.currentText()
        else:
            val = editor.text()
        model.setData(index, val, Qt.ItemDataRole.EditRole)
        if self.db_update_cb:
            self.db_update_cb(index.row())

class StyledTable(QTableWidget):
    def __init__(self, columns, column_widths=None, parent=None, editable=False, db_update_cb=None):
        super().__init__(parent)
        self.setColumnCount(len(columns))
        self.setHorizontalHeaderLabels(columns)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        self.horizontalHeader().setStretchLastSection(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        if column_widths:
            for i, w in enumerate(column_widths):
                self.setColumnWidth(i, w)
        if editable:
            self.delegate = WorkerDelegate(self, db_update_cb)
            self.setItemDelegate(self.delegate)
            self.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        else:
            self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

    def insert_rows(self, rows, tags=None):
        self.setRowCount(0)
        self.setRowCount(len(rows))
        for r_idx, row in enumerate(rows):
            for c_idx, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                if tags and r_idx < len(tags):
                    tag = tags[r_idx]
                    if tag == "skilled": item.setForeground(QColor("#80CBC4"))
                    elif tag == "semi": item.setForeground(QColor("#FFD54F"))
                    elif tag == "unskilled": item.setForeground(QColor("white"))
                    elif tag == "inactive": item.setForeground(QColor(TEXT_MUTED))
                self.setItem(r_idx, c_idx, item)

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

# ══════════════════════════════════════════════════════════════════════════════
class PayrollApp(QMainWindow):
    backup_sync_signal = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self.backup_sync_signal.connect(self._update_backup_label)
        self.setWindowTitle("PayrollPro — Professional Payroll Management")
        self.resize(1300, 800)
        self.setMinimumSize(1050, 650)
        self.setStyleSheet(QSS)
        init_db(DB_PATH, seed=True)
        
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        self._build_sidebar()
        self._build_main_area()
        
        # Real-time backup manager
        self._backup_mgr = BackupManager(db_path=DB_PATH, on_sync=self._on_backup_sync)
        self._backup_mgr.start()
        
        # Pre-warm cache
        def _prewarm():
            try:
                get_all_workers(); get_skill_wages_dict(); get_all_units(); get_config()
            except: pass
        threading.Thread(target=_prewarm, daemon=True).start()
        
        self._navigate("dashboard")

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

    def set_message(self, msg, color=TEXT_MUTED):
        self.status_lbl.setText(f"  {msg}")
        self.status_lbl.setStyleSheet(f"font-size: 10px; color: {color};")

    def _navigate(self, key):
        for k, btn in self._nav_buttons.items():
            btn.set_active(k == key)
        
        # Clear stack
        while self.stack.count() > 0:
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()
            
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
        
        {"dashboard": self._page_dashboard, "attendance": self._page_attendance,
         "workers": self._page_workers, "units": self._page_units,
         "wages": self._page_wages, "slips": self._page_slips,
         "settings": self._page_settings}.get(key, lambda l: None)(self.page_layout)
         
        self.set_message(f"Viewing: {key.replace('_',' ').title()}")

    def _async_load(self, fetch_fn, render_fn):
        self.thread = FetchThread(fetch_fn)
        self.thread.result_ready.connect(render_fn)
        self.thread.error_ready.connect(lambda e: self.set_message(f"⚠️ Load error: {e}", DANGER))
        self.thread.start()

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
                workers, sw, att, month, unit = data
                while content_layout.count():
                    it = content_layout.takeAt(0)
                    if it.widget(): it.widget().deleteLater()
                    
                if unit != "All": workers = [w for w in workers if w.unit == unit]
                results, warnings = calculate_payroll(workers, sw, att, month)
                
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
                cards = QWidget()
                cl = QHBoxLayout(cards)
                cl.setContentsMargins(0,0,0,0)
                cl.addWidget(MetricCard("Workers", s["total_workers"], ACCENT, "👷"))
                cl.addWidget(MetricCard("Total Gross", fmt_inr(s["total_gross"]), "#26A69A", "💰"))
                cl.addWidget(MetricCard("Total EPF", fmt_inr(s["total_epf"]), WARNING_CLR, "🏦"))
                cl.addWidget(MetricCard("Total ESI", fmt_inr(s["total_esi"]), "#AB47BC", "🏥"))
                cl.addWidget(MetricCard("Total Net Pay", fmt_inr(s["total_net"]), SUCCESS, "✅"))
                content_layout.addWidget(cards)
                
                _section_label(content_layout, "Payroll Breakdown")
                cols = ("ID","Name","Unit","Skill","Designation","Days","Gross (₹)","EPF (₹)","ESI (₹)","Net Pay (₹)")
                widths = [60,130,90,80,120,45,100,80,75,110]
                table = StyledTable(cols, widths)
                table.insert_rows([(r.worker_id, r.worker_name, r.unit, r.skill_category,
                                    r.profile_title, r.days_present, fmt_inr(r.gross),
                                    fmt_inr(r.epf_deduction), fmt_inr(r.esi_deduction),
                                    fmt_inr(r.net_pay)) for r in results])
                content_layout.addWidget(table, 1)
                
                exp_btn = QPushButton("⬇️ Export CSV")
                exp_btn.setFixedWidth(120)
                def exp():
                    import csv
                    path, _ = QFileDialog.getSaveFileName(self, "Save CSV", f"Payroll_{month}.csv", "CSV (*.csv)")
                    if path:
                        try:
                            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                                writer = csv.writer(f)
                                writer.writerow(["Emp name", "Total Sal", "IFSC Code", "Account Number"])
                                for r in results:
                                    writer.writerow([r.worker_name, round(r.net_pay, 2), r.ifsc_code, r.bank_account])
                            self.set_message(f"✅ CSV → {path}", SUCCESS)
                        except Exception as e:
                            self.set_message(f"⚠️ Export error: {e}", DANGER)
                exp_btn.clicked.connect(exp)
                content_layout.addWidget(exp_btn)
                
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
        opts = month_options(); config = get_config()
        ctrl = QWidget(); cl = QHBoxLayout(ctrl); cl.setContentsMargins(12, 12, 12, 8)
        cl.addWidget(QLabel("<b>Month:</b>"))
        m_cb = QComboBox(); m_cb.addItems(opts); m_cb.setFixedWidth(140); cl.addWidget(m_cb)
        cl.addSpacing(20)
        cl.addWidget(QLabel("<b>Unit:</b>"))
        u_cb = QComboBox(); u_cb.addItems(_unit_filter_list()); u_cb.setFixedWidth(140); cl.addWidget(u_cb)
        cl.addSpacing(20)
        s_ent = QLineEdit(); s_ent.setPlaceholderText("Search Name/ID..."); s_ent.setFixedWidth(140); cl.addWidget(s_ent)
        cl.addWidget(QLabel(f"(Max days: {config.working_days})", styleSheet=f"color: {TEXT_MUTED};"))
        cl.addStretch()
        layout.addWidget(ctrl)
        
        table = StyledTable(("ID","Name","Unit","Skill","Designation","Days","OT Hours"), [60,140,80,80,120,60,80], editable=True)
        layout.addWidget(table, 1)
        
        self._att_workers = []
        
        def save_all():
            records = []
            month = m_cb.currentText()
            existing_db = {a.worker_id: a for a in get_attendance(month)}
            for row in range(table.rowCount()):
                wid = table.item(row, 0).text()
                att = existing_db.get(wid, AttendanceRecord(wid, month))
                try: att.days_present = float(table.item(row, 5).text())
                except: att.days_present = 0.0
                try: att.overtime_hours = float(table.item(row, 6).text())
                except: att.overtime_hours = 0.0
                records.append(att)
            bulk_upsert_attendance(records)
            self.set_message(f"✅ Saved {len(records)} records for {month}", SUCCESS)
            
        def refresh():
            sync_combo(m_cb, month_options())
            sync_combo(u_cb, _unit_filter_list())
            workers = get_all_workers()
            unit = u_cb.currentText()
            if unit != "All": workers = [w for w in workers if w.unit == unit]
            q = s_ent.text().strip().lower()
            if q: workers = [w for w in workers if q in w.name.lower() or q in w.worker_id.lower()]
            
            existing = {a.worker_id: a for a in get_attendance(m_cb.currentText())}
            self._att_workers = workers
            table.setRowCount(0)
            table.setRowCount(len(workers))
            for i, w in enumerate(workers):
                att = existing.get(w.worker_id, AttendanceRecord(w.worker_id, m_cb.currentText()))
                for j, v in enumerate([w.worker_id, w.name, w.unit, w.skill_category, w.designation, str(att.days_present), str(att.overtime_hours)]):
                    it = QTableWidgetItem(v)
                    if j < 5: it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    table.setItem(i, j, it)
                    
        m_cb.currentTextChanged.connect(refresh)
        u_cb.currentTextChanged.connect(refresh)
        s_ent.textChanged.connect(refresh)
        
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
                res = import_attendance_from_csv(fp, m_cb.currentText())
                self.set_message(f"✅ Imported {res['imported']} records.", SUCCESS)
                self._navigate("attendance")
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
            wid = table.item(row, 0).text()
            w_obj = get_worker_by_id(wid)
            name = table.item(row, 1).text().strip()
            if not name: return
            bname = table.item(row, 5).text().strip()
            if bname.startswith("(No"): bname = ""
            upsert_worker(Worker(
                worker_id=wid, name=name, unit=table.item(row, 2).text().strip(),
                skill_category=table.item(row, 3).text().strip(),
                designation=table.item(row, 4).text().strip(),
                bank_name=bname, bank_account=table.item(row, 6).text().strip(),
                ifsc_code=table.item(row, 7).text().strip(),
                uan_number=table.item(row, 8).text().strip(),
                esic_number=table.item(row, 9).text().strip(),
                joining_date=w_obj.joining_date if w_obj else "",
                active=w_obj.active if w_obj else True))
            self.set_message(f"✅ {wid} auto-saved!", SUCCESS)

        cols = ("ID", "Name", "Unit", "Skill", "Designation", "Bank", "A/C", "IFSC", "UAN", "ESIC", "Status")
        widths = [55, 140, 80, 80, 90, 100, 110, 95, 85, 75, 70]
        table = StyledTable(cols, widths, editable=True, db_update_cb=_db_cb)
        tl.addWidget(table, 1)
        
        act_bar = QFrame(); act_bar.setStyleSheet("background-color: #0D2A4E; border-radius: 8px;"); act_bar.setFixedHeight(42)
        abl = QHBoxLayout(act_bar)
        lbl_ab = QLabel(""); lbl_ab.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;"); abl.addWidget(lbl_ab); abl.addStretch()
        
        def tgl():
            row = table.currentRow()
            if row < 0: return
            wid = table.item(row, 0).text()
            w = get_worker_by_id(wid)
            if w.active: deactivate_worker(wid)
            else: reactivate_worker(wid)
            refresh()
        def del_w():
            row = table.currentRow()
            if row < 0: return
            wid = table.item(row, 0).text()
            if QMessageBox.question(self, "Delete", f"Delete {wid}?") == QMessageBox.StandardButton.Yes:
                delete_worker(wid); refresh()
                
        b_tgl = QPushButton("⏸ Toggle"); b_tgl.setStyleSheet(f"background-color: {WARNING_CLR};"); b_tgl.clicked.connect(tgl); abl.addWidget(b_tgl)
        b_del = QPushButton("🗑️ Delete"); b_del.setStyleSheet(f"background-color: {DANGER};"); b_del.clicked.connect(del_w); abl.addWidget(b_del)
        act_bar.setVisible(False)
        tl.addWidget(act_bar)
        
        def row_sel():
            row = table.currentRow()
            if row >= 0:
                act_bar.setVisible(True)
                lbl_ab.setText(f"✏️ {table.item(row, 0).text()} — {table.item(row, 1).text()}")
            else: act_bar.setVisible(False)
        table.itemSelectionChanged.connect(row_sel)

        def refresh():
            sync_combo(u_cb, _unit_filter_list())
            try:
                sync_combo(e_unit, _unit_list())
                sync_combo(e_bank_name, _bank_names())
            except NameError: pass
            workers = get_all_workers(active_only=False)
            filt = u_cb.currentText()
            q = s_ent.text().strip().lower()
            if filt != "All": workers = [w for w in workers if w.unit == filt]
            if q: workers = [w for w in workers if q in w.name.lower() or q in w.worker_id.lower()]
            
            tags = []
            rows = []
            for w in workers:
                rows.append([w.worker_id, w.name, w.unit, w.skill_category,
                             w.designation, w.bank_name, w.bank_account, w.ifsc_code,
                             w.uan_number, w.esic_number, "● Active" if w.active else "○ Inactive"])
                if not w.active: tags.append("inactive")
                elif w.skill_category == "Skilled": tags.append("skilled")
                elif "Semi" in w.skill_category: tags.append("semi")
                else: tags.append("unskilled")
            table.insert_rows(rows, tags)
            act_bar.setVisible(False)

        u_cb.currentTextChanged.connect(refresh)
        s_ent.textChanged.connect(refresh)
        refresh()

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
                res = import_workers_from_csv(fp)
                self.set_message(f"✅ Imported {res['imported']} workers.", SUCCESS)
                self._navigate("workers")
                
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
        for cat in SKILL_CATEGORIES:
            sw = wages.get(cat, SkillWage(cat, 0, 0))
            cf = QFrame(); cf.setObjectName("card")
            cfl = QHBoxLayout(cf); cfl.setContentsMargins(22, 18, 22, 18)
            vi = QVBoxLayout()
            vi.addWidget(QLabel(cat, styleSheet=f"font-size: 15px; font-weight: bold; color: {ACCENT};"))
            vi.addWidget(QLabel("Skill Category", styleSheet=f"font-size: 10px; color: {TEXT_MUTED};"))
            cfl.addLayout(vi); cfl.addStretch()
            
            vd = QVBoxLayout(); vd.addWidget(QLabel("Daily Wage (₹)", styleSheet=f"font-size: 10px; color: {TEXT_SECONDARY};"))
            ed = QLineEdit(str(sw.daily_wage)); ed.setFixedWidth(110); vd.addWidget(ed); cfl.addLayout(vd)
            
            vo = QVBoxLayout(); vo.addWidget(QLabel("OT Rate (₹/hr)", styleSheet=f"font-size: 10px; color: {TEXT_SECONDARY};"))
            eo = QLineEdit(str(sw.ot_rate)); eo.setFixedWidth(110); vo.addWidget(eo); cfl.addLayout(vo)
            
            entries[cat] = {"dw": ed, "ot": eo}
            cwl.addWidget(cf)
            
        def sv():
            for cat, e in entries.items():
                try: dw = float(e["dw"].text() or 0); ot = float(e["ot"].text() or 0)
                except: continue
                upsert_skill_wage(SkillWage(cat, dw, ot))
            self.set_message("✅ Wage rates saved!", SUCCESS)
            
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
                workers, sw, att, month, unit = data
                while content_layout.count():
                    it = content_layout.takeAt(0)
                    if it.widget(): it.widget().deleteLater()
                if unit != "All": workers = [w for w in workers if w.unit == unit]
                results, warnings = calculate_payroll(workers, sw, att, month)
                
                if not results:
                    content_layout.addWidget(QLabel("No payroll data."))
                    return
                
                _section_label(content_layout, f"📊 Ready: {len(results)} slip(s)")
                table = StyledTable(("ID","Name","Unit","Skill","Designation","Net Pay (₹)"), [70,150,100,80,130,120])
                table.insert_rows([(r.worker_id, r.worker_name, r.unit, r.skill_category,
                                    r.profile_title, fmt_inr(r.net_pay)) for r in results])
                content_layout.addWidget(table, 1)
                
                def gen_all():
                    path, _ = QFileDialog.getSaveFileName(self, "Save ZIP", f"SalarySlips_{month}.zip", "ZIP (*.zip)")
                    if path:
                        self.set_message("⏳ Generating...", ACCENT)
                        def do():
                            td = tempfile.mkdtemp()
                            gen = generate_bulk_pdfs(results, get_config(), td, zip_output=True, zip_only=True)
                            if gen.get("zip_path"):
                                import shutil; shutil.move(gen["zip_path"], path)
                            return True
                        self._pdf_thread = FetchThread(do)
                        self._pdf_thread.result_ready.connect(lambda _: self.set_message("✅ Done", SUCCESS))
                        self._pdf_thread.start()
                
                bz = QPushButton("📦 Download All as ZIP"); bz.clicked.connect(gen_all); content_layout.addWidget(bz)
                
                sc = QHBoxLayout()
                sel_w = QComboBox()
                sel_w.addItems([f"{r.worker_id} — {r.worker_name}" for r in results])
                sc.addWidget(sel_w)
                def gen_s():
                    wid = sel_w.currentText().split(" — ")[0]
                    r = next((r for r in results if r.worker_id == wid), None)
                    if r:
                        od = QFileDialog.getExistingDirectory(self, "Output Folder")
                        if od:
                            p = generate_slip_pdf(r, get_config(), od)
                            self.set_message(f"✅ Saved: {p}", SUCCESS)
                bs = QPushButton("👁️ Generate Single"); bs.setStyleSheet(f"background-color: {SUCCESS};"); bs.clicked.connect(gen_s)
                sc.addWidget(bs)
                content_layout.addLayout(sc)
                
            self._async_load(_fetch, _render)
            
        m_cb.currentTextChanged.connect(refresh)
        u_cb.currentTextChanged.connect(refresh)
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
        e_wd = QLineEdit(str(cfg.working_days)); e_wd.setFixedWidth(80)
        v5 = QVBoxLayout(); v5.addWidget(QLabel("Working Days / Month")); v5.addWidget(e_wd); gl.addLayout(v5)
        cfl.addLayout(gl)
        
        bs = QPushButton("💾 Save Settings"); bs.setStyleSheet(f"background-color: {SUCCESS}; height: 35px;")
        def sv():
            try: wd = int(e_wd.text())
            except: return
            save_config(CompanyConfig(e_cn.text(), e_a1.text(), e_a2.text(), e_ph.text(), e_em.text(), wd))
            self.set_message("✅ Settings saved!", SUCCESS)
        bs.clicked.connect(sv); cfl.addWidget(bs)
        cwl.addWidget(cf)

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
        
        cwl.addWidget(bf, 1)

def _bank_names():
    bs = get_all_banks()
    return bs if bs else ["(No banks — add in Settings)"]

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PayrollApp()
    window.show()
    sys.exit(app.exec())
