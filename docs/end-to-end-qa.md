# End-to-End Manual QA

Manual walkthrough of the full project flow — every major module plus the
accounting/GL integration (including the Accounting dialog fixes from
2026-09-07). Run it top to bottom in a scratch workspace; do not run against
your live/production database unless you are prepared to create test records.

## Prerequisites

- Server running: `python manage.py runserver`
- Migrations applied (Supabase or local SQLite) — `python manage.py migrate`
- Logged in as an **Owner** account (sidebar shows the "Workspace" + "Operations"
  groups). If you only have an Accountant role, Owner-only modules
  (Projects, Approvals, Clients & partners, Suppliers, Procurement, Inventory,
  Workforce, Documents, Settings) will not be reachable.
- The chart of accounts is **seeded by migration `0002`** — the 7 default
  accounts must exist:
  `1000 Cash`, `1100 Accounts Receivable`, `2000 Accounts Payable`,
  `2100 Tax Payable`, `4000 Construction Revenue`, `5000 Cost of Construction`,
  `6000 General Operating Expenses`.

Suggested login test account:

```powershell
python manage.py createsuperuser   # or use an existing Owner account
```

## Time budget

About 30–45 minutes if you type slowly. The first two sections are the most
important (recent work). Section C is a fast page-by-page smoke.

---

## A. Accounting page (highest priority — recent bug fix)

URL: `/accounting/`

> These steps verify the bugs reported on 2026-09-07 (dead "New journal entry"
> button, "Cannot post a financial transaction with no lines", edit throwing
> `cloneNode` null, and the form not appearing as a popup).

### A1. Page loads with seeded accounts

1. Open `/accounting/`.
2. Confirm the chart-of-accounts table lists the 7 seeded accounts.

☐ Expected: page renders; all 7 seed accounts present; no JS errors in the
browser console (`F12`).

### A2. "New journal entry" opens a popup

1. Click **+ New journal entry**.
2. Confirm a **modal popup** appears (centered dialog with backdrop).

☐ Expected: popup opens with an empty header form and **two empty line rows**.
☐ Expected: balance bar shows `Debit $0.00 / Credit $0.00 / Balanced`.

### A3. Add and remove lines

1. In the popup, click **＋ Add line** → a third empty row appears.
2. Click the **×** on that row → it disappears again.

☐ Expected: rows append/remove without errors; balance bar updates.

### A4. Unbalanced entry → friendly in-dialog error (no native alert)

1. Header: Transaction number `QA-MANUAL-1`, a date, description
   `QA manual unbalanced entry`.
2. Line 1: Account `1000 Cash`, Debit `111.11`. Leave credit empty.
3. Click **Save & post**.

☐ Expected: the **popup stays open**, an error message shows inside the dialog
(e.g. totals-out-of-balance) — a styled error, **not** a browser `alert()`.
☐ Expected: nothing was saved — the backend must refuse to post unbalanced.

### A5. Balanced entry posts

1. Line 2: Account `6000 General Operating Expenses`, Credit `111.11`.
2. Balance bar now shows `Debit $111.11 / Credit $111.11 / Balanced`.
3. Click **Save & post**.

☐ Expected: popup closes; a draft transaction appears in the Transactions table
with status `POSTED`, Source `Manual`, and the header reference/description you
entered.

### A6. Create, edit, and re-post a draft (the cloneNode regression)

1. Click **+ New journal entry** again; fill header (Transaction number
   `QA-MANUAL-2`, date, description).
2. Add one line: `1000 Cash` Debit `22.22`; add a second line: `6000` Credit
   `22.22`. Click **Save draft** (not post).
3. Confirm the row appears with status `DRAFT`.
4. Click **Edit** on that draft row.

☐ Expected: the **popup reopens fully populated** — header fields AND both line
rows loaded (this is the `cloneNode` regression — it previously threw
`Cannot read properties of null (reading 'cloneNode')` and showed a native alert
instead of a popup).
5. Change the Debit on line 1 to `33.33` and the Credit on line 2 to `33.33`.
6. Click **Save & post**.

☐ Expected: the draft is posted; totals are `33.33` on both sides.

### A7. System entries are read-only with a Source

Trigger an automatic entry (see Section B) and come back to `/accounting/`.

1. Reload `/accounting/`.
2. Click the row of an auto-generated entry (e.g. from an expense/invoice).

☐ Expected: the detail dialog shows a **Source** field identifying the origin
(e.g. `Expense #…`, `Client Invoice #…`, `Payment #…`).
☐ Expected: auto/system entries have **no Edit/Post/Delete actions** (view-only).

### A8. Posting fails cleanly when a line has no amount

Create a draft, leave the header filled but keep all line blanks, and try to
post it.

☐ Expected: refused with a clear message ("at least one line" / no-lines error)
— never a `500`, and never a silent no-op.

---

## B. Full business loop → auto GL journal entries

This is the CPMAS-34/35 integration: real transactions post automatic,
balanced journal entries.

Distinct amount convention (so you can find your entries later):

| Module | Amount |
| --- | --- |
| Expense | `50.00` |
| Supplier invoice | `1,200.00` (tax `120.00`) |
| Client invoice | `5,000.00` (tax `500.00`) |

### B1. Partners: a client

1. `/partners/` → add a client `QA Client Co`.
2. `/suppliers/` → add a supplier `QA Supply Co`.
3. `/contractors/` → add a contractor `QA Build Ltd`.

☐ Expected: each list page shows the record after saving. (Navigation: use the
sidebar "+" or the New button on each page.)

### B2. Project

1. `/projects/` → **New project** `QA Tower`, with the above client as owner.
2. Open the project detail (click it) — it shows overview/phases/budget tabs.

☐ Expected: project appears; detail page renders without errors.

### B3. Expense (paid) → expense auto journal

1. `/expenses/` → **New expense** on `QA Tower`: category (create one if empty,
   e.g. `Travel`, and link the category's default account = `6000`), amount
   `50.00`, date today.
2. Mark the expense **Paid**.

☐ Expected: a journal entry appears in `/accounting/` with the inspected
amounts: Debit `6000 General Operating Expenses` and Credit `1000 Cash`,
`50.00` each, Source = the expense, and the expense's unlinked category would
raise an error if a category has **no** account (test one unlinked category in
B5).

### B4. Supplier invoice (sent) → payable auto journal

1. `/invoices/` → new **Supplier invoice** for `QA Supply Co` on `QA Tower`:
   line(s) `1,200.00` + tax `120.00`.
2. Approve and mark the invoice **Sent**.

☐ Expected: in `/accounting/`, an entry books `5000 Cost of Construction` Debit
`1,320.00` (`1,200 + 120` VAT in) and `2000 Accounts Payable` Credit
`1,320.00`, Source = the supplier invoice.

### B5. Unlinked expense category raises instead of booking

Create an expense category **without** a default account, then mark an expense
in it Paid.

☐ Expected: posting is refused with an error naming the unlinked category —
never a silent omission.

### B6. Client invoice (sent) → receivable auto journal

1. `/invoices/` → new **Client invoice** to `QA Client Co` on `QA Tower`:
   `5,000.00` + tax `500.00`.
2. Mark it **Sent**.

☐ Expected: in `/accounting/`, an entry books `1100 Accounts Receivable` Debit
`5,500.00`, `4000 Construction Revenue` Credit `5,000.00`, `2100 Tax Payable`
Credit `500.00`, Source = the client invoice.

### B7. Payment against the supplier invoice (outgoing) → rebook

1. `/payments/` → **New payment** for `QA Supply Co`: type **Outgoing**, amount
   `1,320.00`, allocate it 100% to the supplier invoice from B4. Save.

☐ Expected: in `/accounting/` a new entry appears (or the previous one is
replaced per the re-allocation rule): Debit `2000 Accounts Payable`
`1,320.00` and Credit `1000 Cash` `1,320.00`, Source = the payment.
☐ Expected: exactly **one** live journal entry exists for that payment — repeat
the allocation a second time and confirm the previous entry was voided and
rebooked (no duplicates).

### B8. Receipt from the client → never books

1. `/payments/` → **New receipt** from `QA Client Co`: type **Incoming**
   (receipt), `500.00`.

☐ Expected: **no** journal entry is created in `/accounting/` for the receipt —
receipts never book automatically.

### B9. Contractor invoice smoke

Optional (equipment/contractor path): create a contractor invoice on `QA Tower`
and mark it Sent.

☐ Expected: an entry on the books similar to B4 (DR `5000` / CR `2000`) with
Source = the contractor invoice.

---

## C. Broad page smoke (every module)

Open each URL logged-in as Owner and check it renders without errors; then
exercise the primary list action (New → save → item appears).

| # | Module | URL | Smoke check |
| --- | --- | --- | --- |
| 1 | Overview | `/dashboard/` | Cards/stats render; recent activity loads |
| 2 | Projects | `/projects/` | List renders; detail opens |
| 3 | Approvals | `/approvals/` | Pending approvals panel loads |
| 4 | Clients & partners | `/partners/` | Client from B1 listed |
| 5 | Suppliers | `/suppliers/` | Supplier from B1 listed |
| 6 | Procurement | `/procurement/` | PO list renders; New PO dialog opens |
| 7 | Inventory | `/inventory/` | Materials/warehouses/stock tabs render |
| 8 | Workforce | `/workforce/` | Employees/attendance tabs render |
| 9 | Documents | `/documents/` | List loads |
| 10 | Invoices | `/invoices/` | Invoices from B4/B6 listed |
| 11 | Payments | `/payments/` | Payment/receipt from B7/B8 listed |
| 12 | Accounting | `/accounting/` | Section A + B entries visible |
| 13 | Receipts | `/receipts/` | Page loads |
| 14 | Expenses | `/expenses/` | Expense from B3 listed |
| 15 | Reports | `/reports/` | Tabs render; open a Trial Balance / General Ledger for an account — totals match Section B |
| 16 | Settings | `/settings/` | Company profile form loads |
| 17 | Profile | `/profile/` | Own profile loads |
| 18 | Audit trail (API) | `/api/audit/audit-logs/` | Read-only log lists the actions from A & B |

For each:

☐ Page renders (no 500s in the console/network tab).
☐ Primary New/＋ action works.
☐ Sidebar highlights the current module.

Note: `workforce` has a **known pre-existing test failure** in `core.tests`
(`data-workforce-*` vs `data-employee-rows`) — it still renders fine in the
browser; the failing unit is unrelated to page rendering.

---

## D. API smoke (authenticated)

Log in and confirm the main resources respond (list = 200, empty list OK).
You can use the DRF browsable API or a REST client with the session cookie.

| Endpoint | Expected |
| --- | --- |
| `GET /api/accounting/accounts/` | 200, 7 seeded accounts |
| `GET /api/accounting/financial-transactions/` | 200, entries from A & B |
| `GET /api/accounting/transaction-lines/` | 200, balanced lines |
| `GET /api/accounting/reports/profit-loss/` | 200 (P&L summary) |
| `GET /api/accounting/reports/trend/` | 200 (balances trend) |
| `GET /api/projects/projects/` | 200, `QA Tower` |
| `GET /api/clients/clients/` | 200 |
| `GET /api/suppliers/suppliers/` | 200 |
| `GET /api/contractors/contractors/` | 200 |
| `GET /api/expenses/expenses/` | 200 |
| `GET /api/invoicing/supplier-invoices/` | 200 |
| `GET /api/invoicing/client-invoices/` | 200 |
| `GET /api/payments/payments/` | 200 |
| `GET /api/payments/receipts/` | 200 |
| `GET /api/inventory/materials/` | 200 |
| `GET /api/purchasing/purchase-orders/` | 200 |
| `GET /api/employees/` | 200 |
| `GET /api/audit/audit-logs/` | 200, read-only |
| `GET /api/company/` | 200, company profile |
| `GET /api/auth/me/` | 200, current user |

---

## E. Regression checklist (things that used to break)

Done these after clearing the browser cache / hard refresh (`Ctrl+F5`):

- [ ] New journal entry button always opens the modal popup (was: dead button).
- [ ] Posting a balanced entry works (was: `Cannot post a financial transaction
      with no lines`).
- [ ] Editing a draft loads its lines (was: `Cannot read properties of null
      (reading 'cloneNode')`).
- [ ] Posting an unbalanced/invalid entry shows a styled in-dialog error (was:
      native `alert` / nothing visible).
- [ ] The accounting script loads with the cache-buster
      (`accounting.js?v=20260907-dialog`).
- [ ] System (auto) entries are view-only with a Source label.

## Cleanup (if you care)

Delete the QA records via the UI, or reset a local dev database:

```powershell
python manage.py migrate accounting zero
python manage.py migrate
```