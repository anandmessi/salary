"""
payroll_engine.py — Indian Statutory Payroll Engine
=====================================================
Wages determined by SKILL CATEGORY:
  - Each skill category (Skilled/Semi-Skilled/Unskilled) has its own daily_wage & ot_rate.
  - Basic = days_present × daily_wage (from skill category).

Deductions:
  EPF = 12% of (Basic + DA)
  ESI = 0.75% of (Basic + DA) if gross ≤ ₹21,000
"""

from __future__ import annotations
import datetime
import logging
from typing import List, Dict, Tuple

from schema import AttendanceRecord, SkillWage, Worker, PayrollResult

logger = logging.getLogger(__name__)

ESI_GROSS_CEILING = 21_000.0
ESI_EMP_RATE      = 0.0075
PF_EMP_RATE       = 0.12


def _period_label(month: str) -> str:
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
    worker     : Worker,
    skill_wage : SkillWage,
    att        : AttendanceRecord,
) -> PayrollResult:
    # ── Earnings ────────────────────────────────────────────────────────
    basic = att.basic_wages if att.basic_wages > 0 \
            else round(att.days_present * skill_wage.daily_wage, 2)

    overtime_wages = round(att.overtime_hours * skill_wage.ot_rate, 2)

    gross = round(
        basic + att.da + att.hra + att.cca
        + overtime_wages + att.arrears + att.advances_pay
        + att.nfh_wages + att.maternity_benefit + att.leave_wages
        + att.bonus + att.other_allowances,
        2,
    )

    # ── PF/ESI basis = Basic + DA ───────────────────────────────────────
    pf_esi_basis = round(basic + att.da, 2)

    # EPF
    epf = round(att.epf_override, 2) if att.epf_override > 0 \
          else round(pf_esi_basis * PF_EMP_RATE, 2)

    # ESI
    if att.esi_override > 0:
        esi = round(att.esi_override, 2)
    elif gross <= ESI_GROSS_CEILING:
        esi = round(pf_esi_basis * ESI_EMP_RATE, 2)
    else:
        esi = 0.0

    total_ded = round(
        epf + esi + att.welfare_fund + att.tds + att.profession_tax
        + att.advance_repayment + att.fine + att.loss_damages
        + att.other_deductions, 2,
    )
    net = round(gross - total_ded, 2)

    return PayrollResult(
        worker_id         = worker.worker_id,
        worker_name       = worker.name,
        profile_title     = worker.designation,
        location          = worker.unit,
        month             = att.month,
        period_label      = _period_label(att.month),
        joining_date      = worker.joining_date,
        days_present      = att.days_present,
        bank_name         = worker.bank_name,
        bank_account      = worker.bank_account,
        ifsc_code         = worker.ifsc_code,
        uan_number        = worker.uan_number,
        esic_number       = worker.esic_number,
        unit            = worker.unit,
        skill_category    = worker.skill_category,
        basic_wages       = basic,
        da                = att.da,
        hra               = att.hra,
        cca               = att.cca,
        overtime_wages    = overtime_wages,
        arrears           = att.arrears,
        advances_pay      = att.advances_pay,
        nfh_wages         = att.nfh_wages,
        maternity_benefit = att.maternity_benefit,
        leave_wages       = att.leave_wages,
        bonus             = att.bonus,
        other_allowances  = att.other_allowances,
        gross             = gross,
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
    workers     : List[Worker],
    skill_wages : Dict[str, SkillWage],
    attendance  : List[AttendanceRecord],
    month       : str,
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
        sw = skill_wages.get(w.skill_category)
        if sw is None:
            warnings.append(f"No wage rate for skill '{w.skill_category}' — {w.name}.")
            continue
        try:
            results.append(calculate_single(w, sw, att))
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
