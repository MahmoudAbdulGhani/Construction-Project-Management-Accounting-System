from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'audit'

    def ready(self):
        from .registry import register
        from .services import connect_audit_signals

        # ``ready()`` runs after all app models are loaded, so importing here is
        # safe and idempotent. Build the audit surface as a flat list of
        # ``(model, entity_type, label)`` so each model is registered once.
        #
        # Audit scope: users and tax configuration, people records, plus
        # money-moving and counterparty documents -- including the GL
        # (Account, FinancialTransaction), since journal entries are now
        # auto-generated from those documents and the financial
        # transactions table IS the ledger. Dropped as low audit value:
        # Project phase, Project budget, Material category, Warehouse,
        # transaction line items -- high-frequency churn or derived
        # bookkeeping that would flood the trail without helping.
        from accounting.models import Account, FinancialTransaction
        from clients.models import Client
        from company.models import CompanyProfile
        from contractors.models import Contractor
        from employees.models import Employee
        from expenses.models import Expense
        from inventory.models import Material
        from invoicing.models import ClientInvoice, SupplierInvoice
        from payments.models import Payment, Receipt
        from projects.models import Project
        from purchasing.models import GoodsReceipt, PurchaseOrder
        from suppliers.models import Supplier
        from taxes.models import TaxRate
        from users.models import User

        auditables = [
            (User, 'user', 'User', 'Access & settings'),
            (CompanyProfile, 'company_profile', 'Company profile', 'Access & settings'),
            (TaxRate, 'tax_rate', 'Tax rate', 'Access & settings'),
            (Project, 'project', 'Project', 'Projects'),
            (Employee, 'employee', 'Employee', 'People'),
            (Client, 'client', 'Client', 'Partners'),
            (Supplier, 'supplier', 'Supplier', 'Partners'),
            (Contractor, 'contractor', 'Contractor', 'Partners'),
            (PurchaseOrder, 'purchase_order', 'Purchase order', 'Operations'),
            (GoodsReceipt, 'goods_receipt', 'Goods receipt', 'Operations'),
            (Material, 'material', 'Material', 'Operations'),
            (Account, 'account', 'Account', 'Money'),
            (FinancialTransaction, 'financial_transaction', 'Financial transaction', 'Money'),
            (SupplierInvoice, 'supplier_invoice', 'Supplier invoice', 'Money'),
            (ClientInvoice, 'client_invoice', 'Client invoice', 'Money'),
            (Expense, 'expense', 'Expense', 'Money'),
            (Payment, 'payment', 'Payment', 'Money'),
            (Receipt, 'receipt', 'Receipt', 'Money'),
        ]

        for model, entity_type, label, category in auditables:
            register(model, entity_type, label, category)
            connect_audit_signals(model)