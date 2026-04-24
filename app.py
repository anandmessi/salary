"""
app.py — PayrollPro Desktop Application
========================================
Professional native desktop payroll software.
Run with:  python app.py
"""

import os, sys, csv, datetime, threading, tempfile
from backup_manager import BackupManager
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import customtkinter as ctk

from schema import Worker, AttendanceRecord, CompanyConfig, SKILL_CATEGORIES
from database import (
    init_db, get_all_workers, get_all_skill_wages, get_skill_wages_dict,
    upsert_skill_wage,
    get_attendance, upsert_attendance, bulk_upsert_attendance,
    delete_attendance_for_worker,
    upsert_worker, deactivate_worker, reactivate_worker,
    delete_worker, get_worker_by_id,
    get_config, save_config, get_months_with_data,
    get_workers_by_unit, import_attendance_from_csv,
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
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

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
FONT_TITLE       = (FONT_FAMILY, 22, "bold")
FONT_HEADING     = (FONT_FAMILY, 15, "bold")
FONT_SUBHEADING  = (FONT_FAMILY, 12, "bold")
FONT_BODY        = (FONT_FAMILY, 11)
FONT_BODY_BOLD   = (FONT_FAMILY, 11, "bold")
FONT_SMALL       = (FONT_FAMILY, 10)
FONT_TINY        = (FONT_FAMILY, 9)
FONT_METRIC_VAL  = (FONT_FAMILY, 22, "bold")
FONT_METRIC_LBL  = (FONT_FAMILY, 9)


# ── Helpers ───────────────────────────────────────────────────────────────────
def month_options():
    today = datetime.date.today()
    m_list = []
    for i in range(11, -1, -1):
        y, m = today.year, today.month - i
        while m <= 0: m += 12; y -= 1
        m_list.append(f"{y}-{m:02d}")
    return m_list

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

def _page_header(parent, title, subtitle):
    """Compact page header — fixed-height accent bar avoids stretching in CTkScrollableFrame."""
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", padx=28, pady=(14, 6))
    ctk.CTkFrame(row, width=4, height=46, corner_radius=2, fg_color=ACCENT).pack(side="left", padx=(0, 14))
    info = ctk.CTkFrame(row, fg_color="transparent")
    info.pack(side="left")
    ctk.CTkLabel(info, text=title, font=FONT_TITLE,
                  text_color=TEXT_PRIMARY, anchor="w").pack(anchor="w")
    ctk.CTkLabel(info, text=subtitle, font=FONT_SMALL,
                  text_color=TEXT_SECONDARY, anchor="w").pack(anchor="w", pady=(2, 0))

def _section_label(parent, text):
    """A styled section divider label."""
    f = ctk.CTkFrame(parent, fg_color="transparent")
    f.pack(fill="x", pady=(10, 2))
    ctk.CTkLabel(f, text=text, font=FONT_SUBHEADING,
                  text_color=ACCENT, anchor="w").pack(side="left")
    ctk.CTkFrame(f, height=1, fg_color=SURFACE_3).pack(side="left", fill="x", expand=True, padx=(10, 0), pady=6)

# ══════════════════════════════════════════════════════════════════════════════
class MetricCard(ctk.CTkFrame):
    def __init__(self, master, label, value, color=ACCENT, icon="", **kw):
        super().__init__(master, corner_radius=14, fg_color=CARD_BG, **kw)
        # Top accent bar
        ctk.CTkFrame(self, height=4, corner_radius=0, fg_color=color).pack(fill="x")
        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=18, pady=(12, 16))
        if icon:
            ctk.CTkLabel(inner, text=icon, font=(FONT_FAMILY, 20),
                          text_color=color).pack(anchor="w", pady=(0, 2))
        ctk.CTkLabel(inner, text=str(value), font=(FONT_FAMILY, 22, "bold"),
                      text_color=color, anchor="w").pack(anchor="w")
        ctk.CTkLabel(inner, text=label, font=FONT_METRIC_LBL,
                      text_color=TEXT_SECONDARY, anchor="w").pack(anchor="w", pady=(3, 0))

class StyledTreeview(ctk.CTkFrame):
    def __init__(self, master, columns, column_widths=None, height=14, **kw):
        super().__init__(master, fg_color=CARD_BG, corner_radius=10, **kw)
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=6, pady=6)
        self.tree = ttk.Treeview(container, columns=columns, show="headings",
                                  style="Dark.Treeview", height=height, selectmode="browse")
        sb = ctk.CTkScrollbar(container, command=self.tree.yview,
                               fg_color=SURFACE_3, button_color=TEXT_MUTED)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        for i, col in enumerate(columns):
            w = column_widths[i] if column_widths and i < len(column_widths) else 120
            self.tree.heading(col, text=col, anchor="w")
            self.tree.column(col, width=w, minwidth=50, anchor="w")
        self.tree.tag_configure("even",        background="#1A1A2E", foreground=TEXT_PRIMARY)
        self.tree.tag_configure("odd",         background=SURFACE_3, foreground=TEXT_PRIMARY)
        self.tree.tag_configure("skilled",     foreground="#80CBC4")
        self.tree.tag_configure("semi",        foreground="#FFD54F")
        self.tree.tag_configure("unskilled",   foreground="#EF9A9A")
        self.tree.tag_configure("inactive",    foreground=TEXT_MUTED)
    def clear(self):
        self.tree.delete(*self.tree.get_children())
    def insert_rows(self, rows):
        """Batch-insert rows; freezes the treeview during load to prevent layout thrashing."""
        self.tree.delete(*self.tree.get_children())
        # Build all inserts before committing to the display
        self.tree.update_idletasks()
        for i, row in enumerate(rows):
            self.tree.insert("", "end", values=row, tags=("even" if i % 2 == 0 else "odd",))

class SidebarButton(ctk.CTkButton):
    def __init__(self, master, text, icon, command=None, **kw):
        super().__init__(master, text=f"  {icon}   {text}", font=(FONT_FAMILY, 12, "bold"),
                         anchor="w", height=46, corner_radius=10, fg_color="transparent",
                         hover_color=SIDEBAR_HOVER, text_color=TEXT_SECONDARY, command=command, **kw)
    def set_active(self, a):
        self.configure(fg_color=ACCENT if a else "transparent",
                       text_color="white" if a else TEXT_SECONDARY,
                       hover_color=ACCENT_HOVER if a else SIDEBAR_HOVER)

class StatusBar(ctk.CTkFrame):
    def __init__(self, master, **kw):
        super().__init__(master, height=30, corner_radius=0, fg_color=SIDEBAR_BG, **kw)
        self.pack_propagate(False)
        # Left accent dot
        ctk.CTkFrame(self, width=3, corner_radius=0, fg_color=ACCENT).pack(side="left", fill="y")
        self._label = ctk.CTkLabel(self, text="  Ready", font=FONT_TINY,
                                    text_color=TEXT_MUTED, anchor="w")
        self._label.pack(side="left", padx=10, fill="y")
        ctk.CTkLabel(self, text=f"PayrollPro v2.1  •  {os.path.abspath(DB_PATH)}  ",
                      font=FONT_TINY, text_color=TEXT_MUTED, anchor="e").pack(side="right", padx=10, fill="y")
        self._backup_label = ctk.CTkLabel(
            self, text="  🔄 Backup: Starting…  ",
            font=FONT_TINY, text_color=TEXT_MUTED, anchor="e")
        self._backup_label.pack(side="right", padx=4, fill="y")
    def set_message(self, msg, color=TEXT_MUTED):
        self._label.configure(text=f"  {msg}", text_color=color)
    def set_backup_status(self, status: str, color=TEXT_MUTED):
        self._backup_label.configure(text=f"  {status}  ", text_color=color)


# ── App-wide async / debounce helpers ─────────────────────────────────────────
def _async_load(fetch_fn, done_fn, error_fn=None):
    """Run *fetch_fn()* on a background thread, then post *done_fn(result)*
    back onto the Tk main thread — BUT only if the page hasn't changed.

    Uses a generation counter (_async_load._gen) that is bumped by _navigate().
    Any callback whose captured generation no longer matches is silently dropped,
    preventing crashes when the user switches pages mid-load.
    """
    my_gen = _async_load._gen   # snapshot at call time
    def _worker():
        try:
            result = fetch_fn()
            def _deliver():
                # Drop stale callbacks (page changed while we were loading)
                if _async_load._gen != my_gen:
                    return
                try:
                    done_fn(result)
                except Exception as exc:
                    if error_fn:
                        try: error_fn(exc)
                        except Exception: pass
            _async_load._root.after(0, _deliver)
        except Exception as exc:
            def _err():
                if _async_load._gen != my_gen:
                    return
                if error_fn:
                    try: error_fn(exc)
                    except Exception: pass
            _async_load._root.after(0, _err)
    threading.Thread(target=_worker, daemon=True).start()

_async_load._root = None   # set to the PayrollApp instance at startup
_async_load._gen  = 0      # bumped on every _navigate call


def _make_debouncer(widget, delay_ms=280):
    """Return a debounce wrapper — only fires *fn* after *delay_ms* ms of silence."""
    pending = [None]
    def debounce(fn):
        def wrapper(*args, **kwargs):
            if pending[0]:
                try: widget.after_cancel(pending[0])
                except Exception: pass
            pending[0] = widget.after(delay_ms, lambda: fn(*args, **kwargs))
        return wrapper
    return debounce


def _show_loading(parent, text="Loading…"):
    """Show a transient loading banner; caller destroys the returned frame."""
    f = ctk.CTkFrame(parent, fg_color=SURFACE_2, corner_radius=10)
    f.pack(fill="x", padx=28, pady=8)
    ctk.CTkLabel(f, text=f"⏳  {text}", font=FONT_BODY,
                 text_color=TEXT_SECONDARY).pack(pady=14)
    parent.update_idletasks()
    return f


# ══════════════════════════════════════════════════════════════════════════════
class PayrollApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        _async_load._root = self          # enable background→main-thread posting
        self.title("PayrollPro — Professional Payroll Management")
        self.geometry("1300x800"); self.minsize(1050, 650)
        init_db(DB_PATH, seed=True)
        self.grid_columnconfigure(1, weight=1); self.grid_rowconfigure(0, weight=1)
        style = ttk.Style(); style.theme_use("clam")
        style.configure("Dark.Treeview", background=SURFACE_3,
                         foreground=TEXT_PRIMARY, fieldbackground=SURFACE_3,
                         borderwidth=0, font=(FONT_FAMILY, 10), rowheight=32)
        style.configure("Dark.Treeview.Heading", background="#0D2A4E",
                         foreground="#90CAF9", font=(FONT_FAMILY, 10, "bold"),
                         borderwidth=0, relief="flat")
        style.map("Dark.Treeview",
                   background=[("selected", "#1565C0")], foreground=[("selected", "white")])
        style.map("Dark.Treeview.Heading", background=[("active", ACCENT)])
        self._build_sidebar(); self._build_main_area(); self._build_status_bar()
        # ── Start real-time backup manager ─────────────────────────────────
        self._backup_mgr = BackupManager(
            db_path=DB_PATH,
            on_sync=self._on_backup_sync,
        )
        self._backup_mgr.start()
        # Pre-warm cache in background so first page loads hit RAM, not disk
        def _prewarm():
            try:
                from database import get_all_workers, get_skill_wages_dict, get_all_units, get_config
                get_all_workers(); get_skill_wages_dict(); get_all_units(); get_config()
            except Exception:
                pass
        threading.Thread(target=_prewarm, daemon=True).start()
        self._navigate("dashboard")


    def _on_backup_sync(self, status: str, timestamp: str):
        """Called by BackupManager (background thread) after each sync."""
        def _update():
            if "Error" in status or "⚠" in status:
                color = DANGER
                label = f"🔴 Backup: {timestamp}"
            else:
                color = SUCCESS
                label = f"🟢 Backup: {timestamp}"
            self.status_bar.set_backup_status(label, color)
        # Schedule UI update on the main thread
        self.after(0, _update)

    def _build_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=230, corner_radius=0, fg_color=SIDEBAR_BG)
        self.sidebar.grid(row=0, column=0, sticky="nsew"); self.sidebar.grid_propagate(False)
        # Logo area
        logo = ctk.CTkFrame(self.sidebar, fg_color=GLAS if hasattr(self,'GLAS') else "#191932",
                             corner_radius=0)
        logo.pack(fill="x", pady=0)
        logo_inner = ctk.CTkFrame(logo, fg_color="transparent")
        logo_inner.pack(fill="x", padx=18, pady=(22, 18))
        ctk.CTkLabel(logo_inner, text="💼", font=(FONT_FAMILY, 30)).pack(side="left")
        brand = ctk.CTkFrame(logo_inner, fg_color="transparent")
        brand.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(brand, text="PayrollPro", font=(FONT_FAMILY, 18, "bold"),
                      text_color=TEXT_PRIMARY).pack(anchor="w")
        ctk.CTkLabel(brand, text="Enterprise Edition", font=(FONT_FAMILY, 8),
                      text_color=ACCENT).pack(anchor="w")
        # Accent line
        ctk.CTkFrame(self.sidebar, height=1, fg_color=CARD_BORDER).pack(fill="x")
        # Nav
        nav_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        nav_frame.pack(fill="x", padx=10, pady=(14, 0))
        nav = [
            ("Dashboard",      "📊", "dashboard"),
            ("Attendance",     "📋", "attendance"),
            ("Workers",        "👷", "workers"),
            ("Units",       "🏢", "units"),
            ("Wage Rates",     "💰", "wages"),
            ("Generate Slips", "📄", "slips"),
            ("Settings",       "⚙️",  "settings"),
        ]
        self._nav_buttons = {}
        for text, icon, key in nav:
            btn = SidebarButton(nav_frame, text=text, icon=icon,
                                command=lambda k=key: self._navigate(k))
            btn.pack(fill="x", pady=3); self._nav_buttons[key] = btn
        ctk.CTkFrame(self.sidebar, fg_color="transparent").pack(fill="both", expand=True)
        ctk.CTkFrame(self.sidebar, height=1, fg_color=CARD_BORDER).pack(fill="x")
        # Footer
        foot = ctk.CTkFrame(self.sidebar, fg_color="#191932", corner_radius=0)
        foot.pack(fill="x")
        ctk.CTkLabel(foot, text="🟢  Zero-Cost Payroll System",
                      font=(FONT_FAMILY, 9, "bold"), text_color=SUCCESS
                      ).pack(padx=16, pady=(10, 2), anchor="w")
        ctk.CTkLabel(foot, text="Python • SQLite • 2026",
                      font=FONT_TINY, text_color=TEXT_MUTED).pack(padx=16, pady=(0, 14), anchor="w")

    def _build_main_area(self):
        self.main_area = ctk.CTkFrame(self, corner_radius=0, fg_color=SURFACE)
        self.main_area.grid(row=0, column=1, sticky="nsew")
        self.main_area.grid_columnconfigure(0, weight=1); self.main_area.grid_rowconfigure(0, weight=1)
        self._current_page = None

    def _build_status_bar(self):
        self.status_bar = StatusBar(self)
        self.status_bar.grid(row=1, column=0, columnspan=2, sticky="ew")

    def _navigate(self, key):
        for k, btn in self._nav_buttons.items(): btn.set_active(k == key)
        # Invalidate any in-flight async callbacks from the previous page
        _async_load._gen += 1
        if self._current_page: self._current_page.destroy()
        page = ctk.CTkScrollableFrame(self.main_area, fg_color=SURFACE,
                                       scrollbar_button_color=CARD_BORDER, scrollbar_fg_color=SURFACE)
        page.grid(row=0, column=0, sticky="nsew"); self._current_page = page
        {"dashboard": self._page_dashboard, "attendance": self._page_attendance,
         "workers": self._page_workers, "units": self._page_units,
         "wages": self._page_wages, "slips": self._page_slips,
         "settings": self._page_settings}.get(key, lambda p: None)(page)
        self.status_bar.set_message(f"Viewing: {key.replace('_',' ').title()}")

    # ══════════════════════════════════════════════════════════════════════
    #   DASHBOARD
    # ══════════════════════════════════════════════════════════════════════
    def _page_dashboard(self, parent):
        _page_header(parent, "📊  Payroll Dashboard",
                     "Overview of payroll calculations for the selected period")
        ctrl = ctk.CTkFrame(parent, fg_color=SURFACE_2, corner_radius=10)
        ctrl.pack(fill="x", padx=28, pady=(4, 14))
        inner_ctrl = ctk.CTkFrame(ctrl, fg_color="transparent")
        inner_ctrl.pack(fill="x", padx=16, pady=10)
        opts = month_options()
        ctk.CTkLabel(inner_ctrl, text="Month:", font=FONT_BODY_BOLD, text_color=TEXT_PRIMARY).pack(side="left")
        month_var = ctk.StringVar(value=opts[-1])
        ctk.CTkOptionMenu(inner_ctrl, values=opts, variable=month_var, width=140,
                           font=FONT_BODY, fg_color=SURFACE_3, button_color=ACCENT,
                           button_hover_color=ACCENT_HOVER).pack(side="left", padx=(8, 20))
        ctk.CTkLabel(inner_ctrl, text="Unit:", font=FONT_BODY_BOLD, text_color=TEXT_PRIMARY).pack(side="left")
        unit_var = ctk.StringVar(value="All")
        ctk.CTkOptionMenu(inner_ctrl, values=_unit_filter_list(), variable=unit_var, width=150,
                           font=FONT_BODY, fg_color=SURFACE_3, button_color=ACCENT,
                           button_hover_color=ACCENT_HOVER).pack(side="left", padx=(8, 20))
        ctk.CTkButton(inner_ctrl, text="🔄 Refresh", font=FONT_BODY, width=100, fg_color=SURFACE_3,
                       hover_color=SURFACE_2, text_color=TEXT_PRIMARY, height=32,
                       corner_radius=8, command=lambda: refresh()).pack(side="right")
        content = ctk.CTkFrame(parent, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=28, pady=(0, 20))

        _loading = [None]   # holds the loading banner frame

        def refresh():
            for w in content.winfo_children(): w.destroy()
            _loading[0] = _show_loading(content, "Calculating payroll…")

            month  = month_var.get()
            unit   = unit_var.get()

            def _fetch():
                workers, att_dict = get_workers_and_attendance(month)
                sw = get_skill_wages_dict()
                return workers, sw, list(att_dict.values()), month, unit

            def _render(data):
                workers, sw, att, month, unit = data
                # Guard: abort if the content frame was destroyed (page navigated away)
                try:
                    if not content.winfo_exists():
                        return
                except Exception:
                    return
                # Clear banner
                if _loading[0]:
                    try: _loading[0].destroy()
                    except Exception: pass
                    _loading[0] = None
                for w in content.winfo_children(): w.destroy()

                if unit != "All":
                    workers = [w for w in workers if w.unit == unit]
                results, warnings = calculate_payroll(workers, sw, att, month)
                if warnings:
                    wf = ctk.CTkFrame(content, fg_color="#3D2F00", corner_radius=8); wf.pack(fill="x", pady=(0, 10))
                    ctk.CTkLabel(wf, text=f"  ⚠️  {len(warnings)} warning(s): {warnings[0]}"
                                 + (" …" if len(warnings) > 1 else ""),
                                 font=FONT_SMALL, text_color=WARNING_CLR, anchor="w").pack(padx=12, pady=8)
                if not results:
                    ef = ctk.CTkFrame(content, fg_color=CARD_BG, corner_radius=12)
                    ef.pack(fill="x", pady=30, padx=40)
                    ctk.CTkLabel(ef, text="📭", font=(FONT_FAMILY, 40)).pack(pady=(30, 6))
                    ctk.CTkLabel(ef, text="No payroll data for this period",
                                 font=FONT_HEADING, text_color=TEXT_SECONDARY).pack()
                    ctk.CTkLabel(ef, text="Enter attendance data first to see results.",
                                 font=FONT_SMALL, text_color=TEXT_MUTED).pack(pady=(4, 30))
                    return
                s = payroll_summary(results)
                mf = ctk.CTkFrame(content, fg_color="transparent"); mf.pack(fill="x", pady=(0, 18))
                mf.grid_columnconfigure((0,1,2,3,4), weight=1)
                for i, (l, v, c, ic) in enumerate([
                    ("Workers",     str(s["total_workers"]), ACCENT,      "👷"),
                    ("Total Gross", fmt_inr(s["total_gross"]), "#26A69A",  "💰"),
                    ("Total EPF",   fmt_inr(s["total_epf"]),  WARNING_CLR, "🏦"),
                    ("Total ESI",   fmt_inr(s["total_esi"]),  "#AB47BC",   "🏥"),
                    ("Total Net Pay",fmt_inr(s["total_net"]), SUCCESS,      "✅"),
                ]):
                    MetricCard(mf, l, v, color=c, icon=ic).grid(row=0, column=i, padx=5, pady=4, sticky="nsew")
                _section_label(content, "Payroll Breakdown")
                cols = ("ID","Name","Unit","Skill","Designation","Days","Gross (₹)","EPF (₹)","ESI (₹)","Net Pay (₹)")
                widths = [60,130,90,80,120,45,100,80,75,110]
                table = StyledTreeview(content, columns=cols, column_widths=widths, height=min(len(results), 14))
                table.pack(fill="both", expand=True, pady=(0, 10))
                table.insert_rows([(r.worker_id, r.worker_name, r.unit, r.skill_category,
                                    r.profile_title, r.days_present, fmt_inr(r.gross),
                                    fmt_inr(r.epf_deduction), fmt_inr(r.esi_deduction),
                                    fmt_inr(r.net_pay)) for r in results])
                def export_csv():
                    import pandas as pd
                    path = filedialog.asksaveasfilename(defaultextension=".csv",
                        filetypes=[("CSV","*.csv")], initialfile=f"Payroll_{month}.csv")
                    if path:
                        data = [{"Emp name": r.worker_name, "Total Sal": round(r.net_pay, 2),
                                 "IFSC Code": r.ifsc_code, "Account Number": r.bank_account}
                                for r in results]
                        pd.DataFrame(data).to_csv(path, index=False)
                        self.status_bar.set_message(f"✅ CSV → {path}", SUCCESS)
                        messagebox.showinfo("Export", f"CSV saved:\n{path}")
                ctk.CTkButton(content, text="⬇️  Export CSV", font=FONT_BODY_BOLD,
                               fg_color=ACCENT, hover_color=ACCENT_HOVER, height=36,
                               corner_radius=8, command=export_csv).pack(anchor="w", pady=(0, 16))

            def _on_error(exc):
                if _loading[0]:
                    try: _loading[0].destroy()
                    except Exception: pass
                self.status_bar.set_message(f"⚠️ Load error: {exc}", DANGER)

            _async_load(_fetch, _render, _on_error)

        month_var.trace_add("write", lambda *_: refresh())
        unit_var.trace_add("write", lambda *_: refresh())
        refresh()

    # ══════════════════════════════════════════════════════════════════════
    #   ATTENDANCE
    # ══════════════════════════════════════════════════════════════════════
    def _page_attendance(self, parent):
        _page_header(parent, "­ƒôï  Attendance & Earnings Entry",
                     "Enter daily attendance and manage per-worker allowances / deductions")
        tabview = ctk.CTkTabview(parent, fg_color=SURFACE_2, segmented_button_fg_color=SURFACE_3,
                                  segmented_button_selected_color=ACCENT,
                                  segmented_button_selected_hover_color=ACCENT_HOVER,
                                  segmented_button_unselected_color=SURFACE_3,
                                  segmented_button_unselected_hover_color=SIDEBAR_HOVER, corner_radius=10)
        tabview.pack(fill="both", expand=True, padx=28, pady=(0, 20))
        tab_manual = tabview.add("Ô£Å´©Å  Manual Entry"); tab_csv = tabview.add("­ƒôÑ  CSV Import")
        self._build_att_manual(tab_manual); self._build_att_csv(tab_csv)

    def _build_att_manual(self, parent):
        opts = month_options(); config = get_config()
        ctrl = ctk.CTkFrame(parent, fg_color="transparent"); ctrl.pack(fill="x", padx=12, pady=(12, 8))
        ctk.CTkLabel(ctrl, text="Month:", font=FONT_BODY_BOLD, text_color=TEXT_PRIMARY).pack(side="left")
        month_var = ctk.StringVar(value=opts[-1])
        ctk.CTkOptionMenu(ctrl, values=opts, variable=month_var, width=140, font=FONT_BODY,
                           fg_color=SURFACE_3, button_color=ACCENT,
                           button_hover_color=ACCENT_HOVER).pack(side="left", padx=(8, 20))
        ctk.CTkLabel(ctrl, text="Unit:", font=FONT_BODY_BOLD, text_color=TEXT_PRIMARY).pack(side="left")
        unit_var = ctk.StringVar(value="All")
        ctk.CTkOptionMenu(ctrl, values=_unit_filter_list(), variable=unit_var, width=140,
                           font=FONT_BODY, fg_color=SURFACE_3, button_color=ACCENT,
                           button_hover_color=ACCENT_HOVER).pack(side="left", padx=(8, 20))
        search_var_att = ctk.StringVar(value="")
        ctk.CTkEntry(ctrl, textvariable=search_var_att, placeholder_text="Search Name/ID...", width=140,
                      font=FONT_SMALL, fg_color=SURFACE, border_color=TEXT_MUTED).pack(side="left", padx=(8, 20))
        ctk.CTkLabel(ctrl, text=f"(Max days: {config.working_days})",
                      font=FONT_SMALL, text_color=TEXT_MUTED).pack(side="left")
        table_frame = ctk.CTkScrollableFrame(parent, fg_color="transparent", height=420,
                                              scrollbar_button_color=TEXT_MUTED, scrollbar_fg_color=SURFACE)
        table_frame.pack(fill="x", expand=False, padx=12, pady=(0, 4))
        self._att_entries = {}

        # ÔöÇÔöÇ Debounce helper: prevents hammering refresh on every keystroke ÔöÇÔöÇ
        _debounce_id = [None]
        def _debounced_refresh(*_):
            if _debounce_id[0]:
                try: parent.after_cancel(_debounce_id[0])
                except Exception: pass
            _debounce_id[0] = parent.after(300, refresh)

        def save_all():
            records = []
            existing_db = {a.worker_id: a for a in get_attendance(month_var.get())}
            for wid, entry in self._att_entries.items():
                # Prefer already-built detail_att; fall back to existing DB record or blank
                att = entry.get("detail_att")
                if att is None:
                    att = existing_db.get(wid)
                    if att is None:
                        att = AttendanceRecord(wid, month_var.get())
                try:
                    att.days_present = float(entry["days"].get() or 0)
                    att.overtime_hours = float(entry["ot"].get() or 0)
                except ValueError: pass
                att.month = month_var.get()
                records.append(att)
            bulk_upsert_attendance(records)
            self.status_bar.set_message(f"Ô£à Saved {len(records)} records for {month_var.get()}", SUCCESS)
            messagebox.showinfo("Saved", f"{len(records)} records saved for {month_var.get()}.")

        def refresh():
            for w in table_frame.winfo_children(): w.destroy()
            self._att_entries.clear()
            workers = get_all_workers()
            if unit_var.get() != "All":
                workers = [w for w in workers if w.unit == unit_var.get()]
            q_att = search_var_att.get().strip().lower()
            if q_att:
                workers = [w for w in workers if q_att in w.name.lower() or q_att in w.worker_id.lower()]
            existing = {a.worker_id: a for a in get_attendance(month_var.get())}
            sw_dict = get_skill_wages_dict()
            if not workers:
                ctk.CTkLabel(table_frame, text="No workers found. Add workers first.",
                              font=FONT_BODY, text_color=TEXT_MUTED).pack(pady=30); return
            ctk.CTkLabel(table_frame, text="Days Present & Overtime", font=FONT_SUBHEADING,
                          text_color=TEXT_PRIMARY, anchor="w").pack(fill="x", pady=(4, 6))
            hdr = ctk.CTkFrame(table_frame, fg_color=ACCENT_DARK, corner_radius=6)
            hdr.pack(fill="x", pady=(0, 2))
            cols = [("ID",55), ("Name",110), ("Unit",75), ("Skill",70), ("Designation",90), ("Rate/Day",55), ("Days",55), ("OT Hours",80)]
            for txt, w in cols:
                ctk.CTkLabel(hdr, text=txt, font=(FONT_FAMILY, 10, "bold"),
                              text_color="white", anchor="w", width=w).pack(side="left", padx=6, pady=5)
            for i, w in enumerate(workers):
                att = existing.get(w.worker_id, AttendanceRecord(w.worker_id, month_var.get()))
                sw = sw_dict.get(w.skill_category)
                rate = f"\u20b9{sw.daily_wage}" if sw else "\u2014"
                bg = SURFACE_2 if i % 2 == 0 else SURFACE_3

                worker_container = ctk.CTkFrame(table_frame, fg_color=bg, corner_radius=4)
                worker_container.pack(fill="x", pady=1)

                row = ctk.CTkFrame(worker_container, fg_color="transparent")
                row.pack(fill="x")

                ctk.CTkLabel(row, text=w.worker_id, font=FONT_SMALL, text_color=TEXT_PRIMARY, width=55).pack(side="left", padx=6, pady=4)
                ctk.CTkLabel(row, text=w.name, font=FONT_SMALL, text_color=TEXT_PRIMARY, width=110, anchor="w").pack(side="left", padx=6)
                ctk.CTkLabel(row, text=w.unit, font=FONT_TINY, text_color=TEXT_SECONDARY, width=75, anchor="w").pack(side="left", padx=6)
                ctk.CTkLabel(row, text=w.skill_category, font=FONT_TINY, text_color=TEXT_SECONDARY, width=70, anchor="w").pack(side="left", padx=6)
                ctk.CTkLabel(row, text=w.designation, font=FONT_TINY, text_color=TEXT_SECONDARY, width=90, anchor="w").pack(side="left", padx=6)
                ctk.CTkLabel(row, text=rate, font=FONT_TINY, text_color=TEXT_SECONDARY, width=55, anchor="w").pack(side="left", padx=6)

                days_var = ctk.StringVar(value=str(att.days_present))
                ctk.CTkEntry(row, textvariable=days_var, width=55, height=24, font=FONT_SMALL,
                              fg_color=SURFACE, border_color=TEXT_MUTED, corner_radius=4).pack(side="left", padx=6)

                ot_var = ctk.StringVar(value=str(att.overtime_hours))
                ctk.CTkEntry(row, textvariable=ot_var, width=80, height=24, font=FONT_SMALL,
                              fg_color=SURFACE, border_color=TEXT_MUTED, corner_radius=4).pack(side="left", padx=6)

                # ÔöÇÔöÇ Lazy detail panel: only built on first expand ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ
                details = ctk.CTkFrame(worker_container, fg_color="transparent")
                shown    = [False]
                built    = [False]       # track whether widgets have been created
                entry_data = {"days": days_var, "ot": ot_var}  # no detail_att yet
                self._att_entries[w.worker_id] = entry_data

                # Capture loop vars
                def make_toggle(d=details, tb_ref=[None], sh=shown, blt=built,
                                 ed=entry_data, wid=w.worker_id, att_snap=att):
                    btn = ctk.CTkButton(row, text="\u25bc", font=FONT_SMALL, width=30, height=24,
                        corner_radius=4, fg_color=SURFACE_3, hover_color=SURFACE_2,
                        text_color=TEXT_SECONDARY)
                    btn.pack(side="left", padx=6)
                    tb_ref[0] = btn
                    def toggle():
                        if sh[0]:
                            d.pack_forget()
                            btn.configure(text="\u25bc")
                            sh[0] = False
                        else:
                            # Lazy-build on first open
                            if not blt[0]:
                                self._build_detail_fields(d, wid, att_snap, ed)
                                blt[0] = True
                            d.pack(fill="x", padx=10, pady=(6, 10))
                            btn.configure(text="\u25b2")
                            sh[0] = True
                    btn.configure(command=toggle)
                make_toggle()

        # Save button lives OUTSIDE the scrollable table_frame ÔÇö always visible
        ctk.CTkButton(parent, text="\U0001f4be  Save All Attendance", font=FONT_BODY_BOLD,
                       fg_color=SUCCESS, hover_color="#2E7D32", height=40,
                       corner_radius=8, command=save_all).pack(fill="x", padx=12, pady=(4, 12))

        month_var.trace_add("write", lambda *_: refresh())
        unit_var.trace_add("write", lambda *_: refresh())
        search_var_att.trace_add("write", _debounced_refresh)
        refresh()

    def _build_detail_fields(self, parent, worker_id, att, entry_data=None):
        """Build the expandable allowance/deduction fields panel.
        entry_data: the dict from self._att_entries[worker_id] ÔÇö updated in-place.
        """
        fields = [
            ("DA (\u20b9)","da"),("HRA (\u20b9)","hra"),("CCA (\u20b9)","cca"),
            ("Arrears (\u20b9)","arrears"),("N&FH Wages (\u20b9)","nfh_wages"),
            ("Leave Wages (\u20b9)","leave_wages"),("Bonus (\u20b9)","bonus"),
            ("Maternity (\u20b9)","maternity_benefit"),("Advance Pay (\u20b9)","advances_pay"),
            ("Other Allow. (\u20b9)","other_allowances"),
            ("EPF Override (0=auto)","epf_override"),("ESI Override (0=auto)","esi_override"),
            ("Welfare Fund (\u20b9)","welfare_fund"),("TDS (\u20b9)","tds"),
            ("Prof. Tax (\u20b9)","profession_tax"),("Adv. Repayment (\u20b9)","advance_repayment"),
            ("Fine (\u20b9)","fine"),("Loss/Damages (\u20b9)","loss_damages"),
            ("Other Ded. (\u20b9)","other_deductions"),
        ]
        vars_dict = {}
        row_frame = None
        for i, (label, attr) in enumerate(fields):
            if i % 3 == 0:
                row_frame = ctk.CTkFrame(parent, fg_color="transparent")
                row_frame.pack(fill="x", pady=2)
            f = ctk.CTkFrame(row_frame, fg_color="transparent")
            f.pack(side="left", expand=True, fill="x", padx=4)
            ctk.CTkLabel(f, text=label, font=FONT_TINY, text_color=TEXT_SECONDARY, anchor="w").pack(anchor="w")
            var = ctk.StringVar(value=str(getattr(att, attr, 0.0)))
            ctk.CTkEntry(f, textvariable=var, width=110, height=24, font=FONT_SMALL,
                          fg_color=SURFACE, border_color=TEXT_MUTED, corner_radius=4).pack(anchor="w")
            vars_dict[attr] = var

        def build_record():
            kwargs = {"worker_id": worker_id, "month": att.month}
            for _, attr in fields:
                try: kwargs[attr] = float(vars_dict[attr].get() or 0)
                except ValueError: kwargs[attr] = 0.0
            # Carry through days/ot from the main row entry if entry_data is available
            if entry_data:
                try: kwargs["days_present"] = float(entry_data["days"].get() or 0)
                except (ValueError, KeyError): kwargs["days_present"] = att.days_present
                try: kwargs["overtime_hours"] = float(entry_data["ot"].get() or 0)
                except (ValueError, KeyError): kwargs["overtime_hours"] = att.overtime_hours
            return AttendanceRecord(**kwargs)

        def update(*_):
            target = entry_data if entry_data is not None else (
                self._att_entries.get(worker_id) or {})
            if target is not None:
                target["detail_att"] = build_record()

        # Use a single coalesced trace ÔÇö only one write-back per field change
        _pending = [None]
        def _coalesced(*_):
            if _pending[0]:
                try: parent.after_cancel(_pending[0])
                except Exception: pass
            _pending[0] = parent.after(400, update)
        for _, attr in fields:
            vars_dict[attr].trace_add("write", _coalesced)
        update()

    def _build_att_csv(self, parent):
        ctk.CTkLabel(parent, text="Upload a CSV to import attendance data in bulk.",
                      font=FONT_BODY, text_color=TEXT_SECONDARY, anchor="w").pack(padx=16, pady=(16, 8))
        info = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=8); info.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(info, text="Supported columns:", font=FONT_BODY_BOLD,
                      text_color=TEXT_PRIMARY).pack(padx=12, pady=(10, 2), anchor="w")
        ctk.CTkLabel(info, text="worker_id, days_present, da, hra, cca, overtime_hours,\n"
                     "bonus, arrears, advance_repayment, epf_override, esi_override ÔÇª",
                      font=FONT_TINY, text_color=TEXT_MUTED, justify="left").pack(padx=12, pady=(0, 10), anchor="w")
        def download_tpl():
            workers = get_all_workers()
            tpl = ["worker_id","days_present","da","bonus","overtime_hours","advance_repayment"]
            path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV","*.csv")],
                                                 initialfile="attendance_template.csv")
            if path:
                with open(path, "w", newline="") as f:
                    wr = csv.writer(f); wr.writerow(tpl)
                    for w in workers: wr.writerow([w.worker_id] + [0]*(len(tpl)-1))
        ctk.CTkButton(parent, text="Ô¼ç´©Å  Download Template", font=FONT_BODY, fg_color=SURFACE_3,
                       hover_color=SURFACE_2, text_color=TEXT_PRIMARY, height=32,
                       corner_radius=8, command=download_tpl).pack(padx=16, anchor="w", pady=(0, 12))
        ctk.CTkFrame(parent, height=1, fg_color=TEXT_MUTED).pack(fill="x", padx=16, pady=(0, 10))
        ctrl = ctk.CTkFrame(parent, fg_color="transparent"); ctrl.pack(fill="x", padx=16)
        ctk.CTkLabel(ctrl, text="Import for Month:", font=FONT_BODY_BOLD, text_color=TEXT_PRIMARY).pack(side="left")
        imp_month = ctk.StringVar(value=month_options()[-1])
        ctk.CTkOptionMenu(ctrl, values=month_options(), variable=imp_month, width=140, font=FONT_BODY,
                           fg_color=SURFACE_3, button_color=ACCENT,
                           button_hover_color=ACCENT_HOVER).pack(side="left", padx=(8, 0))
        def import_csv():
            fp = filedialog.askopenfilename(filetypes=[("CSV","*.csv"),("All","*.*")])
            if not fp: return
            res = import_attendance_from_csv(fp, imp_month.get())
            msg = f"Imported {res['imported']} records."
            self.status_bar.set_message(f"Ô£à {msg}", SUCCESS)
            if res["errors"]: messagebox.showwarning("Import", msg+"\n\nErrors:\n"+"\n".join(res["errors"][:10]))
            else: messagebox.showinfo("Import", f"Ô£à {msg}")
        ctk.CTkButton(parent, text="­ƒôÑ  Import CSV", font=FONT_BODY_BOLD, fg_color=ACCENT,
                       hover_color=ACCENT_HOVER, height=38, corner_radius=8,
                       command=import_csv).pack(padx=16, anchor="w", pady=(12, 20))





    # ══════════════════════════════════════════════════════════════════════
    #   WORKERS
    # ══════════════════════════════════════════════════════════════════════
    def _page_workers(self, parent):
        _page_header(parent, "👷  Worker Master Data",
                     "Add, edit, or delete workers — click a row to edit inline")
        tabview = ctk.CTkTabview(parent, fg_color=SURFACE_2, segmented_button_fg_color=SURFACE_3,
                                  segmented_button_selected_color=ACCENT,
                                  segmented_button_selected_hover_color=ACCENT_HOVER,
                                  segmented_button_unselected_color=SURFACE_3,
                                  segmented_button_unselected_hover_color=SIDEBAR_HOVER, corner_radius=10)
        tabview.pack(fill="both", expand=True, padx=28, pady=(0, 20))
        tab_all = tabview.add("👥 All Workers")
        tab_add = tabview.add("➕ Add New Worker")
        form_vars = {}

        SKILL_COLORS_MAP = {
            "Skilled":      ("#22C55E", "#052E16"),
            "Semi-Skilled": ("#F59E0B", "#2D1B00"),
            "Unskilled":    ("#3B82F6", "#0A1628"),
        }

        def _skill_color(s):
            return SKILL_COLORS_MAP.get(s, (ACCENT, SURFACE_3))[0]

        def _bank_names():
            bs = get_all_banks()
            return bs if bs else ["(No banks — add in Settings)"]

        # ══════════════════════════════════════════════════════════════════
        # ── ALL WORKERS TAB ───────────────────────────────────────────────
        # ══════════════════════════════════════════════════════════════════
        # ── Filter bar ───────────────────────────────────────────────────
        fc = ctk.CTkFrame(tab_all, fg_color=SURFACE_2, corner_radius=10)
        fc.pack(fill="x", padx=8, pady=(10, 8))
        inner_fc = ctk.CTkFrame(fc, fg_color="transparent")
        inner_fc.pack(fill="x", padx=14, pady=10)
        ctk.CTkLabel(inner_fc, text="Unit:", font=FONT_BODY_BOLD, text_color=TEXT_PRIMARY).pack(side="left")
        filt_var = ctk.StringVar(value="All")
        ctk.CTkOptionMenu(inner_fc, values=_unit_filter_list(), variable=filt_var, width=140,
                           font=FONT_BODY, fg_color=SURFACE_3, button_color=ACCENT,
                           button_hover_color=ACCENT_HOVER).pack(side="left", padx=(8, 20))
        search_var_wk = ctk.StringVar(value="")
        ctk.CTkLabel(inner_fc, text="🔍", font=(FONT_FAMILY, 13), text_color=TEXT_SECONDARY).pack(side="left")
        ctk.CTkEntry(inner_fc, textvariable=search_var_wk, placeholder_text="Search by Name or ID…", width=200,
                      font=FONT_SMALL, fg_color=SURFACE, border_color=TEXT_MUTED,
                      corner_radius=8).pack(side="left", padx=(4, 0))

        # ── Table area ───────────────────────────────────────────────────
        table_container = ctk.CTkFrame(tab_all, fg_color="transparent")
        table_container.pack(fill="both", expand=True, padx=8)

        # ── Per-cell editor state (persists across update_table calls) ────
        _cell_editor   = [None]   # current single-cell overlay widget
        _editing_wid   = [None]   # worker_id of the selected row
        _editing_item  = [None]   # treeview item id
        _pending_flush = [None]   # fn() → writes open cell value into treeview before save

        # Columns that use a Combobox (not a free-text Entry)
        COMBO_COLS = {"Unit", "Skill", "Bank"}

        _ENTRY_KW = {
            "bg": "#0D1B35", "fg": TEXT_PRIMARY,
            "insertbackground": TEXT_PRIMARY,
            "relief": "flat", "font": (FONT_FAMILY, 9),
            "highlightthickness": 1,
            "highlightbackground": ACCENT,
            "highlightcolor": ACCENT,
        }

        # Style ttk Combobox dropdown to match dark theme
        _cb_style = ttk.Style()
        _cb_style.configure("Dark.TCombobox",
                            fieldbackground="#0D1B35",
                            background="#0D1B35",
                            foreground=TEXT_PRIMARY,
                            arrowcolor=TEXT_PRIMARY,
                            borderwidth=0)
        _cb_style.map("Dark.TCombobox",
                      fieldbackground=[("readonly", "#0D1B35")],
                      foreground=[("readonly", TEXT_PRIMARY)],
                      background=[("readonly", "#0D2A4E"), ("active", ACCENT)])

        def _destroy_cell():
            """Flush pending value then destroy the overlay widget."""
            if _pending_flush[0]:
                try: _pending_flush[0]()
                except Exception: pass
                _pending_flush[0] = None
            if _cell_editor[0]:
                try: _cell_editor[0].destroy()
                except Exception: pass
                _cell_editor[0] = None

        def _auto_save_row():
            """Silently save the current row to DB WITHOUT rebuilding the table.
            Called automatically when the user switches to a different row so
            edits on the previous row are never lost.
            """
            # flush open entry value into treeview first
            if _pending_flush[0]:
                try: _pending_flush[0]()
                except Exception: pass
                _pending_flush[0] = None
            # destroy cell widget (pending_flush already cleared)
            if _cell_editor[0]:
                try: _cell_editor[0].destroy()
                except Exception: pass
                _cell_editor[0] = None
            wid  = _editing_wid[0]
            item = _editing_item[0]
            if not wid or not item: return
            try:
                tree = getattr(action_bar, '_tree_ref', None)
                if tree is None: return
                vals = tree.item(item)["values"]
            except Exception: return
            if not vals: return
            name = str(vals[1]).strip()
            if not name: return   # skip silently if name was cleared
            w_obj = get_worker_by_id(wid)
            bname = str(vals[5]).strip()
            if bname.startswith("(No"): bname = ""
            try:
                upsert_worker(Worker(
                    worker_id=wid, name=name,
                    unit=str(vals[2]).strip(),
                    skill_category=str(vals[3]).strip(),
                    designation=str(vals[4]).strip(),
                    bank_name=bname,
                    bank_account=str(vals[6]).strip(),
                    ifsc_code=str(vals[7]).strip(),
                    uan_number=str(vals[8]).strip(),
                    esic_number=str(vals[9]).strip(),
                    joining_date=w_obj.joining_date if w_obj else "",
                    active=w_obj.active if w_obj else True))
                self.status_bar.set_message(f"\u2705 {wid} auto-saved!", SUCCESS)
            except Exception:
                pass   # silent — user can always Save explicitly

        # ── Action bar (built once under the table container) ─────────────
        action_bar = ctk.CTkFrame(tab_all, fg_color="#0D2A4E", corner_radius=8, height=42)
        _ab_lbl = ctk.CTkLabel(action_bar, text="", font=FONT_SMALL, text_color=TEXT_SECONDARY)
        _ab_lbl.pack(side="left", padx=14)

        def _ab_save():
            # _destroy_cell() flushes _pending_flush FIRST so the value
            # lands in the treeview before we read vals below.
            _destroy_cell()
            wid = _editing_wid[0]; item = _editing_item[0]
            if not wid or not item: return
            # Read live values straight from the treeview cells
            vals = action_bar._tree_ref.item(item)["values"]
            if not vals: return
            w_obj = get_worker_by_id(wid)
            bname = str(vals[5]).strip()
            if bname.startswith("(No"): bname = ""
            name = str(vals[1]).strip()
            if not name:
                messagebox.showerror("Required", "Name cannot be empty."); return
            upsert_worker(Worker(
                worker_id=wid,
                name=name,
                unit=str(vals[2]).strip(),
                skill_category=str(vals[3]).strip(),
                designation=str(vals[4]).strip(),
                bank_name=bname,
                bank_account=str(vals[6]).strip(),
                ifsc_code=str(vals[7]).strip(),
                uan_number=str(vals[8]).strip(),
                esic_number=str(vals[9]).strip(),
                joining_date=w_obj.joining_date if w_obj else "",
                active=w_obj.active if w_obj else True))
            self.status_bar.set_message(f"✅ Worker {wid} saved!", SUCCESS)
            _editing_wid[0] = None; _editing_item[0] = None
            action_bar.pack_forget(); update_table()

        def _ab_cancel():
            _destroy_cell()
            _editing_wid[0] = None; _editing_item[0] = None
            action_bar.pack_forget(); update_table()

        def _ab_toggle():
            _destroy_cell()
            wid = _editing_wid[0]
            if not wid: return
            w = get_worker_by_id(wid)
            if not w: return
            if w.active:
                if messagebox.askyesno("Confirm", f"Deactivate '{w.name}' ({wid})?"):
                    deactivate_worker(wid)
                    self.status_bar.set_message(f"Worker {wid} deactivated.", WARNING_CLR)
                    action_bar.pack_forget(); update_table()
            else:
                reactivate_worker(wid)
                self.status_bar.set_message(f"Worker {wid} re-activated.", SUCCESS)
                action_bar.pack_forget(); update_table()

        def _ab_delete():
            _destroy_cell()
            wid = _editing_wid[0]
            if not wid: return
            w = get_worker_by_id(wid)
            wname = w.name if w else wid
            if messagebox.askyesno("⚠️ Delete",
                f"Permanently delete '{wname}' ({wid}) and ALL attendance?\nCannot undo.", icon="warning"):
                delete_worker(wid)
                self.status_bar.set_message(f"Worker {wid} deleted.", DANGER)
                action_bar.pack_forget(); update_table()

        for txt, fg, cmd in [
            ("💾 Save",              SUCCESS,     _ab_save),
            ("✖ Cancel",            SURFACE_2,   _ab_cancel),
            ("⏸ Toggle",            WARNING_CLR, _ab_toggle),
            ("🗑️ Delete",           DANGER,      _ab_delete),
        ]:
            ctk.CTkButton(action_bar, text=txt, font=FONT_SMALL,
                           fg_color=fg, hover_color=ACCENT_HOVER if fg == SUCCESS else fg,
                           height=30, corner_radius=6, width=90,
                           command=cmd).pack(side="right", padx=(0, 8), pady=6)

        def _show_action_bar(tree, item, w_obj):
            action_bar._tree_ref = tree       # store reference for save to read values
            _editing_wid[0]  = w_obj.worker_id
            _editing_item[0] = item
            _ab_lbl.configure(text=f"✏️  {w_obj.worker_id}  —  {w_obj.name}")
            if not action_bar.winfo_ismapped():
                action_bar.pack(fill="x", padx=8, pady=(4, 0))

        # ── Cell click handler ────────────────────────────────────────────
        def _on_cell_click(tree, item, col_name, col_idx, bbox, worker_map):
            _destroy_cell()
            if col_name in ("ID", "Status"): return   # non-editable columns

            x, y, w_, h = bbox
            current = str(tree.item(item)["values"][col_idx])

            if col_name in COMBO_COLS:
                choices = {
                    "Unit":  _unit_list,
                    "Skill": lambda: SKILL_CATEGORIES,
                    "Bank":  _bank_names,
                }[col_name]()
                var = tk.StringVar(value=current)
                cb = ttk.Combobox(tree, textvariable=var, values=choices,
                                   state="readonly", font=(FONT_FAMILY, 9),
                                   style="Dark.TCombobox")
                cb.place(x=x, y=y, width=w_, height=h)
                cb.focus()
                def _cb_sel(ev=None, _item=item, _col_name=col_name, _var=var):
                    tree.set(_item, _col_name, _var.get())
                    _destroy_cell()
                cb.bind("<<ComboboxSelected>>", _cb_sel)
                cb.bind("<Escape>", lambda e: _destroy_cell())
                _cell_editor[0] = cb
            else:
                var = tk.StringVar(value=current)
                ent = tk.Entry(tree, textvariable=var, **_ENTRY_KW)
                ent.place(x=x, y=y, width=w_, height=h)
                ent.select_range(0, "end")
                ent.icursor("end")
                ent.focus()
                # Register a flush fn so _ab_save() can pull the value
                # before the Entry's FocusOut fires (race condition fix)
                def _flush(_item=item, _col_name=col_name, _var=var):
                    try: tree.set(_item, _col_name, _var.get())
                    except Exception: pass
                _pending_flush[0] = _flush
                def _commit(ev=None, _fl=_flush):
                    _fl()
                    _pending_flush[0] = None
                    _destroy_cell()
                ent.bind("<Return>",   _commit)
                ent.bind("<FocusOut>", _commit)
                ent.bind("<Escape>",   lambda e: (_pending_flush.__setitem__(0, None), _destroy_cell()))
                _cell_editor[0] = ent

        _wk_debounce  = _make_debouncer(tab_all)
        _wk_loading   = [None]

        def update_table(*_):
            _destroy_cell()
            action_bar.pack_forget()
            for w in table_container.winfo_children(): w.destroy()
            _wk_loading[0] = _show_loading(table_container, "Loading workers…")

            filt = filt_var.get()
            q    = search_var_wk.get().strip().lower()

            def _fetch():
                return get_all_workers(active_only=False)

            def _render(workers):
                try:
                    if not table_container.winfo_exists():
                        return
                except Exception:
                    return
                if _wk_loading[0]:
                    try: _wk_loading[0].destroy()
                    except Exception: pass
                    _wk_loading[0] = None
                for w in table_container.winfo_children(): w.destroy()

                if filt != "All":
                    workers = [w for w in workers if w.unit == filt]
                if q:
                    workers = [w for w in workers if q in w.name.lower() or q in w.worker_id.lower()]
                if not workers:
                    ef = ctk.CTkFrame(table_container, fg_color=CARD_BG, corner_radius=12)
                    ef.pack(fill="x", pady=30, padx=30)
                    ctk.CTkLabel(ef, text="👤", font=(FONT_FAMILY, 36)).pack(pady=(20, 4))
                    ctk.CTkLabel(ef, text="No workers yet", font=FONT_HEADING, text_color=TEXT_SECONDARY).pack()
                    ctk.CTkLabel(ef, text='Use "➕ Add New Worker" tab.',
                                 font=FONT_SMALL, text_color=TEXT_MUTED).pack(pady=(4, 20))
                    return

                cols = ("ID", "Name", "Unit", "Skill", "Designation", "Bank", "A/C", "IFSC", "UAN", "ESIC", "Status")
                widths = [55, 140, 80, 75, 90, 100, 110, 95, 85, 75, 50]
                table = StyledTreeview(table_container, columns=cols, column_widths=widths,
                                        height=min(len(workers), 12))
                table.pack(fill="both", expand=True, pady=(4, 0))
                table.insert_rows([(w.worker_id, w.name, w.unit, w.skill_category,
                                    w.designation, w.bank_name, w.bank_account, w.ifsc_code,
                                    w.uan_number, w.esic_number,
                                    "● Active" if w.active else "○ Inactive") for w in workers])
                for item in table.tree.get_children():
                    vals = table.tree.item(item, "values")
                    skill  = str(vals[3])  if len(vals) > 3  else ""
                    status = str(vals[10]) if len(vals) > 10 else ""
                    if status.startswith("○"):
                        table.tree.item(item, tags=("inactive",))
                    elif skill == "Skilled":
                        table.tree.item(item, tags=("skilled",))
                    elif "Semi" in skill:
                        table.tree.item(item, tags=("semi",))

                ctk.CTkLabel(table_container,
                    text="💡 Click any cell to edit  •  Switching rows auto-saves  •  Click Status to toggle active",
                    font=FONT_TINY, text_color=TEXT_MUTED).pack(anchor="w", pady=(2, 0))

                worker_map = {w.worker_id: w for w in workers}

                def _on_click(event):
                    item = table.tree.identify_row(event.y)
                    col  = table.tree.identify_column(event.x)
                    if not item or not col:
                        _destroy_cell(); return
                    col_idx  = int(col.lstrip('#')) - 1
                    if col_idx < 0 or col_idx >= len(cols): return
                    col_name = cols[col_idx]
                    vals = table.tree.item(item)["values"]
                    if not vals: return
                    w = worker_map.get(str(vals[0]))
                    if not w: return
                    if _editing_item[0] and _editing_item[0] != item:
                        _auto_save_row()
                    if col_name == "Status":
                        _editing_wid[0] = w.worker_id
                        if w.active:
                            if messagebox.askyesno("Deactivate",
                                    f"Deactivate '{w.name}' ({w.worker_id})?"):
                                deactivate_worker(w.worker_id)
                                self.status_bar.set_message(
                                    f"Worker {w.worker_id} deactivated.", WARNING_CLR)
                                action_bar.pack_forget(); update_table()
                        else:
                            reactivate_worker(w.worker_id)
                            self.status_bar.set_message(
                                f"Worker {w.worker_id} re-activated.", SUCCESS)
                            action_bar.pack_forget(); update_table()
                        return
                    _show_action_bar(table.tree, item, w)
                    bbox = table.tree.bbox(item, col)
                    if not bbox: return
                    _on_cell_click(table.tree, item, col_name, col_idx, bbox, worker_map)

                table.tree.bind("<ButtonRelease-1>", _on_click)

            _async_load(_fetch, _render)

        filt_var.trace_add("write", update_table)
        search_var_wk.trace_add("write", _wk_debounce(update_table))
        update_table()

        # ══════════════════════════════════════════════════════════════════
        # ── ADD NEW WORKER FORM ───────────────────────────────────────────
        # ══════════════════════════════════════════════════════════════════
        def _clear_form():
            for k in ["wid", "name", "designation", "bank_acc", "ifsc", "uan", "esic"]:
                form_vars[k].set("")
            form_vars["join"].set(datetime.date.today().strftime("%d/%m/%Y"))
            b = get_all_units()
            form_vars["unit"].set(b[0] if b else "")
            form_vars["skill"].set(SKILL_CATEGORIES[-1])
            bl = get_all_banks()
            form_vars["bank_name"].set(bl[0] if bl else "")
            self.status_bar.set_message("Form cleared — ready to add a new worker.")

        form = ctk.CTkFrame(tab_add, fg_color=CARD_BG, corner_radius=10)
        form.pack(fill="x", padx=16, pady=16)
        fh = ctk.CTkFrame(form, fg_color="transparent"); fh.pack(fill="x", padx=16, pady=(16, 10))
        ctk.CTkLabel(fh, text="New Worker Registration", font=FONT_HEADING,
                      text_color=TEXT_PRIMARY).pack(side="left")
        ctk.CTkButton(fh, text="🧹 Clear", font=FONT_SMALL, fg_color=SURFACE_3,
                       hover_color=SURFACE_2, text_color=TEXT_SECONDARY, height=28, width=80,
                       corner_radius=6, command=lambda: _clear_form()).pack(side="right")
        ff = ctk.CTkFrame(form, fg_color="transparent"); ff.pack(fill="x", padx=16, pady=(0, 10))
        ff.grid_columnconfigure((0, 1, 2), weight=1)

        def mkf(p, lbl, r, c, default=""):
            f = ctk.CTkFrame(p, fg_color="transparent"); f.grid(row=r, column=c, padx=8, pady=4, sticky="ew")
            ctk.CTkLabel(f, text=lbl, font=FONT_SMALL, text_color=TEXT_SECONDARY).pack(anchor="w")
            v = ctk.StringVar(value=default)
            ctk.CTkEntry(f, textvariable=v, height=30, font=FONT_BODY, fg_color=SURFACE,
                          border_color=TEXT_MUTED, corner_radius=6).pack(fill="x")
            return v

        wid_var    = mkf(ff, "Worker ID *", 0, 0)
        wname_var  = mkf(ff, "Full Name *", 0, 1)
        wdesig_var = mkf(ff, "Designation (e.g. Sweeper)", 0, 2)

        bf2 = ctk.CTkFrame(ff, fg_color="transparent"); bf2.grid(row=1, column=0, padx=8, pady=4, sticky="ew")
        ctk.CTkLabel(bf2, text="Unit *", font=FONT_SMALL, text_color=TEXT_SECONDARY).pack(anchor="w")
        units = _unit_list()
        unit_var = ctk.StringVar(value=units[0] if units else "")
        ctk.CTkOptionMenu(bf2, values=units, variable=unit_var, font=FONT_BODY,
                           fg_color=SURFACE, button_color=ACCENT,
                           button_hover_color=ACCENT_HOVER, height=30).pack(fill="x")

        skf2 = ctk.CTkFrame(ff, fg_color="transparent"); skf2.grid(row=1, column=1, padx=8, pady=4, sticky="ew")
        ctk.CTkLabel(skf2, text="Skill Category *  (determines wage)", font=FONT_SMALL,
                      text_color=TEXT_SECONDARY).pack(anchor="w")
        skill_var = ctk.StringVar(value=SKILL_CATEGORIES[-1])
        skill_menu2 = ctk.CTkOptionMenu(skf2, values=SKILL_CATEGORIES, variable=skill_var,
            font=FONT_BODY, fg_color=SURFACE, button_color=_skill_color(skill_var.get()),
            button_hover_color=ACCENT_HOVER, height=30)
        skill_menu2.pack(fill="x")
        skill_var.trace_add("write", lambda *_: skill_menu2.configure(button_color=_skill_color(skill_var.get())))

        wjoin_var = mkf(ff, "Joining Date (DD/MM/YYYY)", 1, 2, datetime.date.today().strftime("%d/%m/%Y"))
        wbank_var = mkf(ff, "Bank Account Number", 2, 0)

        bnf2 = ctk.CTkFrame(ff, fg_color="transparent"); bnf2.grid(row=2, column=1, padx=8, pady=4, sticky="ew")
        ctk.CTkLabel(bnf2, text="Bank Name  (select or ➕ add)", font=FONT_SMALL,
                      text_color=TEXT_SECONDARY).pack(anchor="w")
        bnf2_row = ctk.CTkFrame(bnf2, fg_color="transparent"); bnf2_row.pack(fill="x")
        wbname_var = ctk.StringVar()
        bank_om2 = ctk.CTkOptionMenu(bnf2_row, values=_bank_names(), variable=wbname_var,
            font=FONT_BODY, fg_color=SURFACE, button_color=ACCENT,
            button_hover_color=ACCENT_HOVER, height=30, width=160)
        bank_om2.pack(side="left", fill="x", expand=True)

        def _form_add_bank():
            dlg = ctk.CTkToplevel(self)
            dlg.title("Add Bank"); dlg.geometry("300x130"); dlg.grab_set(); dlg.resizable(False, False)
            nv = ctk.StringVar()
            ctk.CTkLabel(dlg, text="Bank Name:", font=FONT_SMALL, text_color=TEXT_SECONDARY
                          ).pack(padx=16, pady=(14, 4), anchor="w")
            ctk.CTkEntry(dlg, textvariable=nv, font=FONT_BODY, fg_color=SURFACE,
                          border_color=TEXT_MUTED, height=32).pack(fill="x", padx=16)
            def _sv():
                n = nv.get().strip()
                if not n: return
                try:
                    add_bank(n); bank_om2.configure(values=_bank_names()); wbname_var.set(n)
                    self.status_bar.set_message(f"✅ Bank '{n}' added!", SUCCESS); dlg.destroy()
                except Exception as e: messagebox.showerror("Error", str(e), parent=dlg)
            ctk.CTkButton(dlg, text="➕ Add", font=FONT_BODY_BOLD, fg_color=SUCCESS,
                           hover_color="#16A34A", height=32, corner_radius=6, command=_sv).pack(pady=10)
        ctk.CTkButton(bnf2_row, text="➕", font=FONT_BODY_BOLD, width=34, height=30,
                       fg_color=SUCCESS, hover_color="#16A34A", corner_radius=6,
                       command=_form_add_bank).pack(side="left", padx=(6, 0))

        wifsc_var = mkf(ff, "IFSC Code", 2, 2)
        wuan_var  = mkf(ff, "UAN / PF ID Number", 3, 0)
        wesic_var = mkf(ff, "ESIC IP Number", 3, 1)

        initial_banks = _bank_names()
        wbname_var.set(initial_banks[0] if initial_banks else "")

        form_vars.update({
            "wid": wid_var, "name": wname_var, "designation": wdesig_var,
            "unit": unit_var, "skill": skill_var, "join": wjoin_var,
            "bank_acc": wbank_var, "bank_name": wbname_var, "ifsc": wifsc_var,
            "uan": wuan_var, "esic": wesic_var,
        })

        def save_worker():
            wid = wid_var.get().strip().upper(); wname = wname_var.get().strip()
            if not wid or not wname:
                messagebox.showerror("Required", "Worker ID and Name are required."); return
            b = unit_var.get()
            if not b or b == "(No units)":
                messagebox.showerror("Required", "Create a Unit first (🏢 Units)."); return
            bname = wbname_var.get().strip()
            if bname.startswith("(No"): bname = ""
            upsert_worker(Worker(
                worker_id=wid, name=wname, designation=wdesig_var.get().strip(),
                bank_account=wbank_var.get().strip(), bank_name=bname,
                ifsc_code=wifsc_var.get().strip(), uan_number=wuan_var.get().strip(),
                esic_number=wesic_var.get().strip(), joining_date=wjoin_var.get().strip(),
                active=True, unit=b, skill_category=skill_var.get()))
            self.status_bar.set_message(f"✅ Worker {wid} saved!", SUCCESS)
            messagebox.showinfo("Saved", f"Worker {wid} saved!")
            _clear_form(); update_table()

        ctk.CTkButton(form, text="💾  Save Worker", font=FONT_BODY_BOLD, fg_color=SUCCESS,
                       hover_color="#2E7D32", height=40, corner_radius=8,
                       command=save_worker).pack(pady=(4, 16))


    # ══════════════════════════════════════════════════════════════════════
    #   UNITS
    # ══════════════════════════════════════════════════════════════════════
    def _page_units(self, parent):
        _page_header(parent, "🏢  Unit Management",
                     "Add, rename, or remove company units")
        content = ctk.CTkFrame(parent, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=28, pady=(0, 20))

        def refresh():
            for w in content.winfo_children(): w.destroy()
            units = get_all_units(); counts = unit_worker_count()

            # Add card
            add_card = ctk.CTkFrame(content, fg_color=CARD_BG, corner_radius=14, border_width=1, border_color=CARD_BORDER)
            add_card.pack(fill="x", pady=(0, 18))
            ctk.CTkFrame(add_card, height=3, corner_radius=0, fg_color=ACCENT).pack(fill="x")
            add_inner = ctk.CTkFrame(add_card, fg_color="transparent")
            add_inner.pack(fill="x", padx=20, pady=16)
            ctk.CTkLabel(add_inner, text="➕  New Unit", font=FONT_HEADING,
                          text_color=TEXT_PRIMARY).pack(anchor="w", pady=(0, 10))
            add_row = ctk.CTkFrame(add_inner, fg_color="transparent"); add_row.pack(fill="x")
            new_var = ctk.StringVar()
            ctk.CTkEntry(add_row, textvariable=new_var, height=38, width=320, font=FONT_BODY,
                          fg_color=SURFACE, border_color=CARD_BORDER, corner_radius=8,
                          placeholder_text="Unit name e.g. Head Office…").pack(side="left", padx=(0, 12))
            def do_add():
                name = new_var.get().strip()
                if not name: messagebox.showerror("Required", "Unit name cannot be empty."); return
                try: add_unit(name); self.status_bar.set_message(f"✅ Unit '{name}' added!", SUCCESS); new_var.set(""); refresh()
                except Exception as e: messagebox.showerror("Error", f"Already exists or error:\n{e}")
            ctk.CTkButton(add_row, text="➕  Add Unit", font=FONT_BODY_BOLD, fg_color=SUCCESS,
                           hover_color="#16A34A", height=38, corner_radius=8, command=do_add).pack(side="left")

            if not units:
                ef = ctk.CTkFrame(content, fg_color=CARD_BG, corner_radius=14, border_width=1, border_color=CARD_BORDER)
                ef.pack(fill="x", pady=10)
                ctk.CTkLabel(ef, text="🏢", font=(FONT_FAMILY, 40)).pack(pady=(28, 6))
                ctk.CTkLabel(ef, text="No units yet", font=FONT_HEADING, text_color=TEXT_SECONDARY).pack()
                ctk.CTkLabel(ef, text="Add your first unit above.",
                             font=FONT_SMALL, text_color=TEXT_MUTED).pack(pady=(4, 28))
                return

            _section_label(content, f"Units  —  {len(units)} total")
            for b in units:
                count = counts.get(b, 0)
                card = ctk.CTkFrame(content, fg_color=CARD_BG, corner_radius=12,
                                    border_width=1, border_color=CARD_BORDER)
                card.pack(fill="x", pady=4)
                # Left accent
                inner_wrap = ctk.CTkFrame(card, fg_color="transparent")
                inner_wrap.pack(fill="x")
                accent_strip = ctk.CTkFrame(inner_wrap, width=4, corner_radius=0, fg_color=ACCENT)
                accent_strip.pack(side="left", fill="y")
                accent_strip.pack_propagate(False)
                ir = ctk.CTkFrame(inner_wrap, fg_color="transparent")
                ir.pack(side="left", fill="x", expand=True, padx=14, pady=12)
                # Unit name + pill count
                left = ctk.CTkFrame(ir, fg_color="transparent")
                left.pack(side="left", fill="y")
                ctk.CTkLabel(left, text=f"📍  {b}", font=FONT_BODY_BOLD, text_color=TEXT_PRIMARY).pack(anchor="w")
                clr = SUCCESS if count > 0 else TEXT_MUTED
                ctk.CTkLabel(left, text=f"{count} worker{'s' if count != 1 else ''}",
                              font=FONT_TINY, text_color=clr).pack(anchor="w", pady=(2, 0))
                # Buttons
                def mk_rename(bn=b):
                    def do():
                        d = ctk.CTkInputDialog(text=f"Rename '{bn}' to:", title="Rename Unit")
                        nn = d.get_input()
                        if nn and nn.strip():
                            try: rename_unit(bn, nn.strip()); self.status_bar.set_message(f"✅ Renamed → {nn.strip()}", SUCCESS); refresh()
                            except Exception as e: messagebox.showerror("Error", str(e))
                    return do
                ctk.CTkButton(ir, text="✏️  Rename", font=FONT_SMALL, fg_color=ACCENT,
                               hover_color=ACCENT_HOVER, height=30, corner_radius=6, width=90,
                               command=mk_rename()).pack(side="right", padx=(6, 0))
                def mk_del(bn=b, wc=count):
                    def do():
                        extra = f"\n\n⚠️ {wc} worker(s) will become unassigned." if wc > 0 else ""
                        if messagebox.askyesno("Delete Unit", f"Delete '{bn}'?{extra}",
                                                icon="warning" if wc > 0 else "question"):
                            delete_unit(bn); self.status_bar.set_message(f"🗑️ '{bn}' deleted.", DANGER); refresh()
                    return do
                ctk.CTkButton(ir, text="🗑️", font=FONT_SMALL, fg_color=DANGER,
                               hover_color="#B91C1C", height=30, corner_radius=6, width=40,
                               command=mk_del()).pack(side="right")
        refresh()

    # ══════════════════════════════════════════════════════════════════════
    #   WAGE RATES  (per skill category)
    # ══════════════════════════════════════════════════════════════════════
    def _page_wages(self, parent):
        _page_header(parent, "💰  Wage Rates by Skill",
                     "Set daily wage and overtime rate per skill level — applies to all workers in that category")
        content = ctk.CTkFrame(parent, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=28, pady=(0, 20))
        wages = get_skill_wages_dict()
        entries = {}
        SKILL_COLORS = {"Skilled": ("#22C55E", "#052E16"), "Semi-Skilled": ("#F59E0B", "#2D1B00"), "Unskilled": ("#3B82F6", "#0A1628")}
        SKILL_ICONS  = {"Skilled": "👤★", "Semi-Skilled": "👤◐", "Unskilled": "👤"}

        for cat in SKILL_CATEGORIES:
            sw = wages.get(cat, SkillWage(cat, 0, 0))
            accent_clr, bg_clr = SKILL_COLORS.get(cat, (ACCENT, SURFACE_3))
            card = ctk.CTkFrame(content, fg_color=CARD_BG, corner_radius=14,
                                 border_width=1, border_color=CARD_BORDER)
            card.pack(fill="x", pady=7)
            ctk.CTkFrame(card, height=3, corner_radius=0, fg_color=accent_clr).pack(fill="x")
            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="x", padx=22, pady=18)
            # Badge
            badge = ctk.CTkFrame(inner, fg_color=bg_clr, corner_radius=8,
                                  width=46, height=46, border_width=1, border_color=accent_clr)
            badge.pack(side="left", padx=(0, 16)); badge.pack_propagate(False)
            ctk.CTkLabel(badge, text=SKILL_ICONS.get(cat, ""), font=(FONT_FAMILY, 18)).pack(expand=True)
            # Label
            lbl_col = ctk.CTkFrame(inner, fg_color="transparent", width=130)
            lbl_col.pack(side="left"); lbl_col.pack_propagate(False)
            ctk.CTkLabel(lbl_col, text=cat, font=FONT_HEADING,
                          text_color=accent_clr, anchor="w").pack(anchor="w")
            ctk.CTkLabel(lbl_col, text="Skill Category", font=FONT_TINY,
                          text_color=TEXT_MUTED, anchor="w").pack(anchor="w")
            # Divider
            ctk.CTkFrame(inner, width=1, fg_color=CARD_BORDER).pack(side="left", fill="y", padx=20)
            # Daily Wage input
            dw_col = ctk.CTkFrame(inner, fg_color="transparent")
            dw_col.pack(side="left", padx=(0, 20))
            ctk.CTkLabel(dw_col, text="Daily Wage (₹)", font=FONT_TINY, text_color=TEXT_SECONDARY).pack(anchor="w")
            dw_var = ctk.StringVar(value=str(sw.daily_wage))
            ctk.CTkEntry(dw_col, textvariable=dw_var, width=110, height=36, font=FONT_BODY_BOLD,
                          fg_color=SURFACE, border_color=accent_clr, corner_radius=8).pack(anchor="w", pady=(4, 0))
            # OT Rate input
            ot_col = ctk.CTkFrame(inner, fg_color="transparent")
            ot_col.pack(side="left")
            ctk.CTkLabel(ot_col, text="OT Rate (₹/hr)", font=FONT_TINY, text_color=TEXT_SECONDARY).pack(anchor="w")
            ot_var = ctk.StringVar(value=str(sw.ot_rate))
            ctk.CTkEntry(ot_col, textvariable=ot_var, width=110, height=36, font=FONT_BODY_BOLD,
                          fg_color=SURFACE, border_color=accent_clr, corner_radius=8).pack(anchor="w", pady=(4, 0))
            entries[cat] = {"dw": dw_var, "ot": ot_var}

        note = ctk.CTkFrame(content, fg_color="#0A1628", corner_radius=10,
                             border_width=1, border_color="#1E3A5F")
        note.pack(fill="x", pady=(14, 6))
        ctk.CTkLabel(note, text="ℹ️  Designation labels (Sweeper, Janitor…) do NOT affect pay — only Skill Category does.",
                      font=FONT_SMALL, text_color="#60A5FA", justify="left"
                      ).pack(padx=14, pady=12, anchor="w")

        def save_wages():
            for cat, e in entries.items():
                try:
                    dw = float(e["dw"].get() or 0)
                    ot = float(e["ot"].get() or 0)
                except ValueError:
                    messagebox.showerror("Error", f"Invalid number for {cat}."); return
                upsert_skill_wage(SkillWage(cat, dw, ot))
            self.status_bar.set_message("✅ Wage rates saved!", SUCCESS)
            messagebox.showinfo("Saved", "Wage rates for all skill categories saved!")

        ctk.CTkButton(content, text="💾  Save All Wage Rates", font=FONT_BODY_BOLD,
                       fg_color=SUCCESS, hover_color="#16A34A", height=46,
                       corner_radius=10, command=save_wages).pack(fill="x", pady=(16, 16))

    # ══════════════════════════════════════════════════════════════════════
    #   GENERATE SLIPS
    # ══════════════════════════════════════════════════════════════════════
    def _page_slips(self, parent):
        _page_header(parent, "📄  Generate Salary Slips",
                     "Generate PDF salary slips — per unit or for all workers")
        ctrl = ctk.CTkFrame(parent, fg_color=SURFACE_3, corner_radius=10)
        ctrl.pack(fill="x", padx=28, pady=(4, 14))
        inner_ctrl = ctk.CTkFrame(ctrl, fg_color="transparent")
        inner_ctrl.pack(fill="x", padx=16, pady=10)
        opts = month_options()
        ctk.CTkLabel(inner_ctrl, text="Month:", font=FONT_BODY_BOLD, text_color=TEXT_PRIMARY).pack(side="left")
        month_var = ctk.StringVar(value=opts[-1])
        ctk.CTkOptionMenu(inner_ctrl, values=opts, variable=month_var, width=140, font=FONT_BODY,
                           fg_color=SURFACE, button_color=ACCENT,
                           button_hover_color=ACCENT_HOVER).pack(side="left", padx=(8, 20))
        ctk.CTkLabel(inner_ctrl, text="Unit:", font=FONT_BODY_BOLD, text_color=TEXT_PRIMARY).pack(side="left")
        unit_var = ctk.StringVar(value="All")
        ctk.CTkOptionMenu(inner_ctrl, values=_unit_filter_list(), variable=unit_var, width=150,
                           font=FONT_BODY, fg_color=SURFACE, button_color=ACCENT,
                           button_hover_color=ACCENT_HOVER).pack(side="left", padx=(8, 0))
        ctk.CTkButton(inner_ctrl, text="🔄 Refresh", font=FONT_BODY, width=100, fg_color=SURFACE,
                       hover_color=SURFACE_2, text_color=TEXT_PRIMARY, height=32,
                       corner_radius=8, command=lambda: refresh()).pack(side="right")
        content = ctk.CTkFrame(parent, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=28, pady=(0, 20))
        _slips_loading = [None]

        def refresh():
            for w in content.winfo_children(): w.destroy()
            _slips_loading[0] = _show_loading(content, "Calculating payroll…")
            month = month_var.get()
            unit  = unit_var.get()

            def _fetch():
                workers, att_dict = get_workers_and_attendance(month)
                sw = get_skill_wages_dict()
                return workers, sw, list(att_dict.values()), month, unit

            def _render(data):
                workers, sw, att, month, unit = data
                try:
                    if not content.winfo_exists():
                        return
                except Exception:
                    return
                if _slips_loading[0]:
                    try: _slips_loading[0].destroy()
                    except Exception: pass
                    _slips_loading[0] = None
                for w in content.winfo_children(): w.destroy()
                if unit != "All":
                    workers = [w for w in workers if w.unit == unit]
                results, warnings = calculate_payroll(workers, sw, att, month)
                if warnings:
                    wf = ctk.CTkFrame(content, fg_color="#3D2F00", corner_radius=8); wf.pack(fill="x", pady=(0, 8))
                    ctk.CTkLabel(wf, text=f"  ⚠️  {len(warnings)} warning(s)",
                                 font=FONT_SMALL, text_color=WARNING_CLR).pack(padx=12, pady=6)
                if not results:
                    ef = ctk.CTkFrame(content, fg_color=CARD_BG, corner_radius=12)
                    ef.pack(fill="x", pady=30, padx=40)
                    ctk.CTkLabel(ef, text="📭", font=(FONT_FAMILY, 36)).pack(pady=(20, 4))
                    ctk.CTkLabel(ef, text="No payroll data. Add attendance first.",
                                 font=FONT_HEADING, text_color=TEXT_SECONDARY).pack(pady=(0, 20))
                    return
                _section_label(content, f"📊  Ready: {len(results)} slip(s) for {month}")
                cols = ("ID","Name","Unit","Skill","Designation","Net Pay (₹)")
                table = StyledTreeview(content, columns=cols, column_widths=[70,150,100,80,130,120],
                                        height=min(len(results), 10))
                table.pack(fill="both", expand=True, pady=(0, 10))
                table.insert_rows([(r.worker_id, r.worker_name, r.unit, r.skill_category,
                                    r.profile_title, fmt_inr(r.net_pay)) for r in results])

                def gen_all():
                    zip_path = filedialog.asksaveasfilename(
                        title="Save Salary Slips ZIP", defaultextension=".zip",
                        filetypes=[("ZIP Archive", "*.zip")],
                        initialfile=f"SalarySlips_{month}.zip")
                    if not zip_path: return
                    self.status_bar.set_message("⏳ Generating ZIP...", ACCENT); self.update()
                    def do():
                        cfg = get_config()
                        temp_dir = tempfile.mkdtemp(prefix="payroll_slips_")
                        try:
                            gen = generate_bulk_pdfs(results, cfg, temp_dir, zip_output=True, zip_only=True)
                            if gen.get("zip_path") and os.path.exists(gen["zip_path"]):
                                import shutil; shutil.move(gen["zip_path"], zip_path)
                        finally:
                            try:
                                import shutil; shutil.rmtree(temp_dir, ignore_errors=True)
                            except: pass
                        self.after(0, lambda: done(gen, zip_path))
                    def done(gen, zp):
                        self.status_bar.set_message(f"✅ {gen['success_count']} slips → {zp}", SUCCESS)
                        messagebox.showinfo("Done", f"{gen['success_count']} salary slips saved as ZIP.\n\n{zp}")
                        try: os.startfile(os.path.dirname(zp))
                        except: pass
                    threading.Thread(target=do, daemon=True).start()

                ctk.CTkButton(content, text="📦  Download All Slips as ZIP", font=FONT_BODY_BOLD,
                               fg_color=ACCENT, hover_color=ACCENT_HOVER, height=46,
                               corner_radius=10, command=gen_all).pack(fill="x", pady=(10, 10))
                single = ctk.CTkFrame(content, fg_color=CARD_BG, corner_radius=12,
                                       border_width=1, border_color=CARD_BORDER)
                single.pack(fill="x", pady=(6, 4))
                ctk.CTkFrame(single, height=3, corner_radius=0, fg_color=SUCCESS).pack(fill="x")
                ctk.CTkLabel(single, text="📄  Generate Single Slip", font=FONT_SUBHEADING,
                              text_color=TEXT_PRIMARY).pack(padx=16, pady=(12, 6), anchor="w")
                sc = ctk.CTkFrame(single, fg_color="transparent"); sc.pack(fill="x", padx=12, pady=(0, 12))
                nl = [f"{r.worker_id} — {r.worker_name} [{r.unit}]" for r in results]
                sel_w = ctk.StringVar(value=nl[0] if nl else "")
                ctk.CTkOptionMenu(sc, values=nl, variable=sel_w, width=280, font=FONT_BODY,
                                   fg_color=SURFACE, button_color=ACCENT,
                                   button_hover_color=ACCENT_HOVER).pack(side="left", padx=(0, 12))
                def gen_single():
                    wid = sel_w.get().split(" — ")[0].strip()
                    r = next((r for r in results if r.worker_id == wid), None)
                    if not r: return
                    od = filedialog.askdirectory(title="Output folder")
                    if not od: return
                    path = generate_slip_pdf(r, get_config(), od)
                    self.status_bar.set_message(f"✅ Slip → {path}", SUCCESS)
                    messagebox.showinfo("Done", f"Slip saved:\n{path}")
                    try: os.startfile(path)
                    except: pass
                ctk.CTkButton(sc, text="👁️  Generate & Open", font=FONT_BODY_BOLD, fg_color=SUCCESS,
                               hover_color="#2E7D32", height=36, corner_radius=8,
                               command=gen_single).pack(side="left")

            _async_load(_fetch, _render)

        month_var.trace_add("write", lambda *_: refresh())
        unit_var.trace_add("write", lambda *_: refresh())
        refresh()

    # ══════════════════════════════════════════════════════════════════════
    #   SETTINGS
    # ══════════════════════════════════════════════════════════════════════
    def _page_settings(self, parent):
        _page_header(parent, "⚙️  Company Settings",
                     "Company information, working days, and system configuration")
        cfg = get_config()
        # ── Company Info Card ──
        form = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=14,
                             border_width=1, border_color=CARD_BORDER)
        form.pack(fill="x", padx=28, pady=(0, 16))
        ctk.CTkFrame(form, height=3, corner_radius=0, fg_color=ACCENT).pack(fill="x")
        ctk.CTkLabel(form, text="🏢  Company Information", font=FONT_HEADING,
                      text_color=TEXT_PRIMARY).pack(padx=20, pady=(16, 10), anchor="w")
        ff = ctk.CTkFrame(form, fg_color="transparent"); ff.pack(fill="x", padx=20, pady=(0, 14))
        ff.grid_columnconfigure((0, 1), weight=1)
        def sf(p, lbl, default="", r=0, c=0, colspan=1):
            f = ctk.CTkFrame(p, fg_color="transparent")
            f.grid(row=r, column=c, columnspan=colspan, padx=8, pady=5, sticky="ew")
            ctk.CTkLabel(f, text=lbl, font=FONT_SMALL, text_color=TEXT_SECONDARY).pack(anchor="w")
            v = ctk.StringVar(value=default)
            ctk.CTkEntry(f, textvariable=v, height=34, font=FONT_BODY, fg_color=SURFACE,
                          border_color=CARD_BORDER, corner_radius=8).pack(fill="x", pady=(2, 0))
            return v
        cn = sf(ff, "Company Name",        cfg.company_name,   r=0, c=0, colspan=2)
        a1 = sf(ff, "Address Line 1",      cfg.address_line1,  r=1, c=0)
        a2 = sf(ff, "Address Line 2",      cfg.address_line2,  r=1, c=1)
        ph = sf(ff, "Phone",               cfg.phone,          r=2, c=0)
        em = sf(ff, "Email",               cfg.email,          r=2, c=1)
        # Working days row
        wdf = ctk.CTkFrame(ff, fg_color="transparent")
        wdf.grid(row=3, column=0, padx=8, pady=5, sticky="ew")
        ctk.CTkLabel(wdf, text="Working Days / Month", font=FONT_SMALL, text_color=TEXT_SECONDARY).pack(anchor="w")
        wd = ctk.StringVar(value=str(cfg.working_days))
        ctk.CTkEntry(wdf, textvariable=wd, height=34, width=80, font=FONT_BODY, fg_color=SURFACE,
                      border_color=CARD_BORDER, corner_radius=8).pack(anchor="w", pady=(2, 0))
        def save_cfg():
            try: w = int(wd.get())
            except ValueError: messagebox.showerror("Error", "Working days must be a number."); return
            save_config(CompanyConfig(cn.get(), a1.get(), a2.get(), ph.get(), em.get(), w))
            self.status_bar.set_message("✅ Settings saved!", SUCCESS)
            messagebox.showinfo("Saved", "Company settings saved!")
        ctk.CTkButton(form, text="💾  Save Settings", font=FONT_BODY_BOLD, fg_color=SUCCESS,
                       hover_color="#16A34A", height=44, corner_radius=8, command=save_cfg).pack(pady=(4, 18))

        # ── System Info Card ──
        db = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=14,
                           border_width=1, border_color=CARD_BORDER)
        db.pack(fill="x", padx=28, pady=(0, 16))
        ctk.CTkFrame(db, height=3, corner_radius=0, fg_color=TEXT_MUTED).pack(fill="x")
        ctk.CTkLabel(db, text="🖥️  System Information", font=FONT_HEADING,
                      text_color=TEXT_PRIMARY).pack(padx=20, pady=(14, 6), anchor="w")
        db_inner = ctk.CTkFrame(db, fg_color="transparent")
        db_inner.pack(fill="x", padx=20, pady=(0, 16))
        db_inner.grid_columnconfigure((0, 1), weight=1)
        for i, (label, val) in enumerate([
            ("Database", os.path.abspath(DB_PATH)),
            ("Units", str(len(get_all_units()))),
            ("Workers (incl. inactive)", str(len(get_all_workers(active_only=False)))),
            ("App Version", "PayrollPro v2.1"),
        ]):
            r, c = divmod(i, 2)
            f = ctk.CTkFrame(db_inner, fg_color=SURFACE_3, corner_radius=8)
            f.grid(row=r, column=c, padx=6, pady=4, sticky="ew")
            ctk.CTkLabel(f, text=label, font=FONT_TINY, text_color=TEXT_MUTED).pack(anchor="w", padx=10, pady=(6, 0))
            ctk.CTkLabel(f, text=val, font=(FONT_FAMILY, 10, "bold"), text_color=TEXT_PRIMARY).pack(anchor="w", padx=10, pady=(0, 8))

        # ── Bank Presets Card ─────────────────────────────────────────────
        bk_card = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=14,
                                border_width=1, border_color=CARD_BORDER)
        bk_card.pack(fill="x", padx=28, pady=(0, 16))
        ctk.CTkFrame(bk_card, height=3, corner_radius=0, fg_color="#26A69A").pack(fill="x")

        bk_hdr = ctk.CTkFrame(bk_card, fg_color="transparent")
        bk_hdr.pack(fill="x", padx=20, pady=(14, 6))
        ctk.CTkLabel(bk_hdr, text="🏦  Bank Presets", font=FONT_HEADING,
                      text_color=TEXT_PRIMARY).pack(side="left")
        ctk.CTkLabel(bk_hdr, text="Preset banks appear as a dropdown in the Worker form",
                      font=FONT_TINY, text_color=TEXT_MUTED).pack(side="left", padx=(12, 0))

        bk_body = ctk.CTkFrame(bk_card, fg_color="transparent")
        bk_body.pack(fill="x", padx=20, pady=(0, 14))

        def _refresh_banks():
            for w in bk_body.winfo_children(): w.destroy()
            banks = get_all_banks()   # now List[str]

            # ── Add new bank ──
            add_row = ctk.CTkFrame(bk_body, fg_color=SURFACE_3, corner_radius=8)
            add_row.pack(fill="x", pady=(0, 10))
            add_inner = ctk.CTkFrame(add_row, fg_color="transparent")
            add_inner.pack(fill="x", padx=12, pady=10)
            nv = ctk.StringVar()
            ctk.CTkLabel(add_inner, text="Bank Name:", font=FONT_SMALL, text_color=TEXT_SECONDARY,
                          width=80, anchor="w").pack(side="left")
            ctk.CTkEntry(add_inner, textvariable=nv, font=FONT_BODY, fg_color=SURFACE,
                          border_color=TEXT_MUTED, height=30, width=280).pack(side="left", padx=(0, 10))
            def _add():
                n = nv.get().strip()
                if not n: messagebox.showerror("Required", "Bank name cannot be empty."); return
                try: add_bank(n); self.status_bar.set_message(f"✅ Bank '{n}' added!", SUCCESS); _refresh_banks()
                except Exception as e: messagebox.showerror("Error", f"Already exists:\n{e}")
            ctk.CTkButton(add_inner, text="➕ Add", font=FONT_BODY_BOLD, fg_color=SUCCESS,
                           hover_color="#16A34A", height=30, corner_radius=6, width=80,
                           command=_add).pack(side="left")

            if not banks:
                ctk.CTkLabel(bk_body, text="No bank presets yet — add one above.",
                              font=FONT_SMALL, text_color=TEXT_MUTED).pack(pady=8)
                return

            # ── Bank list ──
            list_frame = ctk.CTkFrame(bk_body, fg_color="transparent")
            list_frame.pack(fill="x")
            hdr = ctk.CTkFrame(list_frame, fg_color=ACCENT_DARK, corner_radius=6)
            hdr.pack(fill="x", pady=(0, 2))
            ctk.CTkLabel(hdr, text="Bank Name", font=(FONT_FAMILY, 10, "bold"),
                          text_color="white", anchor="w").pack(side="left", padx=12, pady=6, fill="x",
                          expand=True)
            ctk.CTkLabel(hdr, text="Actions", font=(FONT_FAMILY, 10, "bold"),
                          text_color="white", width=90, anchor="w").pack(side="left", padx=8, pady=6)

            for idx, bname in enumerate(banks):
                bg = SURFACE_2 if idx % 2 == 0 else SURFACE_3
                brow = ctk.CTkFrame(list_frame, fg_color=bg, corner_radius=4)
                brow.pack(fill="x", pady=1)
                binner = ctk.CTkFrame(brow, fg_color="transparent")
                binner.pack(fill="x", padx=8, pady=4)

                ev_name = ctk.StringVar(value=bname)
                ctk.CTkEntry(binner, textvariable=ev_name, font=FONT_SMALL,
                              fg_color=SURFACE, border_color=TEXT_MUTED,
                              height=28, corner_radius=4).pack(side="left", fill="x",
                              expand=True, padx=(0, 8))

                def _mk_save(old=bname, nvar=ev_name):
                    def _save():
                        nn = nvar.get().strip()
                        if not nn: messagebox.showerror("Required", "Name cannot be empty."); return
                        try: update_bank(old, nn); self.status_bar.set_message(f"✅ Bank renamed!", SUCCESS); _refresh_banks()
                        except Exception as e: messagebox.showerror("Error", str(e))
                    return _save

                def _mk_del(name=bname):
                    def _del():
                        if messagebox.askyesno("Delete Bank", f"Remove '{name}' from presets?"):
                            delete_bank(name); self.status_bar.set_message(f"🗑️ '{name}' removed.", DANGER); _refresh_banks()
                    return _del

                ctk.CTkButton(binner, text="💾 Save", font=FONT_SMALL, width=68, height=28,
                               fg_color=ACCENT, hover_color=ACCENT_HOVER, corner_radius=4,
                               command=_mk_save()).pack(side="left", padx=(0, 4))
                ctk.CTkButton(binner, text="🗑️", font=FONT_SMALL, width=34, height=28,
                               fg_color=DANGER, hover_color="#B91C1C", corner_radius=4,
                               command=_mk_del()).pack(side="left")

        _refresh_banks()

        # ── Backup Status Card ────────────────────────────────────────────
        mgr = self._backup_mgr
        bk = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=12)
        bk.pack(fill="x", padx=28, pady=(0, 20))
        # Header row
        bk_hdr = ctk.CTkFrame(bk, fg_color="transparent"); bk_hdr.pack(fill="x", padx=20, pady=(16, 4))
        ctk.CTkLabel(bk_hdr, text="🔄  Real-Time Backup", font=FONT_HEADING,
                      text_color=TEXT_PRIMARY).pack(side="left")
        # Status badge
        bk_badge_var = ctk.StringVar(value=mgr.last_sync_status)
        bk_badge = ctk.CTkLabel(bk_hdr, textvariable=bk_badge_var, font=FONT_SMALL,
                                  text_color=SUCCESS if "✅" in mgr.last_sync_status else TEXT_MUTED)
        bk_badge.pack(side="right")
        # Info rows
        def _bk_row(lbl, val, clickable_path=None):
            r = ctk.CTkFrame(bk, fg_color="transparent"); r.pack(fill="x", padx=20, pady=2)
            ctk.CTkLabel(r, text=lbl, font=FONT_SMALL, text_color=TEXT_SECONDARY,
                          width=160, anchor="w").pack(side="left")
            if clickable_path:
                def _open(p=clickable_path):
                    try: os.startfile(os.path.dirname(p))
                    except Exception: pass
                ctk.CTkButton(r, text=val, font=FONT_TINY, fg_color="transparent",
                               hover_color=SURFACE_3, text_color=ACCENT, anchor="w",
                               height=20, command=_open).pack(side="left", fill="x", expand=True)
            else:
                ctk.CTkLabel(r, text=val, font=FONT_TINY, text_color=TEXT_MUTED,
                              anchor="w").pack(side="left", fill="x", expand=True)
        _bk_row("Worker Details CSV:",  mgr.csv_path_str,       clickable_path=mgr.csv_path_str)
        _bk_row("Backup Database:",     mgr.backup_db_path_str, clickable_path=mgr.backup_db_path_str)
        # Last synced + Sync Now
        ts_var = ctk.StringVar(value=f"Last synced: {mgr.last_sync_time}")
        sync_row = ctk.CTkFrame(bk, fg_color="transparent"); sync_row.pack(fill="x", padx=20, pady=(8, 14))
        ctk.CTkLabel(sync_row, textvariable=ts_var, font=FONT_SMALL,
                      text_color=TEXT_MUTED, anchor="w").pack(side="left")
        def _do_sync_now():
            self.status_bar.set_message("🔄 Syncing backups…", ACCENT)
            mgr.sync_now()
            def _refresh():
                ts_var.set(f"Last synced: {mgr.last_sync_time}")
                bk_badge_var.set(mgr.last_sync_status)
                bk_badge.configure(
                    text_color=SUCCESS if "✅" in mgr.last_sync_status else DANGER)
                self.status_bar.set_message("✅ Backup sync complete!", SUCCESS)
            self.after(2500, _refresh)
        ctk.CTkButton(sync_row, text="🔄  Sync Now", font=FONT_BODY_BOLD,
                       fg_color=ACCENT, hover_color=ACCENT_HOVER, height=32,
                       corner_radius=8, command=_do_sync_now).pack(side="right")
        ctk.CTkFrame(bk, height=1, fg_color=SURFACE_3).pack(fill="x", padx=20)
        ctk.CTkLabel(bk,
                      text="  ℹ️  Backups update automatically within 2 seconds of any change to payroll.db",
                      font=FONT_TINY, text_color=TEXT_MUTED, anchor="w"
                      ).pack(padx=20, pady=(6, 14), anchor="w")


if __name__ == "__main__":
    app = PayrollApp()
    app.mainloop()
