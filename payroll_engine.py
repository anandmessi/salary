"""
payroll_engine.py — Indian Statutory Payroll Engine
=====================================================
Handles the full Nirbhik-style salary structure:
  Earnings : Basic, DA, HRA, CCA, OT, Arrears, N&FH, Bonus, etc.
  Deductions: EPF (12% of PF basis ≤15k), ESI (0.75% if gross ≤21k),
              Welfare Fund, TDS, Profession Tax, Advance Repayment, Fine …
"""

from __future__ import annotations
import datetime
import logging
from typing import List, Dict, Tuple

from schema import AttendanceRecord, MasterProfile, Worker, PayrollResult, CompanyConfig

logger = logging.getLogger(__name__)

# Statutory constants
ESI_CEILING      = 21_000.0
ESI_EMP_RATE     = 0.0075        # 0.75 %
PF_CEILING       = 15_000.0
PF_EMP_RATE      = 0.12          # 12 %


def _period_label(month: str) -> str:
    """'2025-04'  →  '01-April-2025 to 30-April-2025'"""
    try:
        dt       = datetime.datetime.strptime(month, "%Y-%m")
        last_day = (dt.replace(month=dt.month % 12 + 1, day=1)
                    - datetime.timedelta(days=1)).day if dt.month < 12 \
                   else 31
        return (f"01-{dt.strftime('%B-%Y')} to "
                f"{last_day}-{dt.strftime('%B-%Y')}")
    except ValueError:
        return month


def calculate_single(
    worker    : Worker,
    profile   : MasterProfile,
    att       : AttendanceRecord,
) -> PayrollResult:
    """
    Full payroll calculation for one worker × one month.

    Basic Wages: if att.basic_wages == 0, auto-compute from
                 days_present × profile.daily_wage.
    OT Wages   : if att.overtime_wages == 0 and we have ot data,
                 use profile.ot_rate (stored in attendance as overtime_wages
                 already converted to ₹ by the time it reaches here).
    EPF / ESI  : auto-computed unless override is set.
    """
    # ── Earnings ────────────────────────────────────────────────────────
    basic = att.basic_wages if att.basic_wages > 0 \
            else round(att.days_present * profile.daily_wage, 2)

    gross = round(
        basic
        + att.da
        + att.hra
        + att.cca
        + att.overtime_wages
        + att.arrears
        + att.advances_pay
        + att.nfh_wages
        + att.maternity_benefit
        + att.leave_wages
        + att.bonus
        + att.other_allowances,
        2,
    )

    # ── EPF ─────────────────────────────────────────────────────────────
    if att.epf_override > 0:
        epf = round(att.epf_override, 2)
    else:
        pf_basis = min(gross, PF_CEILING)
        epf      = round(pf_basis * PF_EMP_RATE, 2)

    # ── ESI ─────────────────────────────────────────────────────────────
    if att.esi_override > 0:
        esi = round(att.esi_override, 2)
    elif gross <= ESI_CEILING:
        esi = round(gross * ESI_EMP_RATE, 2)
    else:
        esi = 0.0

    total_ded = round(
        epf + esi
        + att.welfare_fund + att.tds + att.profession_tax
        + att.advance_repayment + att.fine
        + att.loss_damages + att.other_deductions,
        2,
    )
    net = round(gross - total_ded, 2)

    return PayrollResult(
        worker_id         = worker.worker_id,
        worker_name       = worker.name,
        profile_title     = profile.title,
        location          = profile.location,
        month             = att.month,
        period_label      = _period_label(att.month),
        joining_date      = worker.joining_date,
        days_present      = att.days_present,
        bank_name         = worker.bank_name,
        bank_account      = worker.bank_account,
        ifsc_code         = worker.ifsc_code,
        uan_number        = worker.uan_number,
        esic_number       = worker.esic_number,
        # earnings
        basic_wages       = basic,
        da                = att.da,
        hra               = att.hra,
        cca               = att.cca,
        overtime_wages    = att.overtime_wages,
        arrears           = att.arrears,
        advances_pay      = att.advances_pay,
        nfh_wages         = att.nfh_wages,
        maternity_benefit = att.maternity_benefit,
        leave_wages       = att.leave_wages,
        bonus             = att.bonus,
        other_allowances  = att.other_allowances,
        gross             = gross,
        # deductions
        epf_deduction     = epf,
        esi_deduction     = esi,
        welfare_fund      = att.welfare_fund,
        tds               = att.tds,
        profession_tax    = att.profession_tax,
        advance_repayment = att.advance_repayment,
        fine              = att.fine,
        loss_damages      = att.loss_damages,
        other_deductions  = att.other_deductions,
        total_deductions  = total_ded,
        net_pay           = net,
    )


def calculate_payroll(
    workers    : List[Worker],
    profiles   : Dict[str, MasterProfile],
    attendance : List[AttendanceRecord],
    month      : str,
) -> Tuple[List[PayrollResult], List[str]]:
    results  = []
    warnings = []
    att_idx  = {a.worker_id: a for a in attendance if a.month == month}

    for w in workers:
        if not w.active:
            continue
        att = att_idx.get(w.worker_id)
        if att is None:
            warnings.append(f"No attendance for {w.name} ({w.worker_id}) in {month}.")
            continue
        prof = profiles.get(w.profile_id)
        if prof is None:
            warnings.append(f"Profile '{w.profile_id}' not found for {w.name}.")
            continue
        try:
            results.append(calculate_single(w, prof, att))
        except Exception as e:
            warnings.append(f"Error for {w.name}: {e}")

    return results, warnings


def payroll_summary(results: List[PayrollResult]) -> dict:
    if not results:
        return dict(total_workers=0, total_gross=0, total_epf=0,
                    total_esi=0, total_net=0, total_deductions=0)
    return {
        "total_workers"   : len(results),
        "total_gross"     : round(sum(r.gross            for r in results), 2),
        "total_epf"       : round(sum(r.epf_deduction    for r in results), 2),
        "total_esi"       : round(sum(r.esi_deduction    for r in results), 2),
        "total_deductions": round(sum(r.total_deductions for r in results), 2),
        "total_net"       : round(sum(r.net_pay          for r in results), 2),
    }
