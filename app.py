"""
app.py — PayrollPro Desktop Application
========================================
Professional native desktop payroll software.
Run with:  python app.py
"""

import os
import io
import sys
import csv
import tempfile
import datetime
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import customtkinter as ctk

from schema import Worker, MasterProfile, AttendanceRecord, CompanyConfig
from database import (
    init_db, get_all_workers, get_all_profiles, get_profiles_dict,
    get_attendance, upsert_attendance, bulk_upsert_attendance,
    upsert_worker, deactivate_worker, upsert_profile, delete_profile,
    get_config, save_config, get_months_with_data,
    import_attendance_from_csv, DB_PATH,
)
from payroll_engine import calculate_payroll, payroll_summary
from pdf_generator import generate_bulk_pdfs, generate_slip_pdf

# ── Theme & Constants ─────────────────────────────────────────────────────────
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
SIDEBAR_ACTIVE   = "#1E88E5"
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

APP_WIDTH  = 1280
APP_HEIGHT = 780


# ── Helpers ───────────────────────────────────────────────────────────────────
def month_options():
    """Generate last 12 months as 'YYYY-MM' strings."""
    today = datetime.date.today()
    months = []
    for i in range(11, -1, -1):
        y, m = today.year, today.month - i
        while m <= 0:
            m += 12
            y -= 1
        months.append(f"{y}-{m:02d}")
    return months


def fmt_inr(amount):
    """Format amount in Indian currency style."""
    s = f"{abs(amount):,.2f}"
    p = s.split(".")
    n = p[0].replace(",", "")
    if len(n) <= 3:
        fmt = n
    else:
        last3 = n[-3:]
        rest = n[:-3]
        grps = []
        while len(rest) > 2:
            grps.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            grps.insert(0, rest)
        fmt = ",".join(grps) + "," + last3
    result = f"₹{fmt}.{p[1]}"
    return ("-" + result) if amount < 0 else result


# ══════════════════════════════════════════════════════════════════════════════
#   METRIC CARD WIDGET
# ══════════════════════════════════════════════════════════════════════════════
class MetricCard(ctk.CTkFrame):
    """A styled metric card showing a value and label."""

    def __init__(self, master, label, value, color=ACCENT, **kw):
        super().__init__(master, corner_radius=12, fg_color=CARD_BG, **kw)

        # Top accent line
        accent = ctk.CTkFrame(self, height=3, corner_radius=0, fg_color=color)
        accent.pack(fill="x", padx=0, pady=0)

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=16, pady=(10, 14))

        self._val_label = ctk.CTkLabel(
            inner, text=str(value), font=FONT_METRIC_VAL,
            text_color=TEXT_PRIMARY, anchor="w"
        )
        self._val_label.pack(anchor="w")

        self._name_label = ctk.CTkLabel(
            inner, text=label, font=FONT_METRIC_LBL,
            text_color=TEXT_SECONDARY, anchor="w"
        )
        self._name_label.pack(anchor="w", pady=(2, 0))

    def update_value(self, value, label=None):
        self._val_label.configure(text=str(value))
        if label:
            self._name_label.configure(text=label)


# ══════════════════════════════════════════════════════════════════════════════
#   STYLED TREEVIEW TABLE
# ══════════════════════════════════════════════════════════════════════════════
class StyledTreeview(ctk.CTkFrame):
    """A dark-themed treeview table inside a CTk frame."""

    def __init__(self, master, columns, column_widths=None, height=14, **kw):
        super().__init__(master, fg_color=CARD_BG, corner_radius=10, **kw)

        style = ttk.Style()
        style.theme_use("clam")

        style.configure("Dark.Treeview",
                         background=SURFACE_3,
                         foreground=TEXT_PRIMARY,
                         fieldbackground=SURFACE_3,
                         borderwidth=0,
                         font=(FONT_FAMILY, 10),
                         rowheight=30)
        style.configure("Dark.Treeview.Heading",
                         background=ACCENT_DARK,
                         foreground="white",
                         font=(FONT_FAMILY, 10, "bold"),
                         borderwidth=0,
                         relief="flat")
        style.map("Dark.Treeview",
                   background=[("selected", ACCENT)],
                   foreground=[("selected", "white")])
        style.map("Dark.Treeview.Heading",
                   background=[("active", ACCENT)])

        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=6, pady=6)

        self.tree = ttk.Treeview(
            container, columns=columns, show="headings",
            style="Dark.Treeview", height=height,
            selectmode="browse"
        )

        scrollbar = ctk.CTkScrollbar(container, command=self.tree.yview,
                                      fg_color=SURFACE_3, button_color=TEXT_MUTED)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for i, col in enumerate(columns):
            w = (column_widths[i] if column_widths and i < len(column_widths)
                 else 120)
            self.tree.heading(col, text=col, anchor="w")
            self.tree.column(col, width=w, minwidth=60, anchor="w")

        # Alternate row striping via tags
        self.tree.tag_configure("even", background=SURFACE_2)
        self.tree.tag_configure("odd", background=SURFACE_3)

    def clear(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

    def insert_rows(self, rows):
        """rows: list of tuples matching column order"""
        self.clear()
        for i, row in enumerate(rows):
            tag = "even" if i % 2 == 0 else "odd"
            self.tree.insert("", "end", values=row, tags=(tag,))


# ══════════════════════════════════════════════════════════════════════════════
#   SIDEBAR BUTTON
# ══════════════════════════════════════════════════════════════════════════════
class SidebarButton(ctk.CTkButton):
    """A sidebar navigation button with icon + label."""

    def __init__(self, master, text, icon, command=None, **kw):
        super().__init__(
            master,
            text=f"  {icon}   {text}",
            font=(FONT_FAMILY, 12),
            anchor="w",
            height=42,
            corner_radius=8,
            fg_color="transparent",
            hover_color=SIDEBAR_HOVER,
            text_color=TEXT_SECONDARY,
            command=command,
            **kw,
        )
        self._is_active = False

    def set_active(self, active):
        self._is_active = active
        if active:
            self.configure(fg_color=ACCENT, text_color="white",
                           hover_color=ACCENT_HOVER)
        else:
            self.configure(fg_color="transparent", text_color=TEXT_SECONDARY,
                           hover_color=SIDEBAR_HOVER)


# ══════════════════════════════════════════════════════════════════════════════
#   STATUS BAR
# ══════════════════════════════════════════════════════════════════════════════
class StatusBar(ctk.CTkFrame):
    """Bottom status bar with message display."""

    def __init__(self, master, **kw):
        super().__init__(master, height=28, corner_radius=0,
                         fg_color=SIDEBAR_BG, **kw)
        self.pack_propagate(False)

        self._label = ctk.CTkLabel(
            self, text="  Ready", font=FONT_TINY,
            text_color=TEXT_MUTED, anchor="w"
        )
        self._label.pack(side="left", padx=10, fill="y")

        self._right = ctk.CTkLabel(
            self, text=f"PayrollPro v2.0  •  DB: {os.path.abspath(DB_PATH)}  ",
            font=FONT_TINY, text_color=TEXT_MUTED, anchor="e"
        )
        self._right.pack(side="right", padx=10, fill="y")

    def set_message(self, msg, color=TEXT_MUTED):
        self._label.configure(text=f"  {msg}", text_color=color)


# ══════════════════════════════════════════════════════════════════════════════
#   MAIN APPLICATION
# ══════════════════════════════════════════════════════════════════════════════
class PayrollApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("PayrollPro — Professional Payroll Management")
        self.geometry(f"{APP_WIDTH}x{APP_HEIGHT}")
        self.minsize(1000, 600)

        # Try to set window icon (optional)
        try:
            self.iconbitmap(default="")
        except Exception:
            pass

        init_db(DB_PATH, seed=True)

        # ── Main layout -------------------------------------------------
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main_area()
        self._build_status_bar()

        # Show dashboard by default
        self._navigate("dashboard")

    # ─── Sidebar ─────────────────────────────────────────────────────────
    def _build_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0,
                                     fg_color=SIDEBAR_BG)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        # Logo area
        logo_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo_frame.pack(fill="x", padx=16, pady=(20, 6))

        ctk.CTkLabel(
            logo_frame, text="💼", font=(FONT_FAMILY, 28)
        ).pack(side="left")
        ctk.CTkLabel(
            logo_frame, text=" PayrollPro",
            font=(FONT_FAMILY, 18, "bold"), text_color=TEXT_PRIMARY
        ).pack(side="left", padx=(6, 0))

        ctk.CTkLabel(
            self.sidebar, text="Professional Payroll System",
            font=FONT_TINY, text_color=TEXT_MUTED
        ).pack(padx=20, anchor="w")

        # Divider
        ctk.CTkFrame(self.sidebar, height=1, fg_color=TEXT_MUTED).pack(
            fill="x", padx=16, pady=(16, 12)
        )

        # Navigation buttons
        nav_items = [
            ("Dashboard",      "📊", "dashboard"),
            ("Attendance",     "📋", "attendance"),
            ("Workers",        "👷", "workers"),
            ("Job Profiles",   "🏷️", "profiles"),
            ("Generate Slips", "📄", "slips"),
            ("Settings",       "⚙️",  "settings"),
        ]

        self._nav_buttons = {}
        for text, icon, key in nav_items:
            btn = SidebarButton(
                self.sidebar, text=text, icon=icon,
                command=lambda k=key: self._navigate(k)
            )
            btn.pack(fill="x", padx=12, pady=2)
            self._nav_buttons[key] = btn

        # Bottom info
        spacer = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        spacer.pack(fill="both", expand=True)

        ctk.CTkFrame(self.sidebar, height=1, fg_color=TEXT_MUTED).pack(
            fill="x", padx=16, pady=(0, 8)
        )
        ctk.CTkLabel(
            self.sidebar, text="Zero-Cost Payroll System\nPython + SQLite",
            font=FONT_TINY, text_color=TEXT_MUTED, justify="left"
        ).pack(padx=20, pady=(0, 16), anchor="w")

    # ─── Main content area ───────────────────────────────────────────────
    def _build_main_area(self):
        self.main_area = ctk.CTkFrame(self, corner_radius=0, fg_color=SURFACE)
        self.main_area.grid(row=0, column=1, sticky="nsew")
        self.main_area.grid_columnconfigure(0, weight=1)
        self.main_area.grid_rowconfigure(0, weight=1)

        self._pages = {}
        self._current_page = None

    def _build_status_bar(self):
        self.status_bar = StatusBar(self)
        self.status_bar.grid(row=1, column=0, columnspan=2, sticky="ew")

    # ─── Navigation ──────────────────────────────────────────────────────
    def _navigate(self, page_key):
        # Update sidebar highlights
        for k, btn in self._nav_buttons.items():
            btn.set_active(k == page_key)

        # Destroy current page
        if self._current_page:
            self._current_page.destroy()

        # Build new page
        builders = {
            "dashboard":  self._build_dashboard,
            "attendance": self._build_attendance,
            "workers":    self._build_workers,
            "profiles":   self._build_profiles,
            "slips":      self._build_slips,
            "settings":   self._build_settings,
        }

        page = ctk.CTkScrollableFrame(
            self.main_area, fg_color=SURFACE,
            scrollbar_button_color=TEXT_MUTED,
            scrollbar_fg_color=SURFACE
        )
        page.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        self._current_page = page

        builder = builders.get(page_key)
        if builder:
            builder(page)

        self.status_bar.set_message(f"Viewing: {page_key.title()}")

    # ══════════════════════════════════════════════════════════════════════
    #   PAGE: DASHBOARD
    # ══════════════════════════════════════════════════════════════════════
    def _build_dashboard(self, parent):
        # Title
        ctk.CTkLabel(
            parent, text="📊  Payroll Dashboard",
            font=FONT_TITLE, text_color=TEXT_PRIMARY, anchor="w"
        ).pack(fill="x", padx=28, pady=(20, 4))

        ctk.CTkLabel(
            parent, text="Overview of payroll calculations for the selected period",
            font=FONT_SMALL, text_color=TEXT_SECONDARY, anchor="w"
        ).pack(fill="x", padx=28, pady=(0, 16))

        # Controls row
        ctrl = ctk.CTkFrame(parent, fg_color="transparent")
        ctrl.pack(fill="x", padx=28, pady=(0, 12))

        opts = month_options()
        ctk.CTkLabel(ctrl, text="Month:", font=FONT_BODY_BOLD,
                      text_color=TEXT_PRIMARY).pack(side="left")
        month_var = ctk.StringVar(value=opts[-1])
        month_menu = ctk.CTkOptionMenu(
            ctrl, values=opts, variable=month_var,
            width=140, font=FONT_BODY,
            fg_color=SURFACE_3, button_color=ACCENT,
            button_hover_color=ACCENT_HOVER
        )
        month_menu.pack(side="left", padx=(8, 20))

        locs = sorted({p.location for p in get_all_profiles()})
        ctk.CTkLabel(ctrl, text="Location:", font=FONT_BODY_BOLD,
                      text_color=TEXT_PRIMARY).pack(side="left")
        loc_var = ctk.StringVar(value="All")
        loc_menu = ctk.CTkOptionMenu(
            ctrl, values=["All"] + locs, variable=loc_var,
            width=160, font=FONT_BODY,
            fg_color=SURFACE_3, button_color=ACCENT,
            button_hover_color=ACCENT_HOVER
        )
        loc_menu.pack(side="left", padx=(8, 20))

        # Container for dynamic content
        content_frame = ctk.CTkFrame(parent, fg_color="transparent")
        content_frame.pack(fill="both", expand=True, padx=28, pady=(0, 20))

        def refresh_dashboard():
            # Clear content
            for w in content_frame.winfo_children():
                w.destroy()

            sel_month = month_var.get()
            sel_loc = loc_var.get()

            workers = get_all_workers()
            profiles = get_profiles_dict()
            attendance = get_attendance(sel_month)

            if sel_loc != "All":
                rel = {pid for pid, p in profiles.items() if p.location == sel_loc}
                workers = [w for w in workers if w.profile_id in rel]

            results, warnings = calculate_payroll(workers, profiles, attendance,
                                                   sel_month)

            if warnings:
                warn_frame = ctk.CTkFrame(content_frame, fg_color="#3D2F00",
                                           corner_radius=8)
                warn_frame.pack(fill="x", pady=(0, 12))
                ctk.CTkLabel(
                    warn_frame,
                    text=f"  ⚠️  {len(warnings)} warning(s): {warnings[0]}"
                         + (" ..." if len(warnings) > 1 else ""),
                    font=FONT_SMALL, text_color=WARNING_CLR, anchor="w"
                ).pack(padx=12, pady=8)

            if not results:
                empty = ctk.CTkFrame(content_frame, fg_color=CARD_BG,
                                      corner_radius=12)
                empty.pack(fill="x", pady=40, padx=60)
                ctk.CTkLabel(
                    empty, text="📭", font=(FONT_FAMILY, 40)
                ).pack(pady=(30, 8))
                ctk.CTkLabel(
                    empty, text="No payroll data for this period",
                    font=FONT_HEADING, text_color=TEXT_SECONDARY
                ).pack()
                ctk.CTkLabel(
                    empty, text="Enter attendance data first to see results here.",
                    font=FONT_SMALL, text_color=TEXT_MUTED
                ).pack(pady=(4, 30))
                return

            # Metrics
            s = payroll_summary(results)
            metrics_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
            metrics_frame.pack(fill="x", pady=(0, 16))
            metrics_frame.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

            cards = [
                ("Workers", str(s["total_workers"]), ACCENT),
                ("Total Gross", fmt_inr(s["total_gross"]), "#26A69A"),
                ("Total EPF", fmt_inr(s["total_epf"]), WARNING_CLR),
                ("Total ESI", fmt_inr(s["total_esi"]), "#AB47BC"),
                ("Total Net Pay", fmt_inr(s["total_net"]), SUCCESS),
            ]
            for i, (lbl, val, clr) in enumerate(cards):
                mc = MetricCard(metrics_frame, lbl, val, color=clr)
                mc.grid(row=0, column=i, padx=4, pady=4, sticky="nsew")

            # Payroll table
            ctk.CTkLabel(
                content_frame, text="Payroll Breakdown",
                font=FONT_HEADING, text_color=TEXT_PRIMARY, anchor="w"
            ).pack(fill="x", pady=(8, 8))

            cols = ("Worker ID", "Name", "Profile", "Days",
                    "Gross (₹)", "EPF (₹)", "ESI (₹)",
                    "Total Ded.", "Net Pay (₹)")
            widths = [80, 140, 130, 50, 110, 90, 90, 100, 120]

            table = StyledTreeview(content_frame, columns=cols,
                                    column_widths=widths, height=min(len(results), 15))
            table.pack(fill="both", expand=True, pady=(0, 12))

            rows = []
            for r in results:
                rows.append((
                    r.worker_id, r.worker_name, r.profile_title,
                    r.days_present,
                    fmt_inr(r.gross), fmt_inr(r.epf_deduction),
                    fmt_inr(r.esi_deduction), fmt_inr(r.total_deductions),
                    fmt_inr(r.net_pay),
                ))
            table.insert_rows(rows)

            # Export CSV button
            def export_csv():
                import pandas as pd
                path = filedialog.asksaveasfilename(
                    defaultextension=".csv",
                    filetypes=[("CSV files", "*.csv")],
                    initialfile=f"Payroll_{sel_month}.csv"
                )
                if path:
                    df = pd.DataFrame([r.summary_row() for r in results])
                    df.to_csv(path, index=False)
                    self.status_bar.set_message(
                        f"✅ Exported CSV → {path}", SUCCESS)
                    messagebox.showinfo("Export Complete",
                                         f"CSV saved to:\n{path}")

            ctk.CTkButton(
                content_frame, text="⬇️  Export CSV", font=FONT_BODY_BOLD,
                fg_color=ACCENT, hover_color=ACCENT_HOVER,
                height=36, corner_radius=8, command=export_csv
            ).pack(anchor="w", pady=(0, 20))

        # Bind refresh on control change
        month_var.trace_add("write", lambda *_: refresh_dashboard())
        loc_var.trace_add("write", lambda *_: refresh_dashboard())

        # Refresh button
        ctk.CTkButton(
            ctrl, text="🔄 Refresh", font=FONT_BODY, width=100,
            fg_color=SURFACE_3, hover_color=SURFACE_2,
            text_color=TEXT_PRIMARY, height=32, corner_radius=8,
            command=refresh_dashboard
        ).pack(side="right")

        refresh_dashboard()

    # ══════════════════════════════════════════════════════════════════════
    #   PAGE: ATTENDANCE
    # ══════════════════════════════════════════════════════════════════════
    def _build_attendance(self, parent):
        ctk.CTkLabel(
            parent, text="📋  Attendance & Earnings Entry",
            font=FONT_TITLE, text_color=TEXT_PRIMARY, anchor="w"
        ).pack(fill="x", padx=28, pady=(20, 4))
        ctk.CTkLabel(
            parent, text="Enter daily attendance and manage per-worker allowances and deductions",
            font=FONT_SMALL, text_color=TEXT_SECONDARY, anchor="w"
        ).pack(fill="x", padx=28, pady=(0, 16))

        # Tabs
        tabview = ctk.CTkTabview(
            parent, fg_color=SURFACE_2, segmented_button_fg_color=SURFACE_3,
            segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color=ACCENT_HOVER,
            segmented_button_unselected_color=SURFACE_3,
            segmented_button_unselected_hover_color=SIDEBAR_HOVER,
            corner_radius=10
        )
        tabview.pack(fill="both", expand=True, padx=28, pady=(0, 20))

        tab_manual = tabview.add("✏️ Manual Entry")
        tab_csv = tabview.add("📥 CSV Import")

        self._build_attendance_manual(tab_manual)
        self._build_attendance_csv(tab_csv)

    def _build_attendance_manual(self, parent):
        opts = month_options()
        config = get_config()

        # Controls
        ctrl = ctk.CTkFrame(parent, fg_color="transparent")
        ctrl.pack(fill="x", padx=12, pady=(12, 8))

        ctk.CTkLabel(ctrl, text="Month:", font=FONT_BODY_BOLD,
                      text_color=TEXT_PRIMARY).pack(side="left")
        month_var = ctk.StringVar(value=opts[-1])
        ctk.CTkOptionMenu(
            ctrl, values=opts, variable=month_var, width=140,
            font=FONT_BODY, fg_color=SURFACE_3, button_color=ACCENT,
            button_hover_color=ACCENT_HOVER
        ).pack(side="left", padx=(8, 20))

        ctk.CTkLabel(
            ctrl, text=f"(Max working days: {config.working_days})",
            font=FONT_SMALL, text_color=TEXT_MUTED
        ).pack(side="left")

        # Container for the table
        table_frame = ctk.CTkFrame(parent, fg_color="transparent")
        table_frame.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        # Store entry widgets keyed by worker_id
        self._att_entries = {}

        def refresh_att_table():
            for w in table_frame.winfo_children():
                w.destroy()
            self._att_entries.clear()

            sel_month = month_var.get()
            workers = get_all_workers()
            profiles = get_profiles_dict()
            existing = {a.worker_id: a for a in get_attendance(sel_month)}

            ctk.CTkLabel(
                table_frame, text="Step 1 — Days Present & OT Wages",
                font=FONT_SUBHEADING, text_color=TEXT_PRIMARY, anchor="w"
            ).pack(fill="x", pady=(4, 8))

            # Header
            hdr = ctk.CTkFrame(table_frame, fg_color=ACCENT_DARK,
                                corner_radius=6)
            hdr.pack(fill="x", pady=(0, 2))
            headers = ["Worker ID", "Name", "Profile", "Days Present", "OT Wages (₹)"]
            hdr_widths = [0.12, 0.25, 0.23, 0.20, 0.20]
            for txt, w in zip(headers, hdr_widths):
                ctk.CTkLabel(
                    hdr, text=txt, font=FONT_BODY_BOLD,
                    text_color="white", anchor="w"
                ).pack(side="left", padx=8, pady=6, expand=True, fill="x")

            if not workers:
                ctk.CTkLabel(
                    table_frame, text="No workers found. Add workers first.",
                    font=FONT_BODY, text_color=TEXT_MUTED
                ).pack(pady=20)
                return

            # Rows
            for i, w in enumerate(workers):
                att = existing.get(w.worker_id,
                                   AttendanceRecord(w.worker_id, sel_month))
                p = profiles.get(w.profile_id)

                bg = SURFACE_2 if i % 2 == 0 else SURFACE_3
                row = ctk.CTkFrame(table_frame, fg_color=bg, corner_radius=4)
                row.pack(fill="x", pady=1)

                ctk.CTkLabel(
                    row, text=w.worker_id, font=FONT_SMALL,
                    text_color=TEXT_PRIMARY, anchor="w", width=90
                ).pack(side="left", padx=8, pady=5)

                ctk.CTkLabel(
                    row, text=w.name, font=FONT_SMALL,
                    text_color=TEXT_PRIMARY, anchor="w", width=160
                ).pack(side="left", padx=8, pady=5)

                ctk.CTkLabel(
                    row, text=(p.title if p else w.profile_id),
                    font=FONT_SMALL, text_color=TEXT_SECONDARY,
                    anchor="w", width=150
                ).pack(side="left", padx=8, pady=5)

                days_var = ctk.StringVar(value=str(att.days_present))
                days_entry = ctk.CTkEntry(
                    row, textvariable=days_var, width=80, height=26,
                    font=FONT_SMALL, fg_color=SURFACE,
                    border_color=TEXT_MUTED, corner_radius=4
                )
                days_entry.pack(side="left", padx=8, pady=5)

                ot_var = ctk.StringVar(value=str(att.overtime_wages))
                ot_entry = ctk.CTkEntry(
                    row, textvariable=ot_var, width=100, height=26,
                    font=FONT_SMALL, fg_color=SURFACE,
                    border_color=TEXT_MUTED, corner_radius=4
                )
                ot_entry.pack(side="left", padx=8, pady=5)

                self._att_entries[w.worker_id] = {
                    "days": days_var,
                    "ot": ot_var,
                    "existing": att,
                }

            # Detailed allowances/deductions section
            ctk.CTkLabel(
                table_frame,
                text="\nStep 2 — Detailed Allowances & Deductions (expand per worker)",
                font=FONT_SUBHEADING, text_color=TEXT_PRIMARY, anchor="w"
            ).pack(fill="x", pady=(12, 8))

            ctk.CTkLabel(
                table_frame,
                text="Click 'Edit Details' next to a worker to set DA, HRA, Bonus, etc.",
                font=FONT_SMALL, text_color=TEXT_MUTED, anchor="w"
            ).pack(fill="x", pady=(0, 8))

            for w in workers:
                att = existing.get(w.worker_id,
                                   AttendanceRecord(w.worker_id, sel_month))
                detail_frame = ctk.CTkFrame(table_frame, fg_color=CARD_BG,
                                             corner_radius=8)
                detail_frame.pack(fill="x", pady=3)

                header_row = ctk.CTkFrame(detail_frame, fg_color="transparent")
                header_row.pack(fill="x", padx=10, pady=(6, 0))

                ctk.CTkLabel(
                    header_row,
                    text=f"{w.worker_id} — {w.name}",
                    font=FONT_BODY_BOLD, text_color=TEXT_PRIMARY
                ).pack(side="left")

                # Collapsible details
                details = ctk.CTkFrame(detail_frame, fg_color="transparent")
                details.pack_forget()

                def make_toggle(d=details, h=header_row):
                    toggle_btn = ctk.CTkButton(
                        h, text="▶ Edit Details", font=FONT_SMALL,
                        width=100, height=26, corner_radius=6,
                        fg_color=SURFACE_3, hover_color=SURFACE_2,
                        text_color=TEXT_SECONDARY
                    )
                    toggle_btn.pack(side="right")
                    shown = [False]

                    def toggle():
                        if shown[0]:
                            d.pack_forget()
                            toggle_btn.configure(text="▶ Edit Details")
                            shown[0] = False
                        else:
                            d.pack(fill="x", padx=10, pady=(6, 10))
                            toggle_btn.configure(text="▼ Hide Details")
                            shown[0] = True
                    toggle_btn.configure(command=toggle)

                make_toggle()

                # Build the detail fields
                self._build_detail_fields(details, w.worker_id, att)

            # Save All button
            def save_all_attendance():
                sel_month = month_var.get()
                records = []
                workers = get_all_workers()
                existing = {a.worker_id: a for a in get_attendance(sel_month)}

                for w in workers:
                    if w.worker_id not in self._att_entries:
                        continue
                    entry = self._att_entries[w.worker_id]
                    att = entry.get("detail_att",
                                    existing.get(w.worker_id,
                                    AttendanceRecord(w.worker_id, sel_month)))

                    try:
                        days = float(entry["days"].get() or 0)
                        ot = float(entry["ot"].get() or 0)
                    except ValueError:
                        days, ot = 0.0, 0.0

                    att.month = sel_month
                    att.days_present = days
                    att.overtime_wages = ot
                    records.append(att)

                bulk_upsert_attendance(records)
                self.status_bar.set_message(
                    f"✅ Saved {len(records)} attendance records for {sel_month}",
                    SUCCESS
                )
                messagebox.showinfo("Success",
                    f"Saved {len(records)} records for {sel_month}.")

            ctk.CTkButton(
                table_frame, text="💾  Save All Attendance",
                font=FONT_BODY_BOLD, fg_color=SUCCESS,
                hover_color="#2E7D32", height=40, corner_radius=8,
                command=save_all_attendance
            ).pack(fill="x", pady=(16, 20))

        month_var.trace_add("write", lambda *_: refresh_att_table())
        refresh_att_table()

    def _build_detail_fields(self, parent, worker_id, att):
        """Build the allowances/deductions input fields for one worker."""
        fields = [
            ("DA (₹)", "da"), ("HRA (₹)", "hra"), ("CCA (₹)", "cca"),
            ("Arrears (₹)", "arrears"), ("N&FH Wages (₹)", "nfh_wages"),
            ("Leave Wages (₹)", "leave_wages"),
            ("Bonus (₹)", "bonus"),
            ("Maternity Benefit (₹)", "maternity_benefit"),
            ("Advance Pay (₹)", "advances_pay"),
            ("Other Allowances (₹)", "other_allowances"),
            ("EPF Override (0=auto)", "epf_override"),
            ("ESI Override (0=auto)", "esi_override"),
            ("Welfare Fund (₹)", "welfare_fund"),
            ("TDS (₹)", "tds"),
            ("Profession Tax (₹)", "profession_tax"),
            ("Advance Repayment (₹)", "advance_repayment"),
            ("Fine (₹)", "fine"),
            ("Loss & Damages (₹)", "loss_damages"),
            ("Other Deductions (₹)", "other_deductions"),
        ]

        vars_dict = {}
        cols_per_row = 3
        for i, (label, attr) in enumerate(fields):
            row_idx, col_idx = divmod(i, cols_per_row)

            if col_idx == 0:
                row_frame = ctk.CTkFrame(parent, fg_color="transparent")
                row_frame.pack(fill="x", pady=2)

            field = ctk.CTkFrame(row_frame, fg_color="transparent")
            field.pack(side="left", expand=True, fill="x", padx=4)

            ctk.CTkLabel(
                field, text=label, font=FONT_TINY,
                text_color=TEXT_SECONDARY, anchor="w"
            ).pack(anchor="w")

            var = ctk.StringVar(value=str(getattr(att, attr, 0.0)))
            ctk.CTkEntry(
                field, textvariable=var, width=120, height=26,
                font=FONT_SMALL, fg_color=SURFACE,
                border_color=TEXT_MUTED, corner_radius=4
            ).pack(anchor="w")
            vars_dict[attr] = var

        # Store a way to build the AttendanceRecord from these vars
        def build_record():
            kwargs = {"worker_id": worker_id, "month": att.month}
            for _, attr in fields:
                try:
                    kwargs[attr] = float(vars_dict[attr].get() or 0)
                except ValueError:
                    kwargs[attr] = 0.0
            return AttendanceRecord(**kwargs)

        # Save reference for the save function
        if worker_id in self._att_entries:
            self._att_entries[worker_id]["detail_att_builder"] = build_record

        # Override the att in entries so save picks up detail fields
        def update_detail_att(*_):
            if worker_id in self._att_entries:
                self._att_entries[worker_id]["detail_att"] = build_record()

        for _, attr in fields:
            vars_dict[attr].trace_add("write", update_detail_att)

        update_detail_att()

    def _build_attendance_csv(self, parent):
        ctk.CTkLabel(
            parent,
            text="Upload a CSV file to import attendance data in bulk.",
            font=FONT_BODY, text_color=TEXT_SECONDARY, anchor="w"
        ).pack(padx=16, pady=(16, 8))

        info = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=8)
        info.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(
            info, text="Supported columns:", font=FONT_BODY_BOLD,
            text_color=TEXT_PRIMARY, anchor="w"
        ).pack(padx=12, pady=(10, 4), anchor="w")
        ctk.CTkLabel(
            info,
            text="worker_id, days_present, basic_wages, da, hra, cca,\n"
                 "overtime_wages, arrears, advances_pay, nfh_wages,\n"
                 "maternity_benefit, leave_wages, bonus, other_allowances,\n"
                 "epf_override, esi_override, welfare_fund, tds,\n"
                 "profession_tax, advance_repayment, fine, loss_damages,\n"
                 "other_deductions",
            font=FONT_TINY, text_color=TEXT_MUTED, anchor="w", justify="left"
        ).pack(padx=12, pady=(0, 10), anchor="w")

        # Download template
        def download_template():
            workers = get_all_workers()
            tpl_cols = ["worker_id", "days_present", "basic_wages", "da",
                        "hra", "cca", "overtime_wages", "bonus",
                        "advance_repayment"]
            path = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV files", "*.csv")],
                initialfile="attendance_template.csv"
            )
            if path:
                with open(path, "w", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(tpl_cols)
                    for w in workers:
                        writer.writerow(
                            [w.worker_id] + [0] * (len(tpl_cols) - 1))
                self.status_bar.set_message(f"✅ Template saved → {path}",
                                             SUCCESS)

        ctk.CTkButton(
            parent, text="⬇️  Download Template CSV", font=FONT_BODY,
            fg_color=SURFACE_3, hover_color=SURFACE_2,
            text_color=TEXT_PRIMARY, height=34, corner_radius=8,
            command=download_template
        ).pack(padx=16, anchor="w", pady=(0, 16))

        ctk.CTkFrame(parent, height=1, fg_color=TEXT_MUTED).pack(
            fill="x", padx=16, pady=(0, 12))

        # Import controls
        opts = month_options()
        ctrl = ctk.CTkFrame(parent, fg_color="transparent")
        ctrl.pack(fill="x", padx=16, pady=(0, 8))

        ctk.CTkLabel(ctrl, text="Import for Month:",
                      font=FONT_BODY_BOLD,
                      text_color=TEXT_PRIMARY).pack(side="left")
        imp_month_var = ctk.StringVar(value=opts[-1])
        ctk.CTkOptionMenu(
            ctrl, values=opts, variable=imp_month_var, width=140,
            font=FONT_BODY, fg_color=SURFACE_3, button_color=ACCENT,
            button_hover_color=ACCENT_HOVER
        ).pack(side="left", padx=(8, 0))

        def import_csv():
            filepath = filedialog.askopenfilename(
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
            )
            if not filepath:
                return
            month = imp_month_var.get()
            res = import_attendance_from_csv(filepath, month)
            msg = f"✅ Imported {res['imported']} records for {month}."
            self.status_bar.set_message(msg, SUCCESS)
            if res["errors"]:
                messagebox.showwarning(
                    "Import Warnings",
                    f"Imported {res['imported']} records.\n\nErrors:\n"
                    + "\n".join(res["errors"][:10])
                )
            else:
                messagebox.showinfo("Import Complete", msg)

        ctk.CTkButton(
            parent, text="📥  Import CSV", font=FONT_BODY_BOLD,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            height=38, corner_radius=8, command=import_csv
        ).pack(padx=16, anchor="w", pady=(12, 20))

    # ══════════════════════════════════════════════════════════════════════
    #   PAGE: WORKERS
    # ══════════════════════════════════════════════════════════════════════
    def _build_workers(self, parent):
        ctk.CTkLabel(
            parent, text="👷  Worker Master Data",
            font=FONT_TITLE, text_color=TEXT_PRIMARY, anchor="w"
        ).pack(fill="x", padx=28, pady=(20, 4))
        ctk.CTkLabel(
            parent, text="Manage all worker registrations, bank details, and status",
            font=FONT_SMALL, text_color=TEXT_SECONDARY, anchor="w"
        ).pack(fill="x", padx=28, pady=(0, 16))

        tabview = ctk.CTkTabview(
            parent, fg_color=SURFACE_2,
            segmented_button_fg_color=SURFACE_3,
            segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color=ACCENT_HOVER,
            segmented_button_unselected_color=SURFACE_3,
            segmented_button_unselected_hover_color=SIDEBAR_HOVER,
            corner_radius=10
        )
        tabview.pack(fill="both", expand=True, padx=28, pady=(0, 20))

        tab_all = tabview.add("👥 All Workers")
        tab_add = tabview.add("➕ Add / Edit")

        # ─ All Workers tab ─
        def refresh_workers():
            for w in tab_all.winfo_children():
                w.destroy()

            workers = get_all_workers(active_only=False)
            profiles = get_profiles_dict()

            cols = ("ID", "Name", "Profile", "Bank", "A/C",
                    "IFSC", "UAN", "ESIC", "Status")
            widths = [60, 140, 130, 100, 120, 100, 110, 90, 60]

            table = StyledTreeview(tab_all, columns=cols,
                                    column_widths=widths, height=12)
            table.pack(fill="both", expand=True, padx=8, pady=(8, 8))

            rows = []
            for w in workers:
                pname = (profiles[w.profile_id].title
                         if w.profile_id in profiles else w.profile_id)
                rows.append((
                    w.worker_id, w.name, pname,
                    w.bank_name, w.bank_account, w.ifsc_code,
                    w.uan_number, w.esic_number,
                    "✅ Active" if w.active else "❌ Inactive"
                ))
            table.insert_rows(rows)

            # Deactivate control
            ctrl = ctk.CTkFrame(tab_all, fg_color="transparent")
            ctrl.pack(fill="x", padx=8, pady=(4, 12))

            active_ids = [w.worker_id for w in workers if w.active]
            if active_ids:
                ctk.CTkLabel(ctrl, text="Deactivate Worker:",
                              font=FONT_BODY_BOLD,
                              text_color=TEXT_PRIMARY).pack(side="left")
                deact_var = ctk.StringVar(value=active_ids[0])
                ctk.CTkOptionMenu(
                    ctrl, values=active_ids, variable=deact_var,
                    width=120, font=FONT_BODY, fg_color=SURFACE_3,
                    button_color=DANGER, button_hover_color="#C62828"
                ).pack(side="left", padx=8)

                def do_deactivate():
                    wid = deact_var.get()
                    if messagebox.askyesno(
                        "Confirm",
                        f"Deactivate worker '{wid}'?"
                    ):
                        deactivate_worker(wid)
                        self.status_bar.set_message(
                            f"Worker {wid} deactivated.", WARNING_CLR)
                        refresh_workers()

                ctk.CTkButton(
                    ctrl, text="❌ Deactivate", font=FONT_BODY,
                    fg_color=DANGER, hover_color="#C62828",
                    height=32, corner_radius=6, command=do_deactivate
                ).pack(side="left", padx=4)

        refresh_workers()

        # ─ Add / Edit tab ─
        profiles = get_all_profiles()
        pmap = {p.profile_id: f"{p.title} ({p.location})" for p in profiles}

        form = ctk.CTkFrame(tab_add, fg_color=CARD_BG, corner_radius=10)
        form.pack(fill="x", padx=16, pady=16)

        ctk.CTkLabel(
            form, text="Worker Registration Form",
            font=FONT_HEADING, text_color=TEXT_PRIMARY
        ).pack(padx=16, pady=(16, 12))

        # Fields
        fields_frame = ctk.CTkFrame(form, fg_color="transparent")
        fields_frame.pack(fill="x", padx=16, pady=(0, 12))

        def make_field(parent, label, row, col, default="", width=200):
            f = ctk.CTkFrame(parent, fg_color="transparent")
            f.grid(row=row, column=col, padx=8, pady=4, sticky="ew")
            ctk.CTkLabel(f, text=label, font=FONT_SMALL,
                          text_color=TEXT_SECONDARY).pack(anchor="w")
            var = ctk.StringVar(value=default)
            ctk.CTkEntry(
                f, textvariable=var, height=30, font=FONT_BODY,
                fg_color=SURFACE, border_color=TEXT_MUTED, corner_radius=6,
                width=width
            ).pack(fill="x")
            return var

        fields_frame.grid_columnconfigure((0, 1, 2), weight=1)

        wid_var = make_field(fields_frame, "Worker ID *", 0, 0,
                              placeholder := "")
        wname_var = make_field(fields_frame, "Full Name *", 0, 1)

        # Profile dropdown
        pf = ctk.CTkFrame(fields_frame, fg_color="transparent")
        pf.grid(row=0, column=2, padx=8, pady=4, sticky="ew")
        ctk.CTkLabel(pf, text="Job Profile *", font=FONT_SMALL,
                      text_color=TEXT_SECONDARY).pack(anchor="w")
        prof_ids = list(pmap.keys()) if pmap else ["(none)"]
        prof_var = ctk.StringVar(value=prof_ids[0] if prof_ids else "")
        ctk.CTkOptionMenu(
            pf, values=prof_ids, variable=prof_var,
            font=FONT_BODY, fg_color=SURFACE, button_color=ACCENT,
            button_hover_color=ACCENT_HOVER, height=30
        ).pack(fill="x")

        wbank_var = make_field(fields_frame, "Bank Account No.", 1, 0)
        wbname_var = make_field(fields_frame, "Bank Name", 1, 1)
        wifsc_var = make_field(fields_frame, "IFSC Code", 1, 2)
        wuan_var = make_field(fields_frame, "UAN Number (PF)", 2, 0)
        wesic_var = make_field(fields_frame, "ESIC IP Number", 2, 1)
        wjoin_var = make_field(fields_frame, "Joining Date (YYYY-MM-DD)",
                                2, 2,
                                default=str(datetime.date.today()))

        def save_worker():
            wid = wid_var.get().strip().upper()
            wname = wname_var.get().strip()
            if not wid or not wname:
                messagebox.showerror("Validation Error",
                                      "Worker ID and Name are required.")
                return

            upsert_worker(Worker(
                wid, wname, prof_var.get(),
                wbank_var.get().strip(), wbname_var.get().strip(),
                wifsc_var.get().strip(), wuan_var.get().strip(),
                wesic_var.get().strip(), wjoin_var.get().strip(), True
            ))
            self.status_bar.set_message(f"✅ Worker {wid} saved!", SUCCESS)
            messagebox.showinfo("Success", f"Worker {wid} saved!")
            refresh_workers()

        ctk.CTkButton(
            form, text="💾  Save Worker", font=FONT_BODY_BOLD,
            fg_color=SUCCESS, hover_color="#2E7D32",
            height=40, corner_radius=8, command=save_worker
        ).pack(pady=(4, 16))

    # ══════════════════════════════════════════════════════════════════════
    #   PAGE: JOB PROFILES
    # ══════════════════════════════════════════════════════════════════════
    def _build_profiles(self, parent):
        ctk.CTkLabel(
            parent, text="🏷️  Job Profile Master",
            font=FONT_TITLE, text_color=TEXT_PRIMARY, anchor="w"
        ).pack(fill="x", padx=28, pady=(20, 4))
        ctk.CTkLabel(
            parent, text="Define job roles, daily wages, and overtime rates",
            font=FONT_SMALL, text_color=TEXT_SECONDARY, anchor="w"
        ).pack(fill="x", padx=28, pady=(0, 16))

        tabview = ctk.CTkTabview(
            parent, fg_color=SURFACE_2,
            segmented_button_fg_color=SURFACE_3,
            segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color=ACCENT_HOVER,
            segmented_button_unselected_color=SURFACE_3,
            segmented_button_unselected_hover_color=SIDEBAR_HOVER,
            corner_radius=10
        )
        tabview.pack(fill="both", expand=True, padx=28, pady=(0, 20))

        tab_all = tabview.add("📋 All Profiles")
        tab_add = tabview.add("➕ Add / Edit")

        # ─ All profiles ─
        def refresh_profiles():
            for w in tab_all.winfo_children():
                w.destroy()

            profiles = get_all_profiles()
            cols = ("Profile ID", "Title", "Daily Wage (₹)",
                    "OT Rate (₹/hr)", "Location")
            widths = [120, 180, 120, 120, 160]
            table = StyledTreeview(tab_all, columns=cols,
                                    column_widths=widths, height=8)
            table.pack(fill="both", expand=True, padx=8, pady=(8, 8))

            rows = [(p.profile_id, p.title, fmt_inr(p.daily_wage),
                     fmt_inr(p.ot_rate), p.location)
                    for p in profiles]
            table.insert_rows(rows)

            # Delete control
            ctrl = ctk.CTkFrame(tab_all, fg_color="transparent")
            ctrl.pack(fill="x", padx=8, pady=(4, 12))

            pids = [p.profile_id for p in profiles]
            if pids:
                ctk.CTkLabel(ctrl, text="Delete Profile:",
                              font=FONT_BODY_BOLD,
                              text_color=TEXT_PRIMARY).pack(side="left")
                del_var = ctk.StringVar(value=pids[0])
                ctk.CTkOptionMenu(
                    ctrl, values=pids, variable=del_var, width=140,
                    font=FONT_BODY, fg_color=SURFACE_3,
                    button_color=DANGER, button_hover_color="#C62828"
                ).pack(side="left", padx=8)

                def do_delete():
                    pid = del_var.get()
                    if messagebox.askyesno("Confirm",
                                            f"Delete profile '{pid}'?"):
                        delete_profile(pid)
                        self.status_bar.set_message(
                            f"Profile '{pid}' deleted.", WARNING_CLR)
                        refresh_profiles()

                ctk.CTkButton(
                    ctrl, text="🗑️ Delete", font=FONT_BODY,
                    fg_color=DANGER, hover_color="#C62828",
                    height=32, corner_radius=6, command=do_delete
                ).pack(side="left", padx=4)

        refresh_profiles()

        # ─ Add / Edit ─
        form = ctk.CTkFrame(tab_add, fg_color=CARD_BG, corner_radius=10)
        form.pack(fill="x", padx=16, pady=16)

        ctk.CTkLabel(
            form, text="Profile Registration Form",
            font=FONT_HEADING, text_color=TEXT_PRIMARY
        ).pack(padx=16, pady=(16, 12))

        ff = ctk.CTkFrame(form, fg_color="transparent")
        ff.pack(fill="x", padx=16, pady=(0, 12))
        ff.grid_columnconfigure((0, 1), weight=1)

        def pfield(parent, label, row, col, default=""):
            f = ctk.CTkFrame(parent, fg_color="transparent")
            f.grid(row=row, column=col, padx=8, pady=4, sticky="ew")
            ctk.CTkLabel(f, text=label, font=FONT_SMALL,
                          text_color=TEXT_SECONDARY).pack(anchor="w")
            var = ctk.StringVar(value=default)
            ctk.CTkEntry(
                f, textvariable=var, height=30, font=FONT_BODY,
                fg_color=SURFACE, border_color=TEXT_MUTED, corner_radius=6
            ).pack(fill="x")
            return var

        pid_var = pfield(ff, "Profile ID *", 0, 0)
        ptit_var = pfield(ff, "Title *", 0, 1)
        pdw_var = pfield(ff, "Daily Wage (₹) *", 1, 0, "494.0")
        pot_var = pfield(ff, "OT Rate (₹/hr) *", 1, 1, "65.0")
        ploc_var = pfield(ff, "Location / Site *", 2, 0, "Head Office")

        def save_profile():
            pid = pid_var.get().strip().lower()
            ptit = ptit_var.get().strip()
            if not pid or not ptit:
                messagebox.showerror("Validation",
                                      "Profile ID and Title are required.")
                return
            if " " in pid:
                messagebox.showerror("Validation",
                                      "No spaces in Profile ID.")
                return
            try:
                dw = float(pdw_var.get())
                ot = float(pot_var.get())
            except ValueError:
                messagebox.showerror("Validation",
                                      "Wage/Rate must be numbers.")
                return

            upsert_profile(MasterProfile(pid, ptit, dw, ot,
                                          ploc_var.get().strip()))
            self.status_bar.set_message(f"✅ Profile '{pid}' saved!", SUCCESS)
            messagebox.showinfo("Success", f"Profile '{pid}' saved!")
            refresh_profiles()

        ctk.CTkButton(
            form, text="💾  Save Profile", font=FONT_BODY_BOLD,
            fg_color=SUCCESS, hover_color="#2E7D32",
            height=40, corner_radius=8, command=save_profile
        ).pack(pady=(4, 16))

    # ══════════════════════════════════════════════════════════════════════
    #   PAGE: GENERATE SLIPS
    # ══════════════════════════════════════════════════════════════════════
    def _build_slips(self, parent):
        ctk.CTkLabel(
            parent, text="📄  Generate Salary Slips",
            font=FONT_TITLE, text_color=TEXT_PRIMARY, anchor="w"
        ).pack(fill="x", padx=28, pady=(20, 4))
        ctk.CTkLabel(
            parent, text="Generate PDF salary slips for all or individual workers",
            font=FONT_SMALL, text_color=TEXT_SECONDARY, anchor="w"
        ).pack(fill="x", padx=28, pady=(0, 16))

        config = get_config()
        opts = month_options()

        # Controls
        ctrl = ctk.CTkFrame(parent, fg_color="transparent")
        ctrl.pack(fill="x", padx=28, pady=(0, 12))

        ctk.CTkLabel(ctrl, text="Month:", font=FONT_BODY_BOLD,
                      text_color=TEXT_PRIMARY).pack(side="left")
        month_var = ctk.StringVar(value=opts[-1])
        ctk.CTkOptionMenu(
            ctrl, values=opts, variable=month_var, width=140,
            font=FONT_BODY, fg_color=SURFACE_3, button_color=ACCENT,
            button_hover_color=ACCENT_HOVER
        ).pack(side="left", padx=(8, 20))

        profiles = get_profiles_dict()
        locs = sorted({p.location for p in profiles.values()})
        ctk.CTkLabel(ctrl, text="Location:", font=FONT_BODY_BOLD,
                      text_color=TEXT_PRIMARY).pack(side="left")
        loc_var = ctk.StringVar(value="All")
        ctk.CTkOptionMenu(
            ctrl, values=["All"] + locs, variable=loc_var, width=160,
            font=FONT_BODY, fg_color=SURFACE_3, button_color=ACCENT,
            button_hover_color=ACCENT_HOVER
        ).pack(side="left", padx=(8, 0))

        content = ctk.CTkFrame(parent, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=28, pady=(0, 20))

        def refresh_slips():
            for w in content.winfo_children():
                w.destroy()

            sel_month = month_var.get()
            sel_loc = loc_var.get()

            workers = get_all_workers()
            profs = get_profiles_dict()
            attendance = get_attendance(sel_month)

            if sel_loc != "All":
                rel = {pid for pid, p in profs.items()
                       if p.location == sel_loc}
                workers = [w for w in workers if w.profile_id in rel]

            results, warnings = calculate_payroll(
                workers, profs, attendance, sel_month)

            if warnings:
                wf = ctk.CTkFrame(content, fg_color="#3D2F00",
                                   corner_radius=8)
                wf.pack(fill="x", pady=(0, 8))
                ctk.CTkLabel(
                    wf,
                    text=f"  ⚠️  {len(warnings)} warning(s)",
                    font=FONT_SMALL, text_color=WARNING_CLR
                ).pack(padx=12, pady=6)

            if not results:
                ef = ctk.CTkFrame(content, fg_color=CARD_BG,
                                   corner_radius=12)
                ef.pack(fill="x", pady=30, padx=40)
                ctk.CTkLabel(ef, text="📭", font=(FONT_FAMILY, 36)).pack(
                    pady=(20, 6))
                ctk.CTkLabel(
                    ef, text="No payroll data available.",
                    font=FONT_HEADING, text_color=TEXT_SECONDARY
                ).pack(pady=(0, 20))
                return

            ctk.CTkLabel(
                content, text=f"Ready: {len(results)} slip(s)",
                font=FONT_HEADING, text_color=TEXT_PRIMARY, anchor="w"
            ).pack(fill="x", pady=(0, 8))

            # Summary table
            cols = ("Worker ID", "Name", "Profile", "Net Pay (₹)")
            widths = [100, 180, 160, 140]
            table = StyledTreeview(content, columns=cols,
                                    column_widths=widths,
                                    height=min(len(results), 10))
            table.pack(fill="both", expand=True, pady=(0, 12))

            rows = [(r.worker_id, r.worker_name, r.profile_title,
                     fmt_inr(r.net_pay)) for r in results]
            table.insert_rows(rows)

            # Action buttons
            btn_frame = ctk.CTkFrame(content, fg_color="transparent")
            btn_frame.pack(fill="x", pady=(8, 4))

            def gen_all_zip():
                out_dir = filedialog.askdirectory(
                    title="Select output folder")
                if not out_dir:
                    return
                self.status_bar.set_message("⏳ Generating PDFs...",
                                             ACCENT)
                self.update()

                # Run in thread to keep UI responsive
                def do_gen():
                    cfg = get_config()
                    gen = generate_bulk_pdfs(results, cfg, out_dir,
                                             zip_output=True)
                    self.after(0, lambda: _on_gen_done(gen, out_dir))

                def _on_gen_done(gen, out_dir):
                    for e in gen["errors"]:
                        messagebox.showerror("Error", e)
                    msg = (f"✅ {gen['success_count']} slips generated "
                           f"→ {out_dir}")
                    self.status_bar.set_message(msg, SUCCESS)
                    messagebox.showinfo("Generation Complete",
                        f"{gen['success_count']} salary slips generated.\n\n"
                        f"Output: {out_dir}\n"
                        + (f"ZIP: {gen['zip_path']}" if gen['zip_path']
                           else ""))
                    # Open folder
                    try:
                        os.startfile(out_dir)
                    except Exception:
                        pass

                threading.Thread(target=do_gen, daemon=True).start()

            ctk.CTkButton(
                btn_frame, text="📦  Generate ALL as ZIP",
                font=FONT_BODY_BOLD, fg_color=ACCENT,
                hover_color=ACCENT_HOVER,
                height=42, corner_radius=8, command=gen_all_zip
            ).pack(side="left", padx=(0, 12))

            # Single slip
            single_frame = ctk.CTkFrame(content, fg_color=CARD_BG,
                                          corner_radius=10)
            single_frame.pack(fill="x", pady=(12, 4))

            ctk.CTkLabel(
                single_frame, text="Generate Single Slip",
                font=FONT_SUBHEADING, text_color=TEXT_PRIMARY
            ).pack(padx=12, pady=(12, 4), anchor="w")

            sf_ctrl = ctk.CTkFrame(single_frame, fg_color="transparent")
            sf_ctrl.pack(fill="x", padx=12, pady=(0, 12))

            names = {r.worker_id: r.worker_name for r in results}
            name_list = [f"{k} — {v}" for k, v in names.items()]
            sel_worker_var = ctk.StringVar(
                value=name_list[0] if name_list else "")
            ctk.CTkOptionMenu(
                sf_ctrl, values=name_list, variable=sel_worker_var,
                width=260, font=FONT_BODY, fg_color=SURFACE,
                button_color=ACCENT, button_hover_color=ACCENT_HOVER
            ).pack(side="left", padx=(0, 12))

            def gen_single():
                sel = sel_worker_var.get()
                wid = sel.split(" — ")[0] if " — " in sel else sel
                target = next(
                    (r for r in results if r.worker_id == wid), None)
                if not target:
                    return
                out_dir = filedialog.askdirectory(
                    title="Select output folder")
                if not out_dir:
                    return
                cfg = get_config()
                path = generate_slip_pdf(target, cfg, out_dir)
                self.status_bar.set_message(
                    f"✅ Slip generated → {path}", SUCCESS)
                messagebox.showinfo("Done", f"Slip saved:\n{path}")
                try:
                    os.startfile(path)
                except Exception:
                    pass

            ctk.CTkButton(
                sf_ctrl, text="👁️  Generate & Open",
                font=FONT_BODY_BOLD, fg_color=SUCCESS,
                hover_color="#2E7D32",
                height=36, corner_radius=8, command=gen_single
            ).pack(side="left")

        month_var.trace_add("write", lambda *_: refresh_slips())
        loc_var.trace_add("write", lambda *_: refresh_slips())
        refresh_slips()

    # ══════════════════════════════════════════════════════════════════════
    #   PAGE: SETTINGS
    # ══════════════════════════════════════════════════════════════════════
    def _build_settings(self, parent):
        ctk.CTkLabel(
            parent, text="⚙️  Company Settings",
            font=FONT_TITLE, text_color=TEXT_PRIMARY, anchor="w"
        ).pack(fill="x", padx=28, pady=(20, 4))
        ctk.CTkLabel(
            parent, text="Configure company information displayed on salary slips",
            font=FONT_SMALL, text_color=TEXT_SECONDARY, anchor="w"
        ).pack(fill="x", padx=28, pady=(0, 16))

        cfg = get_config()

        form = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=12)
        form.pack(fill="x", padx=28, pady=(0, 20))

        ctk.CTkLabel(
            form, text="Company Information",
            font=FONT_HEADING, text_color=TEXT_PRIMARY
        ).pack(padx=20, pady=(20, 16), anchor="w")

        ff = ctk.CTkFrame(form, fg_color="transparent")
        ff.pack(fill="x", padx=20, pady=(0, 16))

        def sfield(parent, label, default="", row=0):
            f = ctk.CTkFrame(parent, fg_color="transparent")
            f.pack(fill="x", pady=4)
            ctk.CTkLabel(f, text=label, font=FONT_SMALL,
                          text_color=TEXT_SECONDARY, width=180,
                          anchor="w").pack(side="left")
            var = ctk.StringVar(value=default)
            ctk.CTkEntry(
                f, textvariable=var, height=32, font=FONT_BODY,
                fg_color=SURFACE, border_color=TEXT_MUTED, corner_radius=6
            ).pack(side="left", fill="x", expand=True, padx=(8, 0))
            return var

        cname_var = sfield(ff, "Company Name", cfg.company_name)
        caddr1_var = sfield(ff, "Address Line 1", cfg.address_line1)
        caddr2_var = sfield(ff, "Address Line 2", cfg.address_line2)
        cphone_var = sfield(ff, "Phone", cfg.phone)
        cemail_var = sfield(ff, "Email", cfg.email)

        # Working days with spinner
        wdf = ctk.CTkFrame(ff, fg_color="transparent")
        wdf.pack(fill="x", pady=4)
        ctk.CTkLabel(wdf, text="Standard Working Days", font=FONT_SMALL,
                      text_color=TEXT_SECONDARY, width=180,
                      anchor="w").pack(side="left")
        wdays_var = ctk.StringVar(value=str(cfg.working_days))
        ctk.CTkEntry(
            wdf, textvariable=wdays_var, height=32, width=80,
            font=FONT_BODY, fg_color=SURFACE, border_color=TEXT_MUTED,
            corner_radius=6
        ).pack(side="left", padx=(8, 0))

        def save_settings():
            try:
                wd = int(wdays_var.get())
            except ValueError:
                messagebox.showerror("Validation",
                                      "Working days must be a number.")
                return

            save_config(CompanyConfig(
                cname_var.get(), caddr1_var.get(), caddr2_var.get(),
                cphone_var.get(), cemail_var.get(), wd
            ))
            self.status_bar.set_message("✅ Settings saved!", SUCCESS)
            messagebox.showinfo("Success", "Company settings saved!")

        ctk.CTkButton(
            form, text="💾  Save Settings", font=FONT_BODY_BOLD,
            fg_color=SUCCESS, hover_color="#2E7D32",
            height=42, corner_radius=8, command=save_settings
        ).pack(pady=(0, 20))

        # Database info
        db_info = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=12)
        db_info.pack(fill="x", padx=28, pady=(0, 20))

        ctk.CTkLabel(
            db_info, text="System Information",
            font=FONT_HEADING, text_color=TEXT_PRIMARY
        ).pack(padx=20, pady=(16, 8), anchor="w")

        ctk.CTkLabel(
            db_info,
            text=f"Database Path:  {os.path.abspath(DB_PATH)}",
            font=FONT_SMALL, text_color=TEXT_MUTED
        ).pack(padx=20, pady=(0, 4), anchor="w")
        ctk.CTkLabel(
            db_info,
            text="Share payroll.db via Google Drive for multi-site access "
                 "(one writer at a time).",
            font=FONT_SMALL, text_color=TEXT_MUTED
        ).pack(padx=20, pady=(0, 16), anchor="w")


# ══════════════════════════════════════════════════════════════════════════════
#   ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = PayrollApp()
    app.mainloop()
