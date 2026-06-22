#!/usr/bin/env python3
"""
Module: payroll_payslip_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Read model untuk slip gaji (payslip) - alias untuk PayslipTable.
               File ini hanya menyediakan akses ke model payslip yang sudah
               didefinisikan di payslip_table.py untuk menghindari duplikasi.
"""

from infrastructure.persistence_orm.payslip_table import PayslipReadModel, PayslipTable

# Alias untuk kompatibilitas dengan kode lama yang mungkin menggunakan nama ini
PayrollPayslipTable = PayslipTable

__all__ = ["PayrollPayslipTable", "PayslipReadModel", "PayslipTable"]
