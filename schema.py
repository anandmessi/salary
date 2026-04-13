"""
schema.py — Data Schemas for the Payroll System
================================================
Matches the real Kerala-format salary slip (Nirbhik style) with all
earnings components (Basic, DA, HRA, Bonus …) and all deduction
components (EPF, ESI, Welfare Fund, TDS …).
Zero-value fields are suppressed at PDF render time.
"""

from dataclasses import dataclass, asdict
from typing import Optional
import json


@dataclass
class MasterProfile:
    profile_id : str
    title      : str
    daily_wage : float
    ot_rate    : float
    location   : str = "Head Office"

    def to_dict(self): return asdict(self)

    @staticmethod
    def from_dict(d): return MasterProfile(**d)


@dataclass
class Worker:
    worker_id    : str
    name         : str
    profile_id   : str
    bank_account : str  = ""
    bank_name    : str  = ""
    ifsc_code    : str  = ""
    uan_number   : str  = ""
    esic_number  : str  = ""
    joining_date : str  = ""
    active       : bool = True

    def to_dict(self): return asdict(self)

    @staticmethod
    def from_dict(d):
        d = dict(d)
        d["active"] = bool(d.get("active", True))
        # backward-compat: old DB rows may lack new columns
        defaults = dict(bank_name="", ifsc_code="")
        for k, v in defaults.items():
            d.setdefault(k, v)
        return Worker(**{k: d[k] for k in Worker.__dataclass_fields__})


@dataclass
class AttendanceRecord:
    """
    One row per worker per month.
    Stores all variable earnings + deduction overrides.
    Auto-calc fields (EPF, ESI) can be left 0; the engine will compute them.
    """
    worker_id    : str
    month        : str           # "YYYY-MM"
    days_present : float = 0.0

    # Earnings (any can be 0)
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
    # Identity
    worker_id    : str
    worker_name  : str
    profile_title: str
    location     : str
    month        : str
    period_label : str
    joining_date : str
    days_present : float
    bank_name    : str
    bank_account : str
    ifsc_code    : str
    uan_number   : str
    esic_number  : str

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
        """(label, value) pairs — zero rows excluded."""
        candidates = [
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
        return [(l, v) for l, v in candidates if v and v > 0]

    def deduction_items(self):
        """(label, value) pairs — zero rows excluded."""
        candidates = [
            ("EPF",               self.epf_deduction),
            ("ESI",               self.esi_deduction),
            ("Welfare Fund",      self.welfare_fund),
            ("TDS",               self.tds),
            ("Profession Tax",    self.profession_tax),
            ("Advance Repayment", self.advance_repayment),
            ("Fine",              self.fine),
            ("Loss & Damages",    self.loss_damages),
            ("Other Deductions",  self.other_deductions),
        ]
        return [(l, v) for l, v in candidates if v and v > 0]

    def summary_row(self) -> dict:
        return {
            "Worker ID"     : self.worker_id,
            "Name"          : self.worker_name,
            "Profile"       : self.profile_title,
            "Days"          : self.days_present,
            "Gross (Rs.)"  : round(self.gross, 2),
            "EPF (Rs.)"    : round(self.epf_deduction, 2),
            "ESI (Rs.)"    : round(self.esi_deduction, 2),
            "Total Ded."   : round(self.total_deductions, 2),
            "Net Pay (Rs.)": round(self.net_pay, 2),
        }


@dataclass
class CompanyConfig:
    company_name  : str = "NIRBHIK SUPPORT SERVICE PRIVATE LIMITED"
    address_line1 : str = "TMC 35/279, FACT NAGAR, MINI BYPASS, THRIPUNITHURA"
    address_line2 : str = "KOCHI-682301"
    phone         : str = ""
    email         : str = ""
    working_days  : int = 26

    def to_dict(self): return asdict(self)

    @staticmethod
    def from_dict(d): return CompanyConfig(**d)

    def to_json(self): return json.dumps(self.to_dict())

    @staticmethod
    def from_json(s): return CompanyConfig.from_dict(json.loads(s))


# ── Seed data ────────────────────────────────────────────────────────────────
SEED_PROFILES = [
    MasterProfile("sweeper",      "Sweeper",                   494.0,  65.0, "FACT Nagar"),
    MasterProfile("janitor_a",    "Janitor – Grade A",         550.0,  70.0, "Site Alpha"),
    MasterProfile("supervisor",   "Housekeeping Supervisor",   900.0, 110.0, "Head Office"),
    MasterProfile("loader",       "Loader / Helper",           500.0,  65.0, "Site Alpha"),
    MasterProfile("laundry_tech", "Laundry Technician",        620.0,  80.0, "Site Beta"),
]

SEED_WORKERS = [
    Worker("N640",   "SUNITHA K S",  "sweeper",    "201250011183220", "KARNATAKA BANK", "KARB0000201", "",             "",      "2024-02-20"),
    Worker("EMP001", "Rajan Kumar",  "janitor_a",  "SB1234567890",   "SBI",            "SBIN0001234", "100123456789", "IP001", "2022-01-10"),
    Worker("EMP002", "Meena Pillai", "janitor_a",  "SB9876543210",   "HDFC BANK",      "HDFC0002345", "100234567890", "IP002", "2021-06-15"),
    Worker("EMP003", "Suresh Nair",  "supervisor", "SB1122334455",   "CANARA BANK",    "CNRB0003456", "100345678901", "IP003", "2020-03-01"),
]
