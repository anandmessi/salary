"""
schema.py — Data Schemas for the Payroll System
================================================
Wages are determined by SKILL CATEGORY (Skilled / Semi-Skilled / Unskilled),
not by job designation. Designations like Sweeper, Janitor etc. are just labels.
"""

from dataclasses import dataclass, asdict
from typing import Optional
import json


# ── Company-wide Constants ───────────────────────────────────────────────────
# Units are stored in the database (dynamic, managed via UI).

SKILL_CATEGORIES = [
    "Skilled",
    "Semi-Skilled",
    "Unskilled",
    "Unskilled Ladies",
    "Grass Cutting",
    "Skilled Data Entry",
    "Highly Skilled",
]


@dataclass
class SkillWage:
    """
    Daily wage and OT rate for a skill category.
    e.g. Unskilled → ₹494/day, ₹65/hr OT
         Semi-Skilled → ₹550/day, ₹70/hr OT
         Skilled → ₹700/day, ₹90/hr OT
    """
    skill_category : str
    daily_wage     : float
    ot_rate        : float

    def to_dict(self): return asdict(self)

    @staticmethod
    def from_dict(d): return SkillWage(**d)


@dataclass
class Worker:
    """
    One worker with personal, bank, and statutory details.
    Wage is determined by skill_category, NOT by designation.
    """
    worker_id      : str
    name           : str
    designation    : str  = ""    # Job title label: Sweeper, Janitor, etc.
    bank_account   : str  = ""
    bank_name      : str  = ""
    ifsc_code      : str  = ""
    uan_number     : str  = ""    # PF Universal Account Number
    esic_number    : str  = ""    # ESIC IP Number
    joining_date   : str  = ""
    active         : bool = True
    unit         : str  = ""    # Which unit (from units table)
    skill_category : str  = "Unskilled"

    def to_dict(self): return asdict(self)

    @staticmethod
    def from_dict(d):
        d = dict(d)
        d["active"] = bool(d.get("active", True))
        defaults = dict(
            bank_name="", ifsc_code="",
            unit="", skill_category="Unskilled",
            designation="",
        )
        for k, v in defaults.items():
            d.setdefault(k, v)
        return Worker(**{k: d[k] for k in Worker.__dataclass_fields__})


@dataclass
class AttendanceRecord:
    """
    One row per worker per month.
    Stores all variable earnings + deduction overrides.
    """
    worker_id    : str
    month        : str           # "YYYY-MM"
    days_present : float = 0.0

    # Earnings
    basic_wages       : float = 0.0
    da                : float = 0.0
    hra               : float = 0.0
    cca               : float = 0.0
    overtime_hours    : float = 0.0   # user enters hours; engine × ot_rate = wages
    arrears           : float = 0.0
    advances_pay      : float = 0.0
    nfh_wages         : float = 0.0
    maternity_benefit : float = 0.0
    leave_wages       : float = 0.0
    bonus             : float = 0.0
    other_allowances  : float = 0.0

    # Manual deduction overrides (0 = let engine calculate)
    epf_override      : float = 0.0
    esi_override      : float = 0.0
    welfare_fund      : float = 0.0
    tds               : float = 0.0
    profession_tax    : float = 0.0
    advance_repayment : float = 0.0
    fine              : float = 0.0
    loss_damages      : float = 0.0
    other_deductions  : float = 0.0

    record_id : Optional[int] = None

    def to_dict(self): return asdict(self)

    @staticmethod
    def from_dict(d):
        d = dict(d)
        known = set(AttendanceRecord.__dataclass_fields__)
        return AttendanceRecord(**{k: d[k] for k in known if k in d})


@dataclass
class PayrollResult:
    """Fully computed payroll for one worker/month — handed to PDF."""
    worker_id      : str
    worker_name    : str
    profile_title  : str        # = designation (Sweeper, Janitor …)
    location       : str        # = unit
    month          : str
    period_label   : str
    joining_date   : str
    days_present   : float
    bank_name      : str
    bank_account   : str
    ifsc_code      : str
    uan_number     : str
    esic_number    : str
    unit         : str = ""
    skill_category : str = ""

    # Earnings
    basic_wages       : float = 0.0
    da                : float = 0.0
    hra               : float = 0.0
    cca               : float = 0.0
    overtime_wages    : float = 0.0
    arrears           : float = 0.0
    advances_pay      : float = 0.0
    nfh_wages         : float = 0.0
    maternity_benefit : float = 0.0
    leave_wages       : float = 0.0
    bonus             : float = 0.0
    other_allowances  : float = 0.0
    gross             : float = 0.0

    # Deductions
    epf_deduction     : float = 0.0
    esi_deduction     : float = 0.0
    welfare_fund      : float = 0.0
    tds               : float = 0.0
    profession_tax    : float = 0.0
    advance_repayment : float = 0.0
    fine              : float = 0.0
    loss_damages      : float = 0.0
    other_deductions  : float = 0.0
    total_deductions  : float = 0.0
    net_pay           : float = 0.0

    def to_dict(self): return asdict(self)

    def earnings_items(self):
        return [(l, v) for l, v in self.all_earnings_items() if v and v > 0]

    def deduction_items(self):
        return [(l, v) for l, v in self.all_deduction_items() if v and v > 0]

    def all_earnings_items(self):
        return [
            ("Basic Wages",       self.basic_wages),
            ("DA",                self.da),
            ("HRA",               self.hra),
            ("CCA",               self.cca),
            ("Overtime Wages",    self.overtime_wages),
            ("Arrears",           self.arrears),
            ("Advances",          self.advances_pay),
            ("N&FH Wages",        self.nfh_wages),
            ("Maternity Benefit", self.maternity_benefit),
            ("Leave Wages",       self.leave_wages),
            ("Bonus",             self.bonus),
            ("Other Allowances",  self.other_allowances),
        ]

    def all_deduction_items(self):
        return [
            ("EPF",               self.epf_deduction),
            ("ESI",               self.esi_deduction),
            ("Welfare Fund",      self.welfare_fund),
            ("TDS",               self.tds),
            ("Profession Tax",    self.profession_tax),
            ("Advance Repayment", self.advance_repayment),
            ("Fine",              self.fine),
            ("Loss&Damages",      self.loss_damages),
            ("Other deductions",  self.other_deductions),
        ]

    def summary_row(self) -> dict:
        return {
            "Worker ID"      : self.worker_id,
            "Name"           : self.worker_name,
            "Unit"         : self.unit,
            "Skill"          : self.skill_category,
            "Designation"    : self.profile_title,
            "Days"           : self.days_present,
            "Gross (Rs.)"    : round(self.gross, 2),
            "EPF (Rs.)"      : round(self.epf_deduction, 2),
            "ESI (Rs.)"      : round(self.esi_deduction, 2),
            "Total Ded."     : round(self.total_deductions, 2),
            "Net Pay (Rs.)"  : round(self.net_pay, 2),
        }


@dataclass
class CompanyConfig:
    company_name  : str = "NIRBHIK SUPPORT SERVICE PRIVATE LIMITED"
    address_line1 : str = "TMC 35/279, FACT NAGAR, MINI BYPASS, THRIPUNITHURA"
    address_line2 : str = "KOCHI-682301"
    phone         : str = ""
    email         : str = ""
    working_days  : int = 26
    
    # Statutory Settings
    epf_rate      : float = 12.0
    esi_rate      : float = 0.75
    esi_ceiling   : float = 21000.0
    
    # Email Automation Target
    target_email  : str = ""

    def to_dict(self): return asdict(self)

    @staticmethod
    def from_dict(d):
        d = dict(d)
        defaults = dict(
            epf_rate=12.0, esi_rate=0.75, esi_ceiling=21000.0, target_email=""
        )
        for k, v in defaults.items():
            d.setdefault(k, v)
        return CompanyConfig(**{k: d[k] for k in CompanyConfig.__dataclass_fields__ if k in d})

    def to_json(self): return json.dumps(self.to_dict())

    @staticmethod
    def from_json(s): return CompanyConfig.from_dict(json.loads(s))
