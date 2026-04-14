"""
app.py — PayrollPro Desktop Application
========================================
Professional native desktop payroll software.
Run with:  python app.py
"""

import os, sys, csv, datetime, threading, tempfile
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
    get_workers_by_branch, import_attendance_from_csv,
    get_all_branches, add_branch, rename_branch, delete_branch,
    branch_worker_count,
    DB_PATH,
)
from payroll_engine import calculate_payroll, payroll_summary
from pdf_generator import generate_bulk_pdfs, generate_slip_pdf
from schema import SkillWage

# ── Theme ─────────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

ACCENT          = "#1E88E5"
ACCENT_HOVER    = "#1565C0"
ACCENT_DARK     = "#0D47A1"
SUCCESS         = "#43A047"
DANGER          = "#E53935"
WARNING_CLR     = "#FB8C00"
SURFACE         = "#1E1E2E"
SURFACE_2       = "#252536"
SURFACE_3       = "#2A2A3C"
CARD_BG         = "#2D2D44"
TEXT_PRIMARY     = "#E8E8F0"
TEXT_SECONDARY   = "#9090A8"
TEXT_MUTED       = "#606078"
SIDEBAR_BG      = "#14141F"
SIDEBAR_HOVER    = "#1A1A2A"

FONT_FAMILY      = "Segoe UI"
FONT_TITLE       = (FONT_FAMILY, 22, "bold")
FONT_HEADING     = (FONT_FAMILY, 15, "bold")
FONT_SUBHEADING  = (FONT_FAMILY, 12, "bold")
FONT_BODY        = (FONT_FAMILY, 11)
FONT_BODY_BOLD   = (FONT_FAMILY, 11, "bold")
FONT_SMALL       = (FONT_FAMILY, 10)
FONT_TINY        = (FONT_FAMILY, 9)
FONT_METRIC_VAL  = (FONT_FAMILY, 20, "bold")
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

def _branch_list():
    b = get_all_branches(); return b if b else ["(No branches)"]

def _branch_filter_list():
    b = get_all_branches(); return ["All"] + b if b else ["All"]


# ══════════════════════════════════════════════════════════════════════════════
class MetricCard(ctk.CTkFrame):
    def __init__(self, master, label, value, color=ACCENT, **kw):
        super().__init__(master, corner_radius=12, fg_color=CARD_BG, **kw)
        ctk.CTkFrame(self, height=3, corner_radius=0, fg_color=color).pack(fill="x")
        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=16, pady=(10, 14))
        ctk.CTkLabel(inner, text=str(value), font=FONT_METRIC_VAL,
                      text_color=TEXT_PRIMARY, anchor="w").pack(anchor="w")
        ctk.CTkLabel(inner, text=label, font=FONT_METRIC_LBL,
                      text_color=TEXT_SECONDARY, anchor="w").pack(anchor="w", pady=(2, 0))

class StyledTreeview(ctk.CTkFrame):
    def __init__(self, master, columns, column_widths=None, height=14, **kw):
        super().__init__(master, fg_color=CARD_BG, corner_radius=10, **kw)
        style = ttk.Style(); style.theme_use("clam")
        style.configure("Dark.Treeview", background=SURFACE_3,
                         foreground=TEXT_PRIMARY, fieldbackground=SURFACE_3,
                         borderwidth=0, font=(FONT_FAMILY, 10), rowheight=28)
        style.configure("Dark.Treeview.Heading", background=ACCENT_DARK,
                         foreground="white", font=(FONT_FAMILY, 10, "bold"),
                         borderwidth=0, relief="flat")
        style.map("Dark.Treeview",
                   background=[("selected", ACCENT)], foreground=[("selected", "white")])
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
        self.tree.tag_configure("even", background=SURFACE_2)
        self.tree.tag_configure("odd", background=SURFACE_3)
    def clear(self):
        for item in self.tree.get_children(): self.tree.delete(item)
    def insert_rows(self, rows):
        self.clear()
        for i, row in enumerate(rows):
            self.tree.insert("", "end", values=row, tags=("even" if i % 2 == 0 else "odd",))

class SidebarButton(ctk.CTkButton):
    def __init__(self, master, text, icon, command=None, **kw):
        super().__init__(master, text=f"  {icon}   {text}", font=(FONT_FAMILY, 12),
                         anchor="w", height=42, corner_radius=8, fg_color="transparent",
                         hover_color=SIDEBAR_HOVER, text_color=TEXT_SECONDARY, command=command, **kw)
    def set_active(self, a):
        self.configure(fg_color=ACCENT if a else "transparent",
                       text_color="white" if a else TEXT_SECONDARY,
                       hover_color=ACCENT_HOVER if a else SIDEBAR_HOVER)

class StatusBar(ctk.CTkFrame):
    def __init__(self, master, **kw):
        super().__init__(master, height=28, corner_radius=0, fg_color=SIDEBAR_BG, **kw)
        self.pack_propagate(False)
        self._label = ctk.CTkLabel(self, text="  Ready", font=FONT_TINY,
                                    text_color=TEXT_MUTED, anchor="w")
        self._label.pack(side="left", padx=10, fill="y")
        ctk.CTkLabel(self, text=f"PayrollPro v2.1  •  DB: {os.path.abspath(DB_PATH)}  ",
                      font=FONT_TINY, text_color=TEXT_MUTED, anchor="e").pack(side="right", padx=10, fill="y")
    def set_message(self, msg, color=TEXT_MUTED):
        self._label.configure(text=f"  {msg}", text_color=color)


# ══════════════════════════════════════════════════════════════════════════════
class PayrollApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("PayrollPro — Professional Payroll Management")
        self.geometry("1300x800"); self.minsize(1050, 650)
        init_db(DB_PATH, seed=True)
        self.grid_columnconfigure(1, weight=1); self.grid_rowconfigure(0, weight=1)
        self._build_sidebar(); self._build_main_area(); self._build_status_bar()
        self._navigate("dashboard")

    def _build_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color=SIDEBAR_BG)
        self.sidebar.grid(row=0, column=0, sticky="nsew"); self.sidebar.grid_propagate(False)
        logo = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo.pack(fill="x", padx=16, pady=(20, 6))
        ctk.CTkLabel(logo, text="💼", font=(FONT_FAMILY, 28)).pack(side="left")
        ctk.CTkLabel(logo, text=" PayrollPro", font=(FONT_FAMILY, 18, "bold"),
                      text_color=TEXT_PRIMARY).pack(side="left", padx=(6, 0))
        ctk.CTkLabel(self.sidebar, text="Professional Payroll System",
                      font=FONT_TINY, text_color=TEXT_MUTED).pack(padx=20, anchor="w")
        ctk.CTkFrame(self.sidebar, height=1, fg_color=TEXT_MUTED).pack(fill="x", padx=16, pady=(16, 12))
        nav = [
            ("Dashboard",      "📊", "dashboard"),
            ("Attendance",     "📋", "attendance"),
            ("Workers",        "👷", "workers"),
            ("Branches",       "🏢", "branches"),
            ("Wage Rates",     "💰", "wages"),
            ("Generate Slips", "📄", "slips"),
            ("Settings",       "⚙️",  "settings"),
        ]
        self._nav_buttons = {}
        for text, icon, key in nav:
            btn = SidebarButton(self.sidebar, text=text, icon=icon,
                                command=lambda k=key: self._navigate(k))
            btn.pack(fill="x", padx=12, pady=2); self._nav_buttons[key] = btn
        ctk.CTkFrame(self.sidebar, fg_color="transparent").pack(fill="both", expand=True)
        ctk.CTkFrame(self.sidebar, height=1, fg_color=TEXT_MUTED).pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkLabel(self.sidebar, text="Zero-Cost Payroll System\nPython + SQLite",
                      font=FONT_TINY, text_color=TEXT_MUTED, justify="left"
                      ).pack(padx=20, pady=(0, 16), anchor="w")

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
                                       scrollbar_button_color=TEXT_MUTED, scrollbar_fg_color=SURFACE)
        page.grid(row=0, column=0, sticky="nsew"); self._current_page = page
        {"dashboard": self._page_dashboard, "attendance": self._page_attendance,
         "workers": self._page_workers, "branches": self._page_branches,
         "wages": self._page_wages, "slips": self._page_slips,
         "settings": self._page_settings}.get(key, lambda p: None)(page)
        self.status_bar.set_message(f"Viewing: {key.replace('_',' ').title()}")

    # ══════════════════════════════════════════════════════════════════════
    #   DASHBOARD
    # ══════════════════════════════════════════════════════════════════════
    def _page_dashboard(self, parent):
        ctk.CTkLabel(parent, text="📊  Payroll Dashboard", font=FONT_TITLE,
                      text_color=TEXT_PRIMARY, anchor="w").pack(fill="x", padx=28, pady=(20, 2))
        ctk.CTkLabel(parent, text="Overview of payroll calculations for the selected period",
                      font=FONT_SMALL, text_color=TEXT_SECONDARY, anchor="w"
                      ).pack(fill="x", padx=28, pady=(0, 14))
        ctrl = ctk.CTkFrame(parent, fg_color="transparent"); ctrl.pack(fill="x", padx=28, pady=(0, 10))
        opts = month_options()
        ctk.CTkLabel(ctrl, text="Month:", font=FONT_BODY_BOLD, text_color=TEXT_PRIMARY).pack(side="left")
        month_var = ctk.StringVar(value=opts[-1])
        ctk.CTkOptionMenu(ctrl, values=opts, variable=month_var, width=140,
                           font=FONT_BODY, fg_color=SURFACE_3, button_color=ACCENT,
                           button_hover_color=ACCENT_HOVER).pack(side="left", padx=(8, 20))
        ctk.CTkLabel(ctrl, text="Branch:", font=FONT_BODY_BOLD, text_color=TEXT_PRIMARY).pack(side="left")
        branch_var = ctk.StringVar(value="All")
        ctk.CTkOptionMenu(ctrl, values=_branch_filter_list(), variable=branch_var, width=150,
                           font=FONT_BODY, fg_color=SURFACE_3, button_color=ACCENT,
                           button_hover_color=ACCENT_HOVER).pack(side="left", padx=(8, 20))
        content = ctk.CTkFrame(parent, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=28, pady=(0, 20))

        def refresh():
            for w in content.winfo_children(): w.destroy()
            workers = get_all_workers()
            sw = get_skill_wages_dict()
            att = get_attendance(month_var.get())
            if branch_var.get() != "All":
                workers = [w for w in workers if w.branch == branch_var.get()]
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
            mf = ctk.CTkFrame(content, fg_color="transparent"); mf.pack(fill="x", pady=(0, 14))
            mf.grid_columnconfigure((0,1,2,3,4), weight=1)
            for i, (l, v, c) in enumerate([
                ("Workers", str(s["total_workers"]), ACCENT),
                ("Total Gross", fmt_inr(s["total_gross"]), "#26A69A"),
                ("Total EPF", fmt_inr(s["total_epf"]), WARNING_CLR),
                ("Total ESI", fmt_inr(s["total_esi"]), "#AB47BC"),
                ("Total Net Pay", fmt_inr(s["total_net"]), SUCCESS),
            ]):
                MetricCard(mf, l, v, color=c).grid(row=0, column=i, padx=4, pady=4, sticky="nsew")
            ctk.CTkLabel(content, text="Payroll Breakdown", font=FONT_HEADING,
                          text_color=TEXT_PRIMARY, anchor="w").pack(fill="x", pady=(6, 6))
            cols = ("ID","Name","Branch","Skill","Designation","Days","Gross (₹)","EPF (₹)","ESI (₹)","Net Pay (₹)")
            widths = [60,130,90,80,120,45,100,80,75,110]
            table = StyledTreeview(content, columns=cols, column_widths=widths, height=min(len(results), 14))
            table.pack(fill="both", expand=True, pady=(0, 10))
            table.insert_rows([(r.worker_id, r.worker_name, r.branch, r.skill_category,
                                r.profile_title, r.days_present, fmt_inr(r.gross),
                                fmt_inr(r.epf_deduction), fmt_inr(r.esi_deduction),
                                fmt_inr(r.net_pay)) for r in results])
            def export_csv():
                import pandas as pd
                path = filedialog.asksaveasfilename(defaultextension=".csv",
                    filetypes=[("CSV","*.csv")], initialfile=f"Payroll_{month_var.get()}.csv")
                if path:
                    pd.DataFrame([r.summary_row() for r in results]).to_csv(path, index=False)
                    self.status_bar.set_message(f"✅ CSV → {path}", SUCCESS)
                    messagebox.showinfo("Export", f"CSV saved:\n{path}")
            ctk.CTkButton(content, text="⬇️  Export CSV", font=FONT_BODY_BOLD,
                           fg_color=ACCENT, hover_color=ACCENT_HOVER, height=36,
                           corner_radius=8, command=export_csv).pack(anchor="w", pady=(0, 16))

        month_var.trace_add("write", lambda *_: refresh())
        branch_var.trace_add("write", lambda *_: refresh())
        ctk.CTkButton(ctrl, text="🔄 Refresh", font=FONT_BODY, width=100, fg_color=SURFACE_3,
                       hover_color=SURFACE_2, text_color=TEXT_PRIMARY, height=32,
                       corner_radius=8, command=refresh).pack(side="right")
        refresh()

    # ══════════════════════════════════════════════════════════════════════
    #   ATTENDANCE
    # ══════════════════════════════════════════════════════════════════════
    def _page_attendance(self, parent):
        ctk.CTkLabel(parent, text="📋  Attendance & Earnings Entry", font=FONT_TITLE,
                      text_color=TEXT_PRIMARY, anchor="w").pack(fill="x", padx=28, pady=(20, 2))
        ctk.CTkLabel(parent, text="Enter daily attendance and manage per-worker allowances / deductions",
                      font=FONT_SMALL, text_color=TEXT_SECONDARY, anchor="w"
                      ).pack(fill="x", padx=28, pady=(0, 14))
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
        ctk.CTkLabel(ctrl, text="Branch:", font=FONT_BODY_BOLD, text_color=TEXT_PRIMARY).pack(side="left")
        branch_var = ctk.StringVar(value="All")
        ctk.CTkOptionMenu(ctrl, values=_branch_filter_list(), variable=branch_var, width=140,
                           font=FONT_BODY, fg_color=SURFACE_3, button_color=ACCENT,
                           button_hover_color=ACCENT_HOVER).pack(side="left", padx=(8, 20))
        ctk.CTkLabel(ctrl, text=f"(Max days: {config.working_days})",
                      font=FONT_SMALL, text_color=TEXT_MUTED).pack(side="left")
        table_frame = ctk.CTkFrame(parent, fg_color="transparent")
        table_frame.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self._att_entries = {}

        def refresh():
            for w in table_frame.winfo_children(): w.destroy()
            self._att_entries.clear()
            workers = get_all_workers()
            if branch_var.get() != "All":
                workers = [w for w in workers if w.branch == branch_var.get()]
            existing = {a.worker_id: a for a in get_attendance(month_var.get())}
            sw_dict = get_skill_wages_dict()
            if not workers:
                ctk.CTkLabel(table_frame, text="No workers found. Add workers first.",
                              font=FONT_BODY, text_color=TEXT_MUTED).pack(pady=30); return
            ctk.CTkLabel(table_frame, text="Days Present & Overtime", font=FONT_SUBHEADING,
                          text_color=TEXT_PRIMARY, anchor="w").pack(fill="x", pady=(4, 6))
            hdr = ctk.CTkFrame(table_frame, fg_color=ACCENT_DARK, corner_radius=6)
            hdr.pack(fill="x", pady=(0, 2))
            cols = [("ID",55), ("Name",110), ("Branch",75), ("Skill",70), ("Designation",90), ("Rate/Day",55), ("Days",55), ("OT Hours",80)]
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
                ctk.CTkLabel(row, text=w.branch, font=FONT_TINY, text_color=TEXT_SECONDARY, width=75, anchor="w").pack(side="left", padx=6)
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

            ctk.CTkButton(table_frame, text="💾  Save All Attendance", font=FONT_BODY_BOLD,
                           fg_color=SUCCESS, hover_color="#2E7D32", height=40,
                           corner_radius=8, command=save_all).pack(fill="x", pady=(14, 16))

        month_var.trace_add("write", lambda *_: refresh())
        branch_var.trace_add("write", lambda *_: refresh())
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
        ctk.CTkLabel(parent, text="👷  Worker Master Data", font=FONT_TITLE,
                      text_color=TEXT_PRIMARY, anchor="w").pack(fill="x", padx=28, pady=(20, 2))
        ctk.CTkLabel(parent, text="Add, edit, or delete workers — bank, PF/ESIC, branch, skill & designation",
                      font=FONT_SMALL, text_color=TEXT_SECONDARY, anchor="w"
                      ).pack(fill="x", padx=28, pady=(0, 14))
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
            form_vars["designation"].set(w.designation); form_vars["branch"].set(w.branch)
            form_vars["skill"].set(w.skill_category); form_vars["join"].set(w.joining_date)
            form_vars["bank_acc"].set(w.bank_account); form_vars["bank_name"].set(w.bank_name)
            form_vars["ifsc"].set(w.ifsc_code); form_vars["uan"].set(w.uan_number)
            form_vars["esic"].set(w.esic_number)
            tabview.set("➕ Add / Edit")
            self.status_bar.set_message(f"Editing worker {w.worker_id} — {w.name}", ACCENT)

        def _clear_form():
            for k in ["wid","name","designation","bank_acc","bank_name","ifsc","uan","esic"]:
                form_vars[k].set("")
            form_vars["join"].set(str(datetime.date.today()))
            b = get_all_branches()
            form_vars["branch"].set(b[0] if b else "")
            form_vars["skill"].set(SKILL_CATEGORIES[-1])
            self.status_bar.set_message("Form cleared — ready to add a new worker.")

        def refresh_workers():
            for w in tab_all.winfo_children(): w.destroy()
            fc = ctk.CTkFrame(tab_all, fg_color="transparent"); fc.pack(fill="x", padx=8, pady=(8, 6))
            ctk.CTkLabel(fc, text="Filter Branch:", font=FONT_BODY_BOLD, text_color=TEXT_PRIMARY).pack(side="left")
            filt_var = ctk.StringVar(value="All")
            ctk.CTkOptionMenu(fc, values=_branch_filter_list(), variable=filt_var, width=140,
                               font=FONT_BODY, fg_color=SURFACE_3, button_color=ACCENT,
                               button_hover_color=ACCENT_HOVER).pack(side="left", padx=(8, 0))
            table_container = ctk.CTkFrame(tab_all, fg_color="transparent")
            table_container.pack(fill="both", expand=True, padx=8)

            def update_table(*_):
                for w in table_container.winfo_children(): w.destroy()
                workers = get_all_workers(active_only=False)
                if filt_var.get() != "All":
                    workers = [w for w in workers if w.branch == filt_var.get()]
                if not workers:
                    ef = ctk.CTkFrame(table_container, fg_color=CARD_BG, corner_radius=12)
                    ef.pack(fill="x", pady=30, padx=30)
                    ctk.CTkLabel(ef, text="👤", font=(FONT_FAMILY, 36)).pack(pady=(20, 4))
                    ctk.CTkLabel(ef, text="No workers yet", font=FONT_HEADING, text_color=TEXT_SECONDARY).pack()
                    ctk.CTkLabel(ef, text='Use "➕ Add / Edit" tab to add your first worker.',
                                 font=FONT_SMALL, text_color=TEXT_MUTED).pack(pady=(4, 20))
                    return
                cols = ("ID","Name","Branch","Skill","Designation","Bank","A/C","IFSC","UAN","ESIC","Status")
                widths = [55,120,80,70,90,90,100,90,80,70,45]
                table = StyledTreeview(table_container, columns=cols, column_widths=widths,
                                        height=min(len(workers), 12))
                table.pack(fill="both", expand=True, pady=(4, 4))
                table.insert_rows([(w.worker_id, w.name, w.branch, w.skill_category,
                                    w.designation, w.bank_name, w.bank_account, w.ifsc_code,
                                    w.uan_number, w.esic_number,
                                    "✅" if w.active else "❌") for w in workers])

                ctrl = ctk.CTkFrame(table_container, fg_color="transparent"); ctrl.pack(fill="x", pady=(6, 8))
                all_ids = [w.worker_id for w in workers]
                sel_var = ctk.StringVar(value=all_ids[0])
                ctk.CTkLabel(ctrl, text="Select:", font=FONT_BODY_BOLD, text_color=TEXT_PRIMARY).pack(side="left")
                ctk.CTkOptionMenu(ctrl, values=all_ids, variable=sel_var, width=100, font=FONT_BODY,
                                   fg_color=SURFACE_3, button_color=ACCENT,
                                   button_hover_color=ACCENT_HOVER).pack(side="left", padx=(8, 12))
                ctk.CTkButton(ctrl, text="✏️ Edit", font=FONT_BODY, fg_color=ACCENT,
                               hover_color=ACCENT_HOVER, height=30, corner_radius=6, width=80,
                               command=lambda: _populate_form(sel_var.get())).pack(side="left", padx=(0, 6))
                def do_toggle():
                    w = get_worker_by_id(sel_var.get())
                    if not w: return
                    if w.active:
                        if messagebox.askyesno("Confirm", f"Deactivate '{sel_var.get()}'?"):
                            deactivate_worker(sel_var.get())
                            self.status_bar.set_message(f"Worker deactivated.", WARNING_CLR); update_table()
                    else:
                        reactivate_worker(sel_var.get())
                        self.status_bar.set_message(f"Worker re-activated.", SUCCESS); update_table()
                ctk.CTkButton(ctrl, text="🔄 Toggle", font=FONT_BODY, fg_color=WARNING_CLR,
                               hover_color="#E65100", height=30, corner_radius=6, width=90,
                               command=do_toggle).pack(side="left", padx=(0, 6))
                def do_delete():
                    if messagebox.askyesno("⚠️ Delete",
                        f"Permanently delete '{sel_var.get()}' and ALL attendance?\nCannot undo.", icon="warning"):
                        delete_worker(sel_var.get())
                        self.status_bar.set_message(f"Worker deleted.", DANGER); update_table()
                ctk.CTkButton(ctrl, text="🗑️ Delete", font=FONT_BODY, fg_color=DANGER,
                               hover_color="#C62828", height=30, corner_radius=6, width=80,
                               command=do_delete).pack(side="left")
                def on_dbl(event):
                    sel = table.tree.selection()
                    if sel:
                        vals = table.tree.item(sel[0])["values"]
                        if vals: _populate_form(str(vals[0]))
                table.tree.bind("<Double-1>", on_dbl)
            filt_var.trace_add("write", update_table); update_table()

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

        # Branch dropdown
        bf = ctk.CTkFrame(ff, fg_color="transparent"); bf.grid(row=1, column=0, padx=8, pady=4, sticky="ew")
        ctk.CTkLabel(bf, text="Branch *", font=FONT_SMALL, text_color=TEXT_SECONDARY).pack(anchor="w")
        branches = _branch_list()
        branch_var = ctk.StringVar(value=branches[0] if branches else "")
        ctk.CTkOptionMenu(bf, values=branches, variable=branch_var, font=FONT_BODY,
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

        wjoin_var = mkf(ff, "Joining Date (YYYY-MM-DD)", 1, 2, str(datetime.date.today()))
        wbank_var = mkf(ff, "Bank Account Number", 2, 0)
        wbname_var = mkf(ff, "Bank Name", 2, 1)
        wifsc_var = mkf(ff, "IFSC Code", 2, 2)
        wuan_var = mkf(ff, "UAN / PF ID Number", 3, 0)
        wesic_var = mkf(ff, "ESIC IP Number", 3, 1)

        form_vars.update({"wid": wid_var, "name": wname_var, "designation": wdesig_var,
                          "branch": branch_var, "skill": skill_var, "join": wjoin_var,
                          "bank_acc": wbank_var, "bank_name": wbname_var, "ifsc": wifsc_var,
                          "uan": wuan_var, "esic": wesic_var})

        def save_worker():
            wid = wid_var.get().strip().upper(); wname = wname_var.get().strip()
            if not wid or not wname:
                messagebox.showerror("Required", "Worker ID and Name are required."); return
            b = branch_var.get()
            if not b or b == "(No branches)":
                messagebox.showerror("Required", "Create a Branch first (🏢 Branches)."); return
            upsert_worker(Worker(
                worker_id=wid, name=wname, designation=wdesig_var.get().strip(),
                bank_account=wbank_var.get().strip(), bank_name=wbname_var.get().strip(),
                ifsc_code=wifsc_var.get().strip(), uan_number=wuan_var.get().strip(),
                esic_number=wesic_var.get().strip(), joining_date=wjoin_var.get().strip(),
                active=True, branch=b, skill_category=skill_var.get()))
            self.status_bar.set_message(f"✅ Worker {wid} saved!", SUCCESS)
            messagebox.showinfo("Saved", f"Worker {wid} saved!")
            _clear_form(); refresh_workers()

        ctk.CTkButton(form, text="💾  Save Worker", font=FONT_BODY_BOLD, fg_color=SUCCESS,
                       hover_color="#2E7D32", height=40, corner_radius=8,
                       command=save_worker).pack(pady=(4, 16))
        refresh_workers()

    # ══════════════════════════════════════════════════════════════════════
    #   BRANCHES
    # ══════════════════════════════════════════════════════════════════════
    def _page_branches(self, parent):
        ctk.CTkLabel(parent, text="🏢  Branch Management", font=FONT_TITLE,
                      text_color=TEXT_PRIMARY, anchor="w").pack(fill="x", padx=28, pady=(20, 2))
        ctk.CTkLabel(parent, text="Add, rename, or remove company branches",
                      font=FONT_SMALL, text_color=TEXT_SECONDARY, anchor="w"
                      ).pack(fill="x", padx=28, pady=(0, 14))
        content = ctk.CTkFrame(parent, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=28, pady=(0, 20))

        def refresh():
            for w in content.winfo_children(): w.destroy()
            branches = get_all_branches(); counts = branch_worker_count()
            add_card = ctk.CTkFrame(content, fg_color=CARD_BG, corner_radius=12)
            add_card.pack(fill="x", pady=(0, 16))
            ctk.CTkLabel(add_card, text="➕  Add New Branch", font=FONT_HEADING,
                          text_color=TEXT_PRIMARY).pack(padx=20, pady=(16, 8), anchor="w")
            add_row = ctk.CTkFrame(add_card, fg_color="transparent"); add_row.pack(fill="x", padx=20, pady=(0, 16))
            new_var = ctk.StringVar()
            ctk.CTkEntry(add_row, textvariable=new_var, height=36, width=300, font=FONT_BODY,
                          fg_color=SURFACE, border_color=TEXT_MUTED, corner_radius=6,
                          placeholder_text="Enter branch name...").pack(side="left", padx=(0, 12))
            def do_add():
                name = new_var.get().strip()
                if not name: messagebox.showerror("Required", "Branch name cannot be empty."); return
                try: add_branch(name); self.status_bar.set_message(f"✅ Branch '{name}' added!", SUCCESS); new_var.set(""); refresh()
                except Exception as e: messagebox.showerror("Error", f"Already exists or error:\n{e}")
            ctk.CTkButton(add_row, text="➕ Add Branch", font=FONT_BODY_BOLD, fg_color=SUCCESS,
                           hover_color="#2E7D32", height=36, corner_radius=8, command=do_add).pack(side="left")
            if not branches:
                ef = ctk.CTkFrame(content, fg_color=CARD_BG, corner_radius=12); ef.pack(fill="x", pady=10)
                ctk.CTkLabel(ef, text="🏢", font=(FONT_FAMILY, 36)).pack(pady=(20, 4))
                ctk.CTkLabel(ef, text="No branches yet", font=FONT_HEADING, text_color=TEXT_SECONDARY).pack()
                ctk.CTkLabel(ef, text="Add your first branch above.",
                             font=FONT_SMALL, text_color=TEXT_MUTED).pack(pady=(4, 20))
                return
            ctk.CTkLabel(content, text="Existing Branches", font=FONT_HEADING,
                          text_color=TEXT_PRIMARY, anchor="w").pack(fill="x", pady=(0, 8))
            for b in branches:
                count = counts.get(b, 0)
                card = ctk.CTkFrame(content, fg_color=CARD_BG, corner_radius=10); card.pack(fill="x", pady=3)
                ir = ctk.CTkFrame(card, fg_color="transparent"); ir.pack(fill="x", padx=16, pady=10)
                ctk.CTkLabel(ir, text=f"📍  {b}", font=FONT_BODY_BOLD, text_color=TEXT_PRIMARY).pack(side="left")
                ctk.CTkLabel(ir, text=f"  ({count} worker{'s' if count != 1 else ''})",
                              font=FONT_SMALL, text_color=TEXT_MUTED).pack(side="left", padx=(4, 0))
                def mk_rename(bn=b):
                    def do():
                        d = ctk.CTkInputDialog(text=f"Rename '{bn}' to:", title="Rename Branch")
                        nn = d.get_input()
                        if nn and nn.strip():
                            try: rename_branch(bn, nn.strip()); self.status_bar.set_message(f"✅ Renamed → {nn.strip()}", SUCCESS); refresh()
                            except Exception as e: messagebox.showerror("Error", str(e))
                    return do
                ctk.CTkButton(ir, text="✏️ Rename", font=FONT_SMALL, fg_color=ACCENT,
                               hover_color=ACCENT_HOVER, height=28, corner_radius=6, width=80,
                               command=mk_rename()).pack(side="right", padx=(6, 0))
                def mk_del(bn=b, wc=count):
                    def do():
                        extra = f"\n\n⚠️ {wc} worker(s) will become unassigned." if wc > 0 else ""
                        if messagebox.askyesno("Delete Branch", f"Delete '{bn}'?{extra}",
                                                icon="warning" if wc > 0 else "question"):
                            delete_branch(bn); self.status_bar.set_message(f"🗑️ '{bn}' deleted.", DANGER); refresh()
                    return do
                ctk.CTkButton(ir, text="🗑️", font=FONT_SMALL, fg_color=DANGER,
                               hover_color="#C62828", height=28, corner_radius=6, width=40,
                               command=mk_del()).pack(side="right")
        refresh()

    # ══════════════════════════════════════════════════════════════════════
    #   WAGE RATES  (per skill category)
    # ══════════════════════════════════════════════════════════════════════
    def _page_wages(self, parent):
        ctk.CTkLabel(parent, text="💰  Wage Rates by Skill Category", font=FONT_TITLE,
                      text_color=TEXT_PRIMARY, anchor="w").pack(fill="x", padx=28, pady=(20, 2))
        ctk.CTkLabel(parent, text="Set the daily wage and OT rate for each skill level — all workers in a category get the same rate",
                      font=FONT_SMALL, text_color=TEXT_SECONDARY, anchor="w"
                      ).pack(fill="x", padx=28, pady=(0, 14))

        content = ctk.CTkFrame(parent, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=28, pady=(0, 20))

        wages = get_skill_wages_dict()
        entries = {}

        for cat in SKILL_CATEGORIES:
            sw = wages.get(cat, SkillWage(cat, 0, 0))
            card = ctk.CTkFrame(content, fg_color=CARD_BG, corner_radius=12)
            card.pack(fill="x", pady=6)

            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="x", padx=20, pady=16)

            # Category label
            color = {"Skilled": SUCCESS, "Semi-Skilled": WARNING_CLR, "Unskilled": ACCENT}.get(cat, ACCENT)
            badge = ctk.CTkFrame(inner, fg_color=color, corner_radius=6, width=12, height=36)
            badge.pack(side="left", padx=(0, 12))
            badge.pack_propagate(False)

            ctk.CTkLabel(inner, text=cat, font=FONT_HEADING,
                          text_color=TEXT_PRIMARY, width=130, anchor="w").pack(side="left")

            # Daily wage
            ctk.CTkLabel(inner, text="Daily Wage (₹):", font=FONT_BODY,
                          text_color=TEXT_SECONDARY).pack(side="left", padx=(20, 6))
            dw_var = ctk.StringVar(value=str(sw.daily_wage))
            ctk.CTkEntry(inner, textvariable=dw_var, width=100, height=32, font=FONT_BODY,
                          fg_color=SURFACE, border_color=TEXT_MUTED, corner_radius=6
                          ).pack(side="left", padx=(0, 20))

            # OT rate
            ctk.CTkLabel(inner, text="OT Rate (₹/hr):", font=FONT_BODY,
                          text_color=TEXT_SECONDARY).pack(side="left", padx=(0, 6))
            ot_var = ctk.StringVar(value=str(sw.ot_rate))
            ctk.CTkEntry(inner, textvariable=ot_var, width=100, height=32, font=FONT_BODY,
                          fg_color=SURFACE, border_color=TEXT_MUTED, corner_radius=6
                          ).pack(side="left")

            entries[cat] = {"dw": dw_var, "ot": ot_var}

        # Info note
        note = ctk.CTkFrame(content, fg_color="#1A2A3A", corner_radius=8)
        note.pack(fill="x", pady=(12, 6))
        ctk.CTkLabel(note, text="ℹ️  All workers in the same skill category earn the same daily wage.\n"
                     "    Designation (Sweeper, Janitor, etc.) is just a label — it does NOT affect pay.",
                      font=FONT_SMALL, text_color=TEXT_SECONDARY, justify="left"
                      ).pack(padx=14, pady=10, anchor="w")

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
                       fg_color=SUCCESS, hover_color="#2E7D32", height=44,
                       corner_radius=8, command=save_wages).pack(fill="x", pady=(12, 16))

    # ══════════════════════════════════════════════════════════════════════
    #   GENERATE SLIPS
    # ══════════════════════════════════════════════════════════════════════
    def _page_slips(self, parent):
        ctk.CTkLabel(parent, text="📄  Generate Salary Slips", font=FONT_TITLE,
                      text_color=TEXT_PRIMARY, anchor="w").pack(fill="x", padx=28, pady=(20, 2))
        ctk.CTkLabel(parent, text="Generate PDF salary slips — per branch or all workers",
                      font=FONT_SMALL, text_color=TEXT_SECONDARY, anchor="w"
                      ).pack(fill="x", padx=28, pady=(0, 14))
        ctrl = ctk.CTkFrame(parent, fg_color="transparent"); ctrl.pack(fill="x", padx=28, pady=(0, 10))
        opts = month_options()
        ctk.CTkLabel(ctrl, text="Month:", font=FONT_BODY_BOLD, text_color=TEXT_PRIMARY).pack(side="left")
        month_var = ctk.StringVar(value=opts[-1])
        ctk.CTkOptionMenu(ctrl, values=opts, variable=month_var, width=140, font=FONT_BODY,
                           fg_color=SURFACE_3, button_color=ACCENT,
                           button_hover_color=ACCENT_HOVER).pack(side="left", padx=(8, 20))
        ctk.CTkLabel(ctrl, text="Branch:", font=FONT_BODY_BOLD, text_color=TEXT_PRIMARY).pack(side="left")
        branch_var = ctk.StringVar(value="All")
        ctk.CTkOptionMenu(ctrl, values=_branch_filter_list(), variable=branch_var, width=150,
                           font=FONT_BODY, fg_color=SURFACE_3, button_color=ACCENT,
                           button_hover_color=ACCENT_HOVER).pack(side="left", padx=(8, 0))
        content = ctk.CTkFrame(parent, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=28, pady=(0, 20))

        def refresh():
            for w in content.winfo_children(): w.destroy()
            workers = get_all_workers()
            if branch_var.get() != "All":
                workers = [w for w in workers if w.branch == branch_var.get()]
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
            ctk.CTkLabel(content, text=f"Ready: {len(results)} slip(s)", font=FONT_HEADING,
                          text_color=TEXT_PRIMARY, anchor="w").pack(fill="x", pady=(0, 6))
            cols = ("ID","Name","Branch","Skill","Designation","Net Pay (₹)")
            table = StyledTreeview(content, columns=cols, column_widths=[70,150,100,80,130,120],
                                    height=min(len(results), 10))
            table.pack(fill="both", expand=True, pady=(0, 10))
            table.insert_rows([(r.worker_id, r.worker_name, r.branch, r.skill_category,
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
                           fg_color=ACCENT, hover_color=ACCENT_HOVER, height=42,
                           corner_radius=8, command=gen_all).pack(fill="x", pady=(8, 8))

            single = ctk.CTkFrame(content, fg_color=CARD_BG, corner_radius=10); single.pack(fill="x", pady=(4, 4))
            ctk.CTkLabel(single, text="Generate Single Slip", font=FONT_SUBHEADING,
                          text_color=TEXT_PRIMARY).pack(padx=12, pady=(10, 4), anchor="w")
            sc = ctk.CTkFrame(single, fg_color="transparent"); sc.pack(fill="x", padx=12, pady=(0, 12))
            nl = [f"{r.worker_id} — {r.worker_name} [{r.branch}]" for r in results]
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
        branch_var.trace_add("write", lambda *_: refresh())
        refresh()

    # ══════════════════════════════════════════════════════════════════════
    #   SETTINGS
    # ══════════════════════════════════════════════════════════════════════
    def _page_settings(self, parent):
        ctk.CTkLabel(parent, text="⚙️  Company Settings", font=FONT_TITLE,
                      text_color=TEXT_PRIMARY, anchor="w").pack(fill="x", padx=28, pady=(20, 2))
        ctk.CTkLabel(parent, text="Company information and configuration",
                      font=FONT_SMALL, text_color=TEXT_SECONDARY, anchor="w"
                      ).pack(fill="x", padx=28, pady=(0, 14))
        cfg = get_config()
        form = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=12); form.pack(fill="x", padx=28, pady=(0, 16))
        ctk.CTkLabel(form, text="Company Information", font=FONT_HEADING,
                      text_color=TEXT_PRIMARY).pack(padx=20, pady=(16, 12), anchor="w")
        ff = ctk.CTkFrame(form, fg_color="transparent"); ff.pack(fill="x", padx=20, pady=(0, 12))
        def sf(p, lbl, default=""):
            f = ctk.CTkFrame(p, fg_color="transparent"); f.pack(fill="x", pady=3)
            ctk.CTkLabel(f, text=lbl, font=FONT_SMALL, text_color=TEXT_SECONDARY, width=180, anchor="w").pack(side="left")
            v = ctk.StringVar(value=default)
            ctk.CTkEntry(f, textvariable=v, height=30, font=FONT_BODY, fg_color=SURFACE,
                          border_color=TEXT_MUTED, corner_radius=6).pack(side="left", fill="x", expand=True, padx=(8, 0))
            return v
        cn=sf(ff,"Company Name",cfg.company_name); a1=sf(ff,"Address Line 1",cfg.address_line1)
        a2=sf(ff,"Address Line 2",cfg.address_line2); ph=sf(ff,"Phone",cfg.phone); em=sf(ff,"Email",cfg.email)
        wdf = ctk.CTkFrame(ff, fg_color="transparent"); wdf.pack(fill="x", pady=3)
        ctk.CTkLabel(wdf, text="Working Days / Month", font=FONT_SMALL, text_color=TEXT_SECONDARY, width=180, anchor="w").pack(side="left")
        wd = ctk.StringVar(value=str(cfg.working_days))
        ctk.CTkEntry(wdf, textvariable=wd, height=30, width=80, font=FONT_BODY, fg_color=SURFACE,
                      border_color=TEXT_MUTED, corner_radius=6).pack(side="left", padx=(8, 0))
        def save_cfg():
            try: w = int(wd.get())
            except ValueError: messagebox.showerror("Error", "Working days must be a number."); return
            save_config(CompanyConfig(cn.get(), a1.get(), a2.get(), ph.get(), em.get(), w))
            self.status_bar.set_message("✅ Settings saved!", SUCCESS)
            messagebox.showinfo("Saved", "Company settings saved!")
        ctk.CTkButton(form, text="💾  Save Settings", font=FONT_BODY_BOLD, fg_color=SUCCESS,
                       hover_color="#2E7D32", height=42, corner_radius=8, command=save_cfg).pack(pady=(0, 16))

        db = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=12); db.pack(fill="x", padx=28, pady=(0, 16))
        ctk.CTkLabel(db, text="System Information", font=FONT_HEADING,
                      text_color=TEXT_PRIMARY).pack(padx=20, pady=(16, 6), anchor="w")
        ctk.CTkLabel(db, text=f"Database: {os.path.abspath(DB_PATH)}",
                      font=FONT_SMALL, text_color=TEXT_MUTED).pack(padx=20, anchor="w")
        ctk.CTkLabel(db, text=f"Branches: {len(get_all_branches())}  |  Workers: {len(get_all_workers(active_only=False))}",
                      font=FONT_SMALL, text_color=TEXT_MUTED).pack(padx=20, anchor="w", pady=(2, 12))


if __name__ == "__main__":
    app = PayrollApp()
    app.mainloop()
