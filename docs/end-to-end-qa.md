# End-to-End Project Workflow — Manual Test Walkthrough

A single story you can follow start-to-finish to test the whole system like a
real user. Same as real life: build the project, buy materials, get the client
to pay, and watch the accounting book itself.

**Scenario: "Downtown Fit-out"**
A fit-out project for a client, using one supplier and one contractor. All the
numbers below were chosen so the GL (general ledger) checks out exactly at the
end.

## Before you start

- Server running: `python manage.py runserver`
- Migrations applied (`python manage.py migrate`)
- Logged in as an **Owner** account (so all sidebar sections are visible).
- The Accounting page must show the 7 seeded accounts (they are created
  automatically by migration `0002`).

> Tip: use the sidebar to jump between sections. Each step below says which
> sidebar item to open.

---

## Phase 1 — The basics (registration, setup)

### Step 1 · Company profile

**Sidebar → Settings**

Set your company name/logo/address. This is the company that appears on
invoices later.

**You should see:** the profile form saves and the sidebar shows your logo/name.

### Step 2 · Client

**Sidebar → Clients & partners**

Create a client:

| Field | Value |
| --- | --- |
| Name | `Al Manar Trading LLC` |
| Phone | `+971 50 111 2222` |
| Email | `accounts@almanar.ae` |
| Address | `Deira, Dubai` |

**You should see:** the client appears in the list.

### Step 3 · Supplier

**Sidebar → Suppliers**

Create a supplier:

| Field | Value |
| --- | --- |
| Name | `Gulf Building Materials` |
| Phone | `+971 4 333 4444` |
| Email | `sales@gulfbm.com` |

**You should see:** the supplier appears in the list.

### Step 4 · Contractor

**Sidebar → Contractors** (also accessible under Clients & partners)

Create a contractor:

| Field | Value |
| --- | --- |
| Name | `Skyline Interiors LLC` |
| Contact | `Eng. Omar Mahmoud` |

**You should see:** the contractor appears in the list.

---

## Phase 2 — The project

### Step 5 · Create the project

**Sidebar → Projects → New project**

| Field | Value |
| --- | --- |
| Name | `Downtown Fit-out` |
| Code | `FIT-2026` |
| Client | `Al Manar Trading LLC` |
| Budget | `120000.00` |
| Start date | today |
| End date | today + 90 days |

**You should see:** the project appears in the list. Click it → the detail page
shows overview/phases/budget tabs. Add one phase:

| Field | Value |
| --- | --- |
| Phase name | `Interior fit-out works` |
| Budget | `120000.00` |

---

## Phase 3 · Workforce

### Step 6 · Employee

**Sidebar → Workforce → Employees**

Create an employee:

| Field | Value |
| --- | --- |
| Name | `Ahmed Hassan` |
| Role | `Foreman` |
| Phone | `+971 55 000 1111` |

**You should see:** the employee listed; the attendance/daily-labor tabs load.

---

## Phase 4 · Materials & purchase order (procurement / inventory)

Pretend we need ceiling tiles for the fit-out.

### Step 7 · Material catalog + warehouse

**Sidebar → Inventory**

1. Create a material category: name `Ceiling Materials`.
2. Create a material: name `Suspended Ceiling Tile`, unit `m²`, price `40.00`,
   category `Ceiling Materials`.
3. Create a warehouse: name `Main Warehouse`.

**You should see:** tile is listed with its unit price; warehouse is listed.

### Step 8 · Purchase order to the supplier

**Sidebar → Procurement → New purchase order**

| Field | Value |
| --- | --- |
| Supplier | `Gulf Building Materials` |
| Project | `Downtown Fit-out` |
| Line: material | `Suspended Ceiling Tile` |
| Line: quantity | `200` |
| Line: price | `40.00` |

**You should see:** PO total = `8,000.00`. Save it.

### Step 9 · Receive the goods → stock in

On the PO row, do the **Receipt/Receive goods** action for `200 m²` of tiles.

**You should see:** a goods receipt is created and **Stock** for
`Suspended Ceiling Tile` in `Main Warehouse` increases to `200`.

---

## Phase 5 · Day-to-day expenses

### Step 10 · Expense for the site visit

**Sidebar → Expenses**

1. **Create the category first** — the Expenses page has no button for this;
   categories live in Django Admin:

   > Open `/admin/expenses/expensecategory/add/` in a new tab and log in with
   > the superuser you created (`python manage.py createsuperuser`). Create:
   >
   > | Field | Value |
   > | --- | --- |
   > | Name | `Travel` |
   > | Account | `6000 General Operating Expenses` (autocomplete) |
   > | Description | `Site visits and transport` |
   >
   > (Alternative: `POST /api/expenses/expense-categories/` with
   > `{"name": "Travel", "account": "<id of account 6000>"}`.)
   >
   > This `account` link is what lets the expense auto-post to the books.

2. New expense:

| Field | Value |
| --- | --- |
| Category | `Travel` |
| Project | `Downtown Fit-out` |
| Description | `Site transport` |
| Amount | `150.00` |
| Date | today |

3. Mark the expense **Paid**.

**You should see:** nothing on this page, but — jump to Sidebar → **Accounting**:

A journal entry appeared, Source = the expense:
- Debit `6000 General Operating Expenses` **150.00**
- Credit `1000 Cash` **150.00**

> This is the automatic GL booking (CPMAS-35). The expense didn't ask you for
> accounts — the category's account did it.

---

## Phase 6 · Buying materials (supplier invoice)

### Step 11 · Supplier invoice

**Sidebar → Invoices → New supplier invoice**

| Field | Value |
| --- | --- |
| Supplier | `Gulf Building Materials` |
| Project | `Downtown Fit-out` |
| Line: item | `Suspended Ceiling Tiles` |
| Line: amount | `8000.00` |
| Tax (5%) | `400.00` |

Mark/approve it and set status **Sent**.

**You should see in Accounting:**
- Debit `5000 Cost of Construction` **8,400.00**
- Credit `2000 Accounts Payable` **8,400.00**  (8,000 + 400 tax)

Source = the supplier invoice.

---

## Phase 7 · Billing the client (client invoice)

### Step 12 · Client invoice

**Sidebar → Invoices → New client invoice**

| Field | Value |
| --- | --- |
| Client | `Al Manar Trading LLC` |
| Project | `Downtown Fit-out` |
| Line: item | `Fit-out progress 1` |
| Line: amount | `20000.00` |
| Tax (5%) | `1000.00` |

Set status **Sent**.

**You should see in Accounting:**
- Debit `1100 Accounts Receivable` **21,000.00**
- Credit `4000 Construction Revenue` **20,000.00**
- Credit `2100 Tax Payable` **1,000.00**

Source = the client invoice. (The tax payable is your VAT owed on the sale.)

### Step 13 · Contractor invoice (finishing works)

**Sidebar → Invoices → New contractor invoice**

| Field | Value |
| --- | --- |
| Contractor | `Skyline Interiors LLC` |
| Project | `Downtown Fit-out` |
| Line: item | `Finishing works` |
| Line: amount | `12000.00` |
| Tax (5%) | `600.00` |

Set status **Sent**.

**You should see in Accounting:**
- Debit `5000 Cost of Construction` **12,600.00**
- Credit `2000 Accounts Payable` **12,600.00**

---

## Phase 8 · Money moving (payments & receipts)

### Step 14 · Pay the supplier (partially)

**Sidebar → Payments → New payment**

| Field | Value |
| --- | --- |
| Type | Outgoing |
| Pay to | `Gulf Building Materials` |
| Method | `Bank transfer` |
| Amount | `4200.00` |
| Allocate to | the supplier invoice (8,400) — `4,200.00` (half) |

Save.

**You should see in Accounting:** the supplier-invoice entry now has a matching
payment entry:
- Debit `2000 Accounts Payable` **4,200.00**
- Credit `1000 Cash` **4,200.00**

Source = the payment, and it points to the invoice's project.

> If you allocate again to the same invoice, the old payment entry is voided and
> rebooked — never two live books entries for one payment.

### Step 15 · Client pays you (receipt)

**Sidebar → Payments → New payment**

| Field | Value |
| --- | --- |
| Type | Incoming (receipt) |
| From | `Al Manar Trading LLC` |
| Method | `Bank transfer` |
| Amount | `10500.00` (half of the 21,000 invoice) |

Save.

**You should see in Accounting:** **no** journal entry appears for the receipt —
receipts don't post automatically (books entry happens when you later allocate).

---

## Phase 9 · Manual accounting work (journal entry)

### Step 16 · A manual journal entry (what an accountant types by hand)

**Sidebar → Accounting → New journal entry**

- Header: number `JRN-001`, date today, description `Bank service charges`.
- Line 1: account `6000 General Operating Expenses`, Debit `25.00`
- Line 2: account `1000 Cash`, Credit `25.00`
- Balance bar shows `Balance: Balanced` → **Save & post**.

**You should see:** the popup closes and the entry shows with status
`POSTED`, Source `Manual`.

> This is also the page that was fixed recently — the dialog always opens, lines
> add/remove, unpaid entries get a styled error instead of a browser alert, and
> drafts can be edited and re-posted.

---

## Phase 10 · The end result — reports

### Step 17 · Check the general ledger

**Sidebar → Accounting**

You should have entries whose Sources are: the Travel expense, the supplier
invoice, the client invoice, the contractor invoice, the payment, and Manual.

### Step 18 · Financial reports

**Sidebar → Reports**

Open the **Profit & Loss** (and/or ledger). It should match exactly:

| Account | Balance |
| --- | --- |
| `4000 Construction Revenue` | Credit **20,000.00** |
| `5000 Cost of Construction` | Debit **21,000.00** (8,400 + 12,600) |
| `6000 General Operating Expenses` | Debit **175.00** (150 + 25) |

Balances sheet side:

| Account | Balance |
| --- | --- |
| `1000 Cash` | Credit **4,375.00** (150 + 4,200 + 25) |
| `1100 Accounts Receivable` | Debit **21,000.00** |
| `2000 Accounts Payable` | Credit **16,800.00** (8,400 + 12,600 − 4,200 paid) |
| `2100 Tax Payable` | Credit **1,000.00** |

Total debits = 21,000 + 21,000 + 175 = **42,175**.
Total credits = 4,375 + 16,800 + 1,000 + 20,000 = **42,175**. Balanced ✔

### Step 19 · Audit trail

**Sidebar → Accounting** → for any entry, open it — you'll see who/when it was
created. (Also available via the audit API `/api/audit/audit-logs/`.)

### Step 20 · System entries are protected

In Accounting, click any entry whose Source is an expense/invoice/payment (an
automatic entry). There is **no Edit/Post/Delete** button — only review. Manual
entries you created yourself do have actions.

---

## Regression check (recent Accounting fixes)

After a hard refresh (`Ctrl+F5`), run these quick checks:

- [ ] **New journal entry** always opens the modal popup.
- [ ] Unbalanced entry shows a styled error **inside the dialog** (no browser
      alert).
- [ ] **Edit** on a draft reopens the popup with its lines loaded.
- [ ] Posting works (no "Cannot post a financial transaction with no lines").
- [ ] Auto/system entries are view-only and show a **Source** label.

## Cleanup

To remove test data afterwards, delete the records through the UI, or reset a
local dev database:

```powershell
python manage.py migrate accounting zero
python manage.py migrate
```