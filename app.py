"""
app.py — PayrollPro Streamlit GUI  (v2 — Nirbhik Format)
=========================================================
Run with:   streamlit run app.py
"""

import os, io, tempfile, datetime
import pandas as pd
import streamlit as st

from schema import Worker, MasterProfile, AttendanceRecord, CompanyConfig
from database import (
    init_db, get_all_workers, get_all_profiles, get_profiles_dict,
    get_attendance, upsert_attendance, bulk_upsert_attendance,
    upsert_worker, deactivate_worker, upsert_profile, delete_profile,
    get_config, save_config, get_months_with_data,
    import_attendance_from_csv, DB_PATH,
)
from payroll_engine import calculate_payroll, payroll_summary
from pdf_generator   import generate_bulk_pdfs, generate_slip_pdf

st.set_page_config(page_title="PayrollPro", page_icon="💼", layout="wide")
init_db(DB_PATH, seed=True)

def month_options():
    today, months = datetime.date.today(), []
    for i in range(11, -1, -1):
        y, m = today.year, today.month - i
        while m <= 0: m += 12; y -= 1
        months.append(f"{y}-{m:02d}")
    return months

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 💼 PayrollPro")
    st.markdown("---")
    page = st.radio("Navigate", [
        "📊 Dashboard", "📋 Attendance", "👷 Workers",
        "🏷️ Job Profiles", "📄 Generate Slips", "⚙️ Settings",
    ], label_visibility="collapsed")
    st.markdown("---")
    st.caption("Zero-Cost Payroll System\nPython + Streamlit + SQLite")


# ════════════════════ DASHBOARD ══════════════════════════════════════════════
if page == "📊 Dashboard":
    st.title("📊 Payroll Dashboard")

    opts = month_options()
    col1, col2, _ = st.columns([2,2,4])
    with col1: sel_month = st.selectbox("Month", opts, index=len(opts)-1)
    with col2:
        locs = sorted({p.location for p in get_all_profiles()})
        sel_loc = st.selectbox("Location", ["All"] + locs)

    workers    = get_all_workers()
    profiles   = get_profiles_dict()
    attendance = get_attendance(sel_month)

    if sel_loc != "All":
        rel = {pid for pid,p in profiles.items() if p.location==sel_loc}
        workers = [w for w in workers if w.profile_id in rel]

    results, warnings = calculate_payroll(workers, profiles, attendance, sel_month)

    if warnings:
        with st.expander(f"⚠️ {len(warnings)} warning(s)"):
            for w in warnings: st.warning(w)

    if not results:
        st.info("No payroll data. Enter attendance first.")
        st.stop()

    s = payroll_summary(results)
    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("Workers",       s["total_workers"])
    c2.metric("Total Gross",   f"Rs.{s['total_gross']:,.0f}")
    c3.metric("Total EPF",     f"Rs.{s['total_epf']:,.0f}")
    c4.metric("Total ESI",     f"Rs.{s['total_esi']:,.0f}")
    c5.metric("Total Net Pay", f"Rs.{s['total_net']:,.0f}")

    st.divider()
    st.subheader("Payroll Preview")
    df = pd.DataFrame([r.summary_row() for r in results])
    st.dataframe(df.style.format({
        "Gross (Rs.)":   "Rs.{:,.2f}",
        "EPF (Rs.)":     "Rs.{:,.2f}",
        "ESI (Rs.)":     "Rs.{:,.2f}",
        "Total Ded.":    "Rs.{:,.2f}",
        "Net Pay (Rs.)": "Rs.{:,.2f}",
    }).background_gradient(subset=["Net Pay (Rs.)"], cmap="Greens"),
    use_container_width=True, height=420)

    csv_buf = io.StringIO(); df.to_csv(csv_buf, index=False)
    st.download_button("⬇️ Download CSV", csv_buf.getvalue().encode(),
                       f"Payroll_{sel_month}.csv", "text/csv")


# ════════════════════ ATTENDANCE ══════════════════════════════════════════════
elif page == "📋 Attendance":
    st.title("📋 Attendance & Earnings Entry")
    tab1, tab2 = st.tabs(["✏️ Manual Entry", "📥 CSV Import"])

    with tab1:
        opts = month_options()
        sel_month = st.selectbox("Month", opts, index=len(opts)-1, key="att_m")
        workers   = get_all_workers()
        profiles  = get_profiles_dict()
        existing  = {a.worker_id: a for a in get_attendance(sel_month)}
        config    = get_config()

        st.caption("Enter attendance and all applicable earnings. **Leave a field 0 if not applicable** — it will be hidden on the slip.")

        # ── Quick table for days-present (most common edit) ───────────────
        st.subheader("Step 1 — Days Present & OT")
        rows = []
        for w in workers:
            att = existing.get(w.worker_id, AttendanceRecord(w.worker_id, sel_month))
            p   = profiles.get(w.profile_id)
            rows.append({
                "Worker ID"        : w.worker_id,
                "Name"             : w.name,
                "Profile"          : p.title if p else w.profile_id,
                "Days Present"     : att.days_present,
                "Overtime Wages(Rs)": att.overtime_wages,
            })

        days_df = st.data_editor(
            pd.DataFrame(rows), use_container_width=True, hide_index=True,
            column_config={
                "Worker ID":         st.column_config.TextColumn(disabled=True),
                "Name":              st.column_config.TextColumn(disabled=True),
                "Profile":           st.column_config.TextColumn(disabled=True),
                "Days Present":      st.column_config.NumberColumn(min_value=0, max_value=config.working_days, step=0.5),
                "Overtime Wages(Rs)":st.column_config.NumberColumn(min_value=0, step=10.0),
            },
        )

        # ── Per-worker allowances & deductions expander ───────────────────
        st.subheader("Step 2 — Allowances & Deductions (per worker)")
        st.caption("Expand a worker to enter DA, HRA, Bonus, Advance Repayment, etc.")

        updated_records = {}
        for i, row in days_df.iterrows():
            wid = row["Worker ID"]
            att = existing.get(wid, AttendanceRecord(wid, sel_month))
            with st.expander(f"{wid} — {row['Name']}"):
                c1, c2, c3 = st.columns(3)
                new_att = AttendanceRecord(
                    worker_id       = wid,
                    month           = sel_month,
                    days_present    = float(row["Days Present"]),
                    overtime_wages  = float(row["Overtime Wages(Rs)"]),
                    da              = c1.number_input("DA (Rs.)",              value=att.da,               min_value=0.0, step=50.0, key=f"da_{wid}"),
                    hra             = c2.number_input("HRA (Rs.)",             value=att.hra,              min_value=0.0, step=50.0, key=f"hra_{wid}"),
                    cca             = c3.number_input("CCA (Rs.)",             value=att.cca,              min_value=0.0, step=50.0, key=f"cca_{wid}"),
                    arrears         = c1.number_input("Arrears (Rs.)",         value=att.arrears,          min_value=0.0, step=50.0, key=f"arr_{wid}"),
                    nfh_wages       = c2.number_input("N&FH Wages (Rs.)",      value=att.nfh_wages,        min_value=0.0, step=50.0, key=f"nfh_{wid}"),
                    leave_wages     = c3.number_input("Leave Wages (Rs.)",     value=att.leave_wages,      min_value=0.0, step=50.0, key=f"lw_{wid}"),
                    bonus           = c1.number_input("Bonus (Rs.)",           value=att.bonus,            min_value=0.0, step=50.0, key=f"bon_{wid}"),
                    maternity_benefit=c2.number_input("Maternity Benefit(Rs.)",value=att.maternity_benefit,min_value=0.0, step=50.0, key=f"mat_{wid}"),
                    advances_pay    = c3.number_input("Advance Pay (Rs.)",     value=att.advances_pay,     min_value=0.0, step=50.0, key=f"adv_{wid}"),
                    other_allowances= c1.number_input("Other Allowances(Rs.)", value=att.other_allowances, min_value=0.0, step=50.0, key=f"oa_{wid}"),
                    # Deductions
                    epf_override    = c2.number_input("EPF Override (0=auto)", value=att.epf_override,     min_value=0.0, step=10.0, key=f"epf_{wid}"),
                    esi_override    = c3.number_input("ESI Override (0=auto)", value=att.esi_override,     min_value=0.0, step=10.0, key=f"esi_{wid}"),
                    welfare_fund    = c1.number_input("Welfare Fund (Rs.)",    value=att.welfare_fund,     min_value=0.0, step=10.0, key=f"wf_{wid}"),
                    tds             = c2.number_input("TDS (Rs.)",             value=att.tds,              min_value=0.0, step=10.0, key=f"tds_{wid}"),
                    profession_tax  = c3.number_input("Profession Tax (Rs.)",  value=att.profession_tax,   min_value=0.0, step=10.0, key=f"pt_{wid}"),
                    advance_repayment=c1.number_input("Advance Repayment(Rs.)",value=att.advance_repayment,min_value=0.0, step=50.0, key=f"ar_{wid}"),
                    fine            = c2.number_input("Fine (Rs.)",            value=att.fine,             min_value=0.0, step=10.0, key=f"fine_{wid}"),
                    loss_damages    = c3.number_input("Loss & Damages (Rs.)",  value=att.loss_damages,     min_value=0.0, step=10.0, key=f"ld_{wid}"),
                    other_deductions= c1.number_input("Other Deductions(Rs.)", value=att.other_deductions, min_value=0.0, step=10.0, key=f"od_{wid}"),
                )
                updated_records[wid] = new_att

        if st.button("💾 Save All Attendance", type="primary"):
            records = list(updated_records.values())
            bulk_upsert_attendance(records)
            st.success(f"✅ Saved {len(records)} records for {sel_month}.")
            st.rerun()

    with tab2:
        st.markdown("""
        Upload a CSV. Any column not present defaults to 0.

        **Supported columns:**
        `worker_id, days_present, basic_wages, da, hra, cca, overtime_wages,
        arrears, advances_pay, nfh_wages, maternity_benefit, leave_wages,
        bonus, other_allowances, epf_override, esi_override,
        welfare_fund, tds, profession_tax, advance_repayment,
        fine, loss_damages, other_deductions`
        """)
        workers  = get_all_workers()
        tpl_cols = ["worker_id","days_present","basic_wages","da","hra","cca",
                    "overtime_wages","bonus","advance_repayment"]
        tpl_df   = pd.DataFrame([{c: (w.worker_id if c=="worker_id" else 0) for c in tpl_cols}
                                  for w in workers])
        st.download_button("⬇️ Download Template",
                           tpl_df.to_csv(index=False).encode(),
                           "attendance_template.csv", "text/csv")
        st.divider()
        opts      = month_options()
        imp_month = st.selectbox("Import for Month", opts, index=len(opts)-1, key="imp_m")
        uploaded  = st.file_uploader("Upload CSV", type=["csv"])
        if uploaded and st.button("📥 Import", type="primary"):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
                tmp.write(uploaded.read()); tmp_path = tmp.name
            res = import_attendance_from_csv(tmp_path, imp_month)
            os.unlink(tmp_path)
            st.success(f"✅ Imported {res['imported']} records.")
            if res["errors"]:
                st.error("\n".join(res["errors"]))


# ════════════════════ WORKERS ═════════════════════════════════════════════════
elif page == "👷 Workers":
    st.title("👷 Worker Master Data")
    tab1, tab2 = st.tabs(["👥 All Workers", "➕ Add / Edit Worker"])

    with tab1:
        workers  = get_all_workers(active_only=False)
        profiles = get_profiles_dict()
        rows = [{
            "ID": w.worker_id, "Name": w.name,
            "Profile": (profiles[w.profile_id].title if w.profile_id in profiles else w.profile_id),
            "Bank": w.bank_name, "A/C": w.bank_account,
            "IFSC": w.ifsc_code, "UAN": w.uan_number, "ESIC": w.esic_number,
            "Status": "✅" if w.active else "❌",
        } for w in workers]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, height=400)
        wids = [w.worker_id for w in workers if w.active]
        sel  = st.selectbox("Deactivate", wids)
        if st.button("❌ Deactivate Worker", type="secondary"):
            deactivate_worker(sel); st.success(f"{sel} deactivated."); st.rerun()

    with tab2:
        profiles = get_all_profiles()
        pmap     = {p.profile_id: f"{p.title} ({p.location})" for p in profiles}
        with st.form("wf"):
            wid   = st.text_input("Worker ID *", placeholder="N641")
            wname = st.text_input("Full Name *")
            wprof = st.selectbox("Job Profile *", list(pmap.keys()), format_func=lambda k: pmap[k])
            c1,c2,c3 = st.columns(3)
            wbank = c1.text_input("Bank Account No.")
            wbname= c2.text_input("Bank Name", placeholder="KARNATAKA BANK")
            wifsc = c3.text_input("IFSC Code",   placeholder="KARB0000201")
            c4,c5,c6 = st.columns(3)
            wuan  = c4.text_input("UAN Number (PF)")
            wesic = c5.text_input("ESIC IP Number")
            wjoin = c6.date_input("Joining Date", value=datetime.date.today())
            ok    = st.form_submit_button("💾 Save Worker", type="primary")
        if ok:
            if not wid or not wname: st.error("ID and Name required.")
            else:
                upsert_worker(Worker(wid.strip().upper(), wname.strip(), wprof,
                                     wbank, wbname, wifsc, wuan, wesic, str(wjoin), True))
                st.success(f"Worker {wid} saved!"); st.rerun()


# ════════════════════ JOB PROFILES ════════════════════════════════════════════
elif page == "🏷️ Job Profiles":
    st.title("🏷️ Job Profile Master")
    tab1, tab2 = st.tabs(["📋 All", "➕ Add / Edit"])
    with tab1:
        profiles = get_all_profiles()
        if profiles:
            df = pd.DataFrame([p.to_dict() for p in profiles])
            df.columns = ["Profile ID","Title","Daily Wage (Rs.)","OT Rate (Rs./hr)","Location"]
            st.dataframe(df, use_container_width=True)
        pid_del = st.selectbox("Delete profile", [p.profile_id for p in profiles])
        if st.button("🗑️ Delete", type="secondary"):
            delete_profile(pid_del); st.success("Deleted."); st.rerun()
    with tab2:
        with st.form("pf"):
            pid   = st.text_input("Profile ID *", placeholder="sweeper_b")
            ptit  = st.text_input("Title *",       placeholder="Sweeper Grade B")
            c1,c2 = st.columns(2)
            pdw   = c1.number_input("Daily Wage (Rs.) *", min_value=100.0, value=494.0, step=10.0)
            pot   = c2.number_input("OT Rate (Rs./hr) *", min_value=0.0,   value=65.0,  step=5.0)
            ploc  = st.text_input("Location / Site *", value="Head Office")
            ok    = st.form_submit_button("💾 Save", type="primary")
        if ok:
            if not pid or not ptit: st.error("ID and Title required.")
            elif " " in pid:        st.error("No spaces in Profile ID.")
            else:
                upsert_profile(MasterProfile(pid.strip().lower(), ptit.strip(), pdw, pot, ploc.strip()))
                st.success(f"Profile '{pid}' saved!"); st.rerun()


# ════════════════════ GENERATE SLIPS ══════════════════════════════════════════
elif page == "📄 Generate Slips":
    st.title("📄 Generate Salary Slips")
    config   = get_config()
    workers  = get_all_workers()
    profiles = get_profiles_dict()
    opts     = month_options()

    c1,c2,_ = st.columns([2,2,4])
    with c1: sel_month = st.selectbox("Month", opts, index=len(opts)-1)
    with c2:
        locs    = sorted({p.location for p in profiles.values()})
        sel_loc = st.selectbox("Location", ["All"] + locs)

    attendance = get_attendance(sel_month)
    if sel_loc != "All":
        rel     = {pid for pid,p in profiles.items() if p.location==sel_loc}
        workers = [w for w in workers if w.profile_id in rel]

    results, warnings = calculate_payroll(workers, profiles, attendance, sel_month)
    if warnings:
        with st.expander(f"⚠️ {len(warnings)} warning(s)"):
            for w in warnings: st.warning(w)

    if not results: st.info("No data. Add attendance first."); st.stop()

    st.subheader(f"Ready: {len(results)} slip(s)")
    st.dataframe(pd.DataFrame([r.summary_row() for r in results]),
                 use_container_width=True, height=260)
    st.divider()

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("📦 Generate ALL as ZIP", type="primary", use_container_width=True):
            out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "salary_slips")
            with st.spinner("Generating PDFs…"):
                gen = generate_bulk_pdfs(results, config, out_dir, zip_output=True)
            for e in gen["errors"]: st.error(e)
            if gen["zip_path"] and os.path.exists(gen["zip_path"]):
                with open(gen["zip_path"],"rb") as zf:
                    st.download_button(
                        f"⬇️ Download ZIP ({gen['success_count']} slips)",
                        zf.read(), os.path.basename(gen["zip_path"]), "application/zip",
                        type="primary",
                    )
                st.success(f"✅ {gen['success_count']} slips generated → {out_dir}")

    with col_b:
        st.markdown("**Preview single slip:**")
        names   = {r.worker_id: r.worker_name for r in results}
        sel_wid = st.selectbox("Worker", list(names.keys()),
                               format_func=lambda k: f"{k} — {names[k]}",
                               label_visibility="collapsed")
        if st.button("👁️ Download Single Slip", use_container_width=True):
            target = next((r for r in results if r.worker_id==sel_wid), None)
            if target:
                out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),"salary_slips")
                with st.spinner("Generating…"):
                    path = generate_slip_pdf(target, config, out_dir)
                with open(path,"rb") as f:
                    st.download_button(
                        f"⬇️ {target.worker_name}'s Slip",
                        f.read(), os.path.basename(path), "application/pdf",
                    )


# ════════════════════ SETTINGS ════════════════════════════════════════════════
elif page == "⚙️ Settings":
    st.title("⚙️ Company Settings")
    cfg = get_config()
    with st.form("cfg"):
        cname  = st.text_input("Company Name",  value=cfg.company_name)
        caddr1 = st.text_input("Address Line 1",value=cfg.address_line1)
        caddr2 = st.text_input("Address Line 2",value=cfg.address_line2)
        c1,c2  = st.columns(2)
        cphone = c1.text_input("Phone", value=cfg.phone)
        cemail = c2.text_input("Email", value=cfg.email)
        cwdays = st.number_input("Standard Working Days", min_value=20, max_value=31,
                                  value=cfg.working_days)
        ok = st.form_submit_button("💾 Save", type="primary")
    if ok:
        save_config(CompanyConfig(cname,caddr1,caddr2,cphone,cemail,int(cwdays)))
        st.success("✅ Saved!"); st.rerun()
    st.divider()
    st.code(f"Database: {os.path.abspath(DB_PATH)}")
    st.info("Share payroll.db via Google Drive for multi-site access (one writer at a time).")
