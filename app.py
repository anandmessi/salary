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
        for item in self.tree.get_children(): self.tree.delete(item)
    def insert_rows(self, rows):
        self.clear()
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


# ══════════════════════════════════════════════════════════════════════════════
class PayrollApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("PayrollPro — Professional Payroll Management")
        self.geometry("1300x800"); self.minsize(1050, 650)
        init_db(DB_PATH, seed=True)
        self.grid_columnconfigure(1, weight=1); self.grid_rowconfigure(0, weight=1)
        self._build_sidebar(); self._build_main_area(); self._build_status_bar()
        # ── Start real-time backup manager ─────────────────────────────────
        self._backup_mgr = BackupManager(
            db_path=DB_PATH,
            on_sync=self._on_backup_sync,
        )
        self._backup_mgr.start()
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

        def refresh():
            for w in content.winfo_children(): w.destroy()
            workers = get_all_workers()
            sw = get_skill_wages_dict()
            att = get_attendance(month_var.get())
            if unit_var.get() != "All":
                workers = [w for w in workers if w.unit == unit_var.get()]
            results, warnings = calculate_payroll(workers, sw, att, month_var.get())
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
                    filetypes=[("CSV","*.csv")], initialfile=f"Payroll_{month_var.get()}.csv")
                if path:
                    data = []
                    for r in results:
                        data.append({
                            "Emp name": r.worker_name,
                            "Total Sal": round(r.net_pay, 2),
                            "IFSC Code": r.ifsc_code,
                            "Account Number": r.bank_account
                        })
                    pd.DataFrame(data).to_csv(path, index=False)
                    self.status_bar.set_message(f"✅ CSV → {path}", SUCCESS)
                    messagebox.showinfo("Export", f"CSV saved:\n{path}")
            ctk.CTkButton(content, text="⬇️  Export CSV", font=FONT_BODY_BOLD,
                           fg_color=ACCENT, hover_color=ACCENT_HOVER, height=36,
                           corner_radius=8, command=export_csv).pack(anchor="w", pady=(0, 16))

        month_var.trace_add("write", lambda *_: refresh())
        unit_var.trace_add("write", lambda *_: refresh())
        refresh()

    # ══════════════════════════════════════════════════════════════════════
    #   ATTENDANCE
    # ══════════════════════════════════════════════════════════════════════
    def _page_attendance(self, parent):
        _page_header(parent, "📋  Attendance & Earnings Entry",
                     "Enter daily attendance and manage per-worker allowances / deductions")
        tabview = ctk.CTkTabview(parent, fg_color=SURFACE_2, segmented_button_fg_color=SURFACE_3,
                                  segmented_button_selected_color=ACCENT,
                                  segmented_button_selected_hover_color=ACCENT_HOVER,
                                  segmented_button_unselected_color=SURFACE_3,
                                  segmented_button_unselected_hover_color=SIDEBAR_HOVER, corner_radius=10)
        tabview.pack(fill="both", expand=True, padx=28, pady=(0, 20))
        tab_manual = tabview.add("✏️  Manual Entry"); tab_csv = tabview.add("📥  CSV Import")
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

        def save_all():
            records = []
            existing_db = {a.worker_id: a for a in get_attendance(month_var.get())}
            for wid, entry in self._att_entries.items():
                att = entry.get("detail_att", existing_db.get(wid, AttendanceRecord(wid, month_var.get())))
                try:
                    att.days_present = float(entry["days"].get() or 0)
                    att.overtime_hours = float(entry["ot"].get() or 0)
                except ValueError: pass
                att.month = month_var.get(); records.append(att)
            bulk_upsert_attendance(records)
            self.status_bar.set_message(f"✅ Saved {len(records)} records for {month_var.get()}", SUCCESS)
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
                rate = f"₹{sw.daily_wage}" if sw else "—"
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
                
                details = ctk.CTkFrame(worker_container, fg_color="transparent")
                shown = [False]
                toggle_btn = ctk.CTkButton(row, text="▼", font=FONT_SMALL, width=30, height=24,
                    corner_radius=4, fg_color=SURFACE_3, hover_color=SURFACE_2, text_color=TEXT_SECONDARY)
                toggle_btn.pack(side="left", padx=6)

                def make_toggle(d=details, tb=toggle_btn, sh=shown):
                    def toggle():
                        if sh[0]: d.pack_forget(); tb.configure(text="▼"); sh[0] = False
                        else: d.pack(fill="x", padx=10, pady=(6, 10)); tb.configure(text="▲"); sh[0] = True
                    tb.configure(command=toggle)
                make_toggle()
                
                self._build_detail_fields(details, w.worker_id, att)
                self._att_entries[w.worker_id] = {"days": days_var, "ot": ot_var, "existing": att}

        # Save button lives OUTSIDE the scrollable table_frame — always visible
        ctk.CTkButton(parent, text="💾  Save All Attendance", font=FONT_BODY_BOLD,
                       fg_color=SUCCESS, hover_color="#2E7D32", height=40,
                       corner_radius=8, command=save_all).pack(fill="x", padx=12, pady=(4, 12))

        month_var.trace_add("write", lambda *_: refresh())
        unit_var.trace_add("write", lambda *_: refresh())
        search_var_att.trace_add("write", lambda *_: refresh())
        refresh()

    def _build_detail_fields(self, parent, worker_id, att):
        fields = [
            ("DA (₹)","da"),("HRA (₹)","hra"),("CCA (₹)","cca"),
            ("Arrears (₹)","arrears"),("N&FH Wages (₹)","nfh_wages"),
            ("Leave Wages (₹)","leave_wages"),("Bonus (₹)","bonus"),
            ("Maternity (₹)","maternity_benefit"),("Advance Pay (₹)","advances_pay"),
            ("Other Allow. (₹)","other_allowances"),
            ("EPF Override (0=auto)","epf_override"),("ESI Override (0=auto)","esi_override"),
            ("Welfare Fund (₹)","welfare_fund"),("TDS (₹)","tds"),
            ("Prof. Tax (₹)","profession_tax"),("Adv. Repayment (₹)","advance_repayment"),
            ("Fine (₹)","fine"),("Loss/Damages (₹)","loss_damages"),
            ("Other Ded. (₹)","other_deductions"),
        ]
        vars_dict = {}
        for i, (label, attr) in enumerate(fields):
            if i % 3 == 0:
                row_frame = ctk.CTkFrame(parent, fg_color="transparent"); row_frame.pack(fill="x", pady=2)
            f = ctk.CTkFrame(row_frame, fg_color="transparent"); f.pack(side="left", expand=True, fill="x", padx=4)
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
            return AttendanceRecord(**kwargs)
        def update(*_):
            if worker_id in self._att_entries:
                self._att_entries[worker_id]["detail_att"] = build_record()
        for _, attr in fields: vars_dict[attr].trace_add("write", update)
        update()

    def _build_att_csv(self, parent):
        ctk.CTkLabel(parent, text="Upload a CSV to import attendance data in bulk.",
                      font=FONT_BODY, text_color=TEXT_SECONDARY, anchor="w").pack(padx=16, pady=(16, 8))
        info = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=8); info.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(info, text="Supported columns:", font=FONT_BODY_BOLD,
                      text_color=TEXT_PRIMARY).pack(padx=12, pady=(10, 2), anchor="w")
        ctk.CTkLabel(info, text="worker_id, days_present, da, hra, cca, overtime_hours,\n"
                     "bonus, arrears, advance_repayment, epf_override, esi_override …",
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
                self.status_bar.set_message(f"✅ Template → {path}", SUCCESS)
        ctk.CTkButton(parent, text="⬇️  Download Template", font=FONT_BODY, fg_color=SURFACE_3,
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
            self.status_bar.set_message(f"✅ {msg}", SUCCESS)
            if res["errors"]: messagebox.showwarning("Import", msg+"\n\nErrors:\n"+"\n".join(res["errors"][:10]))
            else: messagebox.showinfo("Import", f"✅ {msg}")
        ctk.CTkButton(parent, text="📥  Import CSV", font=FONT_BODY_BOLD, fg_color=ACCENT,
                       hover_color=ACCENT_HOVER, height=38, corner_radius=8,
                       command=import_csv).pack(padx=16, anchor="w", pady=(12, 20))

    # ══════════════════════════════════════════════════════════════════════
    #   WORKERS
    # ══════════════════════════════════════════════════════════════════════
    def _page_workers(self, parent):
        _page_header(parent, "👷  Worker Master Data",
                     "Add, edit, or delete workers — bank, PF/ESIC, unit, skill & designation")
        tabview = ctk.CTkTabview(parent, fg_color=SURFACE_2, segmented_button_fg_color=SURFACE_3,
                                  segmented_button_selected_color=ACCENT,
                                  segmented_button_selected_hover_color=ACCENT_HOVER,
                                  segmented_button_unselected_color=SURFACE_3,
                                  segmented_button_unselected_hover_color=SIDEBAR_HOVER, corner_radius=10)
        tabview.pack(fill="both", expand=True, padx=28, pady=(0, 20))
        tab_all = tabview.add("👥 All Workers"); tab_add = tabview.add("➕ Add / Edit")
        form_vars = {}

        def _populate_form(wid_str):
            w = get_worker_by_id(wid_str)
            if not w: messagebox.showerror("Error", f"Worker '{wid_str}' not found."); return
            form_vars["wid"].set(w.worker_id); form_vars["name"].set(w.name)
            form_vars["designation"].set(w.designation); form_vars["unit"].set(w.unit)
            form_vars["skill"].set(w.skill_category); form_vars["join"].set(w.joining_date)
            form_vars["bank_acc"].set(w.bank_account); form_vars["bank_name"].set(w.bank_name)
            form_vars["ifsc"].set(w.ifsc_code); form_vars["uan"].set(w.uan_number)
            form_vars["esic"].set(w.esic_number)
            tabview.set("➕ Add / Edit")
            self.status_bar.set_message(f"Editing worker {w.worker_id} — {w.name}", ACCENT)

        def _clear_form():
            for k in ["wid","name","designation","bank_acc","bank_name","ifsc","uan","esic"]:
                form_vars[k].set("")
            form_vars["join"].set(datetime.date.today().strftime("%d/%m/%Y"))
            b = get_all_units()
            form_vars["unit"].set(b[0] if b else "")
            form_vars["skill"].set(SKILL_CATEGORIES[-1])
            self.status_bar.set_message("Form cleared — ready to add a new worker.")

        def refresh_workers():
            for w in tab_all.winfo_children(): w.destroy()
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
            ctk.CTkEntry(inner_fc, textvariable=search_var_wk, placeholder_text="Search by Name or ID…", width=180,
                          font=FONT_SMALL, fg_color=SURFACE, border_color=TEXT_MUTED,
                          corner_radius=8).pack(side="left", padx=(4, 0))
            table_container = ctk.CTkFrame(tab_all, fg_color="transparent")
            table_container.pack(fill="both", expand=True, padx=8)

            def update_table(*_):
                for w in table_container.winfo_children(): w.destroy()
                workers = get_all_workers(active_only=False)
                if filt_var.get() != "All":
                    workers = [w for w in workers if w.unit == filt_var.get()]
                q_wk = search_var_wk.get().strip().lower()
                if q_wk:
                    workers = [w for w in workers if q_wk in w.name.lower() or q_wk in w.worker_id.lower()]
                if not workers:
                    ef = ctk.CTkFrame(table_container, fg_color=CARD_BG, corner_radius=12)
                    ef.pack(fill="x", pady=30, padx=30)
                    ctk.CTkLabel(ef, text="👤", font=(FONT_FAMILY, 36)).pack(pady=(20, 4))
                    ctk.CTkLabel(ef, text="No workers yet", font=FONT_HEADING, text_color=TEXT_SECONDARY).pack()
                    ctk.CTkLabel(ef, text='Use "➕ Add / Edit" tab to add your first worker.',
                                 font=FONT_SMALL, text_color=TEXT_MUTED).pack(pady=(4, 20))
                    return
                cols = ("ID","Name","Unit","Skill","Designation","Bank","A/C","IFSC","UAN","ESIC","Status")
                widths = [55,120,80,70,90,90,100,90,80,70,45]
                table = StyledTreeview(table_container, columns=cols, column_widths=widths,
                                        height=min(len(workers), 12))
                table.pack(fill="both", expand=True, pady=(4, 4))
                table.insert_rows([(w.worker_id, w.name, w.unit, w.skill_category,
                                    w.designation, w.bank_name, w.bank_account, w.ifsc_code,
                                    w.uan_number, w.esic_number,
                                    "● Active" if w.active else "○ Inactive") for w in workers])
                # Apply color tags using row values only (no outer-loop 'w' reference)
                for item in table.tree.get_children():
                    vals = table.tree.item(item, "values")
                    skill  = str(vals[3])  if len(vals) >  3 else ""
                    status = str(vals[10]) if len(vals) > 10 else ""
                    if status.startswith("○"):
                        table.tree.item(item, tags=("inactive",))
                    elif skill == "Skilled":
                        table.tree.item(item, tags=("skilled",))
                    elif "Semi" in skill:
                        table.tree.item(item, tags=("semi",))

                # ── Action panel ──
                ap = ctk.CTkFrame(table_container, fg_color=CARD_BG, corner_radius=10)
                ap.pack(fill="x", pady=(8, 4))
                ap_inner = ctk.CTkFrame(ap, fg_color="transparent")
                ap_inner.pack(fill="x", padx=14, pady=10)
                # Show "ID — Name" in dropdown for easy identification
                all_labels = [f"{w.worker_id} — {w.name}" for w in workers]
                sel_var = ctk.StringVar(value=all_labels[0] if all_labels else "")

                def _get_selected_id():
                    """Extract worker_id from the 'ID — Name' dropdown value."""
                    val = sel_var.get()
                    return val.split(" — ")[0].strip() if " — " in val else val.strip()

                ctk.CTkLabel(ap_inner, text="Worker:", font=FONT_BODY_BOLD, text_color=TEXT_PRIMARY).pack(side="left")
                ctk.CTkOptionMenu(ap_inner, values=all_labels, variable=sel_var, width=230, font=FONT_BODY,
                                   fg_color=SURFACE_3, button_color=ACCENT,
                                   button_hover_color=ACCENT_HOVER).pack(side="left", padx=(8, 16))
                ctk.CTkButton(ap_inner, text="✏️  Edit", font=FONT_BODY_BOLD, fg_color=ACCENT,
                               hover_color=ACCENT_HOVER, height=34, corner_radius=8, width=90,
                               command=lambda: _populate_form(_get_selected_id())).pack(side="left", padx=(0, 6))
                def do_toggle():
                    wid = _get_selected_id()
                    w = get_worker_by_id(wid)
                    if not w: return
                    if w.active:
                        if messagebox.askyesno("Confirm", f"Deactivate '{w.name}' ({wid})?"):
                            deactivate_worker(wid)
                            self.status_bar.set_message(f"Worker {wid} deactivated.", WARNING_CLR); update_table()
                    else:
                        reactivate_worker(wid)
                        self.status_bar.set_message(f"Worker {wid} re-activated.", SUCCESS); update_table()
                ctk.CTkButton(ap_inner, text="⏸  Toggle", font=FONT_BODY_BOLD, fg_color=WARNING_CLR,
                               hover_color="#E65100", height=34, corner_radius=8, width=100,
                               command=do_toggle).pack(side="left", padx=(0, 6))
                def do_delete():
                    wid = _get_selected_id()
                    w = get_worker_by_id(wid)
                    wname = w.name if w else wid
                    if messagebox.askyesno("⚠️ Delete",
                        f"Permanently delete '{wname}' ({wid}) and ALL their attendance?\nCannot undo.", icon="warning"):
                        delete_worker(wid)
                        self.status_bar.set_message(f"Worker {wid} deleted.", DANGER); update_table()
                ctk.CTkButton(ap_inner, text="🗑️  Delete", font=FONT_BODY_BOLD, fg_color=DANGER,
                               hover_color="#C62828", height=34, corner_radius=8, width=90,
                               command=do_delete).pack(side="left")

                # Clicking a row in the table updates the dropdown
                def on_select(event):
                    sel = table.tree.selection()
                    if sel:
                        vals = table.tree.item(sel[0])["values"]
                        if vals:
                            wid = str(vals[0])
                            # Find matching label in dropdown
                            for lbl in all_labels:
                                if lbl.startswith(wid + " — "):
                                    sel_var.set(lbl); break
                table.tree.bind("<<TreeviewSelect>>", on_select)

                def on_dbl(event):
                    sel = table.tree.selection()
                    if sel:
                        vals = table.tree.item(sel[0])["values"]
                        if vals: _populate_form(str(vals[0]))
                table.tree.bind("<Double-1>", on_dbl)
            filt_var.trace_add("write", update_table)
            search_var_wk.trace_add("write", update_table)
            update_table()

        # ── Form ──
        form = ctk.CTkFrame(tab_add, fg_color=CARD_BG, corner_radius=10); form.pack(fill="x", padx=16, pady=16)
        fh = ctk.CTkFrame(form, fg_color="transparent"); fh.pack(fill="x", padx=16, pady=(16, 10))
        ctk.CTkLabel(fh, text="Worker Registration Form", font=FONT_HEADING,
                      text_color=TEXT_PRIMARY).pack(side="left")
        ctk.CTkButton(fh, text="🧹 Clear", font=FONT_SMALL, fg_color=SURFACE_3,
                       hover_color=SURFACE_2, text_color=TEXT_SECONDARY, height=28, width=80,
                       corner_radius=6, command=lambda: _clear_form()).pack(side="right")
        ff = ctk.CTkFrame(form, fg_color="transparent"); ff.pack(fill="x", padx=16, pady=(0, 10))
        ff.grid_columnconfigure((0,1,2), weight=1)

        def mkf(p, lbl, r, c, default=""):
            f = ctk.CTkFrame(p, fg_color="transparent"); f.grid(row=r, column=c, padx=8, pady=4, sticky="ew")
            ctk.CTkLabel(f, text=lbl, font=FONT_SMALL, text_color=TEXT_SECONDARY).pack(anchor="w")
            v = ctk.StringVar(value=default)
            ctk.CTkEntry(f, textvariable=v, height=30, font=FONT_BODY, fg_color=SURFACE,
                          border_color=TEXT_MUTED, corner_radius=6).pack(fill="x")
            return v

        wid_var = mkf(ff, "Worker ID *", 0, 0)
        wname_var = mkf(ff, "Full Name *", 0, 1)
        wdesig_var = mkf(ff, "Designation (e.g. Sweeper)", 0, 2)

        # Unit dropdown
        bf = ctk.CTkFrame(ff, fg_color="transparent"); bf.grid(row=1, column=0, padx=8, pady=4, sticky="ew")
        ctk.CTkLabel(bf, text="Unit *", font=FONT_SMALL, text_color=TEXT_SECONDARY).pack(anchor="w")
        units = _unit_list()
        unit_var = ctk.StringVar(value=units[0] if units else "")
        ctk.CTkOptionMenu(bf, values=units, variable=unit_var, font=FONT_BODY,
                           fg_color=SURFACE, button_color=ACCENT,
                           button_hover_color=ACCENT_HOVER, height=30).pack(fill="x")

        # Skill dropdown
        sf = ctk.CTkFrame(ff, fg_color="transparent"); sf.grid(row=1, column=1, padx=8, pady=4, sticky="ew")
        ctk.CTkLabel(sf, text="Skill Category *  (determines wage)", font=FONT_SMALL,
                      text_color=TEXT_SECONDARY).pack(anchor="w")
        skill_var = ctk.StringVar(value=SKILL_CATEGORIES[-1])
        ctk.CTkOptionMenu(sf, values=SKILL_CATEGORIES, variable=skill_var, font=FONT_BODY,
                           fg_color=SURFACE, button_color=ACCENT,
                           button_hover_color=ACCENT_HOVER, height=30).pack(fill="x")

        wjoin_var = mkf(ff, "Joining Date (DD/MM/YYYY)", 1, 2, datetime.date.today().strftime("%d/%m/%Y"))
        wbank_var = mkf(ff, "Bank Account Number", 2, 0)
        wbname_var = mkf(ff, "Bank Name", 2, 1)
        wifsc_var = mkf(ff, "IFSC Code", 2, 2)
        wuan_var = mkf(ff, "UAN / PF ID Number", 3, 0)
        wesic_var = mkf(ff, "ESIC IP Number", 3, 1)

        form_vars.update({"wid": wid_var, "name": wname_var, "designation": wdesig_var,
                          "unit": unit_var, "skill": skill_var, "join": wjoin_var,
                          "bank_acc": wbank_var, "bank_name": wbname_var, "ifsc": wifsc_var,
                          "uan": wuan_var, "esic": wesic_var})

        def save_worker():
            wid = wid_var.get().strip().upper(); wname = wname_var.get().strip()
            if not wid or not wname:
                messagebox.showerror("Required", "Worker ID and Name are required."); return
            b = unit_var.get()
            if not b or b == "(No units)":
                messagebox.showerror("Required", "Create a Unit first (🏢 Units)."); return
            upsert_worker(Worker(
                worker_id=wid, name=wname, designation=wdesig_var.get().strip(),
                bank_account=wbank_var.get().strip(), bank_name=wbname_var.get().strip(),
                ifsc_code=wifsc_var.get().strip(), uan_number=wuan_var.get().strip(),
                esic_number=wesic_var.get().strip(), joining_date=wjoin_var.get().strip(),
                active=True, unit=b, skill_category=skill_var.get()))
            self.status_bar.set_message(f"✅ Worker {wid} saved!", SUCCESS)
            messagebox.showinfo("Saved", f"Worker {wid} saved!")
            _clear_form(); refresh_workers()

        ctk.CTkButton(form, text="💾  Save Worker", font=FONT_BODY_BOLD, fg_color=SUCCESS,
                       hover_color="#2E7D32", height=40, corner_radius=8,
                       command=save_worker).pack(pady=(4, 16))
        refresh_workers()

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

        def refresh():
            for w in content.winfo_children(): w.destroy()
            workers = get_all_workers()
            if unit_var.get() != "All":
                workers = [w for w in workers if w.unit == unit_var.get()]
            sw = get_skill_wages_dict(); att = get_attendance(month_var.get())
            results, warnings = calculate_payroll(workers, sw, att, month_var.get())
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
            _section_label(content, f"📊  Ready: {len(results)} slip(s) for {month_var.get()}")
            cols = ("ID","Name","Unit","Skill","Designation","Net Pay (₹)")
            table = StyledTreeview(content, columns=cols, column_widths=[70,150,100,80,130,120],
                                    height=min(len(results), 10))
            table.pack(fill="both", expand=True, pady=(0, 10))
            table.insert_rows([(r.worker_id, r.worker_name, r.unit, r.skill_category,
                                r.profile_title, fmt_inr(r.net_pay)) for r in results])

            def gen_all():
                zip_path = filedialog.asksaveasfilename(
                    title="Save Salary Slips ZIP",
                    defaultextension=".zip",
                    filetypes=[("ZIP Archive", "*.zip")],
                    initialfile=f"SalarySlips_{month_var.get()}.zip"
                )
                if not zip_path: return
                self.status_bar.set_message("⏳ Generating ZIP...", ACCENT); self.update()
                def do():
                    cfg = get_config()
                    # Generate into a temp dir, zip_only keeps output clean
                    temp_dir = tempfile.mkdtemp(prefix="payroll_slips_")
                    try:
                        gen = generate_bulk_pdfs(results, cfg, temp_dir, zip_output=True, zip_only=True)
                        # Move the generated zip to the user-chosen path
                        if gen.get("zip_path") and os.path.exists(gen["zip_path"]):
                            import shutil
                            shutil.move(gen["zip_path"], zip_path)
                    finally:
                        # Clean up temp dir
                        try:
                            import shutil
                            shutil.rmtree(temp_dir, ignore_errors=True)
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
