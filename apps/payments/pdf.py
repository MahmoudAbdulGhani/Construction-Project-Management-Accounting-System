"""
Printable/downloadable receipt generation for the ``payments`` app
(CPMAS-21, BRD 5.19: "Generates printable/downloadable receipts for
recorded payments").

Kept separate from services.py: this is presentation (rendering a
Receipt to bytes), not business logic -- nothing here reads or writes
the database, it only formats an already-fetched Receipt instance plus
the company identity and party (client/supplier) it is issued to.

The layout is a professional, formally branded receipt:
+------------------ header band (company name + RECEIPT badge) -----+
| Receipt to / issued-by-block       Receipt # / date / reference    |
+-------------------------------------------------------------------+
| Payment summary table (payment #, method, date, amount)           |
| Party block (client / supplier details)                           |
| Amount due bar                                                    |
| Notes + signature line + footer (company contacts)                |
+-------------------------------------------------------------------+
"""
import io
from datetime import date
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from company.models import CompanyProfile

from contractors.models import Contractor
from employees.models import Employee

from .models import Payment, Receipt


# Brand palette (teal tones matching the Cedar Control dashboard).
_TEAL = colors.HexColor("#0a8f85")
_TEAL_DARK = colors.HexColor("#05635e")
_INK = colors.HexColor("#123f3d")
_MUTED = colors.HexColor("#607b76")
_LINE = colors.HexColor("#c2cfca")
_LIGHT_BG = colors.HexColor("#eef4f1")
_ACCENT_GOLD = colors.HexColor("#c99a2e")


def _money(value) -> str:
    """Format a Decimal as USD currency text."""
    return "${:,.2f}".format(Decimal(str(value or 0)))


def render_receipt_pdf(receipt: Receipt) -> bytes:
    """
    Render a single Receipt as a one-page branded PDF.

    Includes: company letterhead (from CompanyProfile), receipt number
    + date + reference, the issuing company and party (client/supplier)
    blocks, a payment summary, the amount, payment method, and a footer
    with company contact details.
    """
    payment = receipt.payment

    # company_details is a shared, unmanaged table (CompanyProfile has
    # managed=False) -- it exists in the live database but may not in every
    # environment/test database. The receipt must still render without it,
    # falling back to a neutral default.
    try:
        company = (
            CompanyProfile.objects.order_by("-updated_at")
            .exclude(name__isnull=True)
            .exclude(name="")
            .first()
        )
    except Exception:
        company = None

    # Resolve the transaction party. Receipts now cover both directions:
    # money received from a client (client) or paid out to a supplier /
    # employee / contractor. The unmanaged Employee/Contractor reflections
    # may be absent in some environments, so resolution is best-effort.
    party = None
    if payment.client_id:
        party = payment.client
    elif payment.supplier_id:
        party = payment.supplier
    elif payment.contractor_id:
        party = _lookup_reflection(Contractor, payment.contractor_id)
    elif payment.employee_id:
        party = _lookup_reflection(Employee, payment.employee_id)

    party_name = _display_party_name(party)
    party_sub = _display_party_sub(party)
    party_block = _display_party_block(party)
    party_heading = "RECEIVED FROM" if payment.direction == Payment.Direction.INCOMING else "PAID TO"

    styles = _make_styles()

    doc_buffer = io.BytesIO()
    page = SimpleDocTemplate(
        doc_buffer,
        pagesize=letter,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
        leftMargin=0.7 * inch,
        rightMargin=0.7 * inch,
    )

    story = []

    # ---- Brand header band ----
    header = Table(
        [
            [
                Paragraph(
                    f"<b>{_esc(company.name if company else 'Cedar Control')}</b>",
                    styles["brand"],
                ),
                Paragraph("RECEIPT", styles["receipt_badge"]),
            ]
        ],
        colWidths=[5.5 * inch, 1.5 * inch],
    )
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(header)
    story.append(Spacer(1, 4))
    # Header underline
    under = Table([[""]], colWidths=[7.0 * inch])
    under.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 2, _TEAL)]))
    story.append(under)
    story.append(Spacer(1, 16))

    # ---- Title row: receipt number vs payment summary ----
    title = Table(
        [
            [
                Paragraph(
                    (
                        f"<font color='{_MUTED.hexval()}'><b>RECEIPT NUMBER</b></font><br/>"
                        f"<font size='13' color='{_INK.hexval()}'><b>{_esc(receipt.receipt_number)}</b></font>"
                    ),
                    styles["cell"],
                ),
                Paragraph(
                    (
                        f"<font color='{_MUTED.hexval()}'><b>DATE ISSUED</b></font><br/>"
                        f"<font size='11' color='{_INK.hexval()}'><b>{_esc(_date(receipt.receipt_date))}</b></font>"
                    ),
                    styles["cell_right"],
                ),
                Paragraph(
                    (
                        f"<font color='{_MUTED.hexval()}'><b>PAYMENT</b></font><br/>"
                        f"<font size='11' color='{_INK.hexval()}'><b>{_esc(payment.payment_number)}</b></font>"
                    ),
                    styles["cell_right"],
                ),
            ]
        ],
        colWidths=[2.5 * inch, 2.5 * inch, 2.0 * inch],
    )
    title.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(title)
    story.append(Spacer(1, 18))

    # ---- Issued-to / issued-by two-column block ----
    issued_by_lines = [_esc(company.name if company else "")]
    if company:
        if company.address:
            issued_by_lines.append(_esc(company.address))
        contact = " · ".join(x for x in [company.phone, company.email] if x)
        if contact:
            issued_by_lines.append(contact)
        if company.registration_number:
            issued_by_lines.append("Reg. " + _esc(company.registration_number))

    party_lines = [_esc(party_name)]
    if party_sub:
        party_lines.append(_esc(party_sub))
    if party_block:
        party_lines.append(_esc(party_block))

    block = Table(
        [
            [
                Paragraph(party_heading, styles["label"]),
                Paragraph("ISSUED BY", styles["label"]),
            ],
            [
                Paragraph("<br/>".join(party_lines), styles["body"]),
                Paragraph("<br/>".join(issued_by_lines), styles["body"]),
            ],
        ],
        colWidths=[3.5 * inch, 3.5 * inch],
    )
    block.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("BOX", (0, 0), (-1, -1), 1, _LINE),
                ("BACKGROUND", (0, 0), (-1, -1), _LIGHT_BG),
                ("LINEAFTER", (0, 0), (0, -1), 1, _LINE),
            ]
        )
    )
    story.append(block)
    story.append(Spacer(1, 20))

    # ---- Payment summary table ----
    summary_rows = [
        [Paragraph("DESCRIPTION", styles["th"]), Paragraph("", styles["th"]), Paragraph("", styles["th"])],
        [
            Paragraph(
                f"Payment <b>{_esc(payment.payment_number)}</b> {'received' if payment.direction == Payment.Direction.INCOMING else 'paid'}",
                styles["cell"],
            ),
            Paragraph(_esc(payment.payment_method or "-"), styles["cell_center"]),
            Paragraph(f"<b>{_money(receipt.amount)}</b>", styles["cell_right"]),
        ],
    ]
    summary = Table(
        summary_rows,
        colWidths=[3.4 * inch, 1.8 * inch, 1.8 * inch],
    )
    summary.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _TEAL_DARK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, _LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(summary)
    story.append(Spacer(1, 12))

    # ---- Totals bar ----
    totals = Table(
        [
            [
                Paragraph(
                    (
                        f"<font color='{_MUTED.hexval()}'><b>PAYMENT DATE</b></font> "
                        f"<font color='{_INK.hexval()}'>{_esc(_date(payment.payment_date))}</font>"
                        f"&nbsp;&nbsp;&nbsp;"
                        f"<font color='{_MUTED.hexval()}'><b>REFERENCE</b></font> "
                        f"<font color='{_INK.hexval()}'>{_esc(receipt.reference or payment.reference or '-')}</font>"
                    ),
                    styles["cell"],
                ),
                Paragraph(
                    (
                        f"<font color='{_MUTED.hexval()}'><b>TOTAL PAID</b></font><br/>"
                        f"<font size='16' color='{_TEAL_DARK.hexval()}'><b>{_money(receipt.amount)}</b></font>"
                    ),
                    styles["cell_right"],
                ),
            ]
        ],
        colWidths=[4.6 * inch, 2.4 * inch],
    )
    totals.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _LIGHT_BG),
                ("BOX", (0, 0), (-1, -1), 1, _LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story.append(totals)

    # ---- Notes / reference ----
    if payment.notes:
        story.append(Spacer(1, 14))
        notes = Table(
            [[Paragraph(f"<b>Notes</b><br/>{_esc(payment.notes)}", styles["body"])]],
            colWidths=[7.0 * inch],
        )
        notes.setStyle(
            TableStyle(
                [
                    ("LINEABOVE", (0, 0), (-1, -1), 0.5, _LINE),
                    ("TOPPADDING", (0, 0), (-1, -1), 10),
                ]
            )
        )
        story.append(notes)

    story.append(Spacer(1, 40))

    # ---- Signature / acknowledgement ----
    if payment.direction == Payment.Direction.INCOMING:
        ack_text = (
            "<font size='9' color='%s'>Thank you. This receipt acknowledges "
            "receipt of the above payment from %s.</font>" % (_MUTED.hexval(), _esc(party_name))
        )
    else:
        ack_text = (
            "<font size='9' color='%s'>This receipt acknowledges payment of the "
            "above amount to %s.</font>" % (_MUTED.hexval(), _esc(party_name))
        )
    ack = Paragraph(ack_text, styles["body"])
    story.append(ack)
    story.append(Spacer(1, 40))

    sig = Table(
        [
            [
                Paragraph("", styles["body"]),
                Paragraph("Authorized signature", styles["label_right"]),
            ]
        ],
        colWidths=[4.0 * inch, 3.0 * inch],
    )
    sig.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (1, 0), (1, 0), 0.75, _INK),
                ("BOTTOMPADDING", (1, 0), (1, 0), 4),
                ("TOPPADDING", (1, 0), (1, 0), 28),
            ]
        )
    )
    story.append(sig)

    # ---- Footer ----
    footer_lines = []
    if company:
        bits = [x for x in [company.name, company.phone, company.email, company.website] if x]
        footer_lines.append(" · ".join(bits))
    footer_lines.append(f"Receipt {receipt.receipt_number} · Generated {_date(date.today())}")
    footer = Paragraph(" | ".join(_esc(x) for x in footer_lines), styles["footer"])
    story.append(Spacer(1, 20))
    story.append(footer)

    page.build(story)
    return doc_buffer.getvalue()


# --------------------------------------------------------------------------- #
# Small presentation helpers
# --------------------------------------------------------------------------- #

def _esc(value):
    """Escape text for reportlab Paragraph markup."""
    return (
        (value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _date(value) -> str:
    """Render a date as a display string, tolerating str/date."""
    if not value:
        return "-"
    if isinstance(value, str):
        return value
    return value.isoformat()


def _display_party_name(party) -> str:
    """Best display name for the party (client/supplier)."""
    if party is None:
        return "-"
    company_name = getattr(party, "company_name", None)
    return company_name or party.name


def _lookup_reflection(model, pk):
    """
    Fetch one row from an unmanaged reflection (Contractor/Employee),
    returning None if the table is absent (test/alternate environments)
    or the row doesn't exist.
    """
    try:
        return model.objects.filter(pk=pk).first()
    except Exception:
        return None


def _display_party_sub(party) -> str:
    """Secondary name line when company_name differs from name."""
    if party is None:
        return ""
    company_name = getattr(party, "company_name", None)
    name = party.name
    if company_name and company_name != name:
        return name
    return ""


def _display_party_block(party) -> str:
    """Multiline contact details (address / phone / email) for a party."""
    if party is None:
        return ""
    lines = []
    if getattr(party, "address", None):
        lines.append(party.address)
    contact = " · ".join(x for x in [party.phone, party.email] if x)
    if contact:
        lines.append(contact)
    return "\n".join(lines)


def _make_styles():
    sample = getSampleStyleSheet()
    base = sample["Normal"]
    return {
        "brand": ParagraphStyle(
            "brand",
            parent=base,
            fontName="Helvetica-Bold",
            fontSize=20,
            textColor=_INK,
            leading=22,
        ),
        "receipt_badge": ParagraphStyle(
            "receipt_badge",
            parent=base,
            fontName="Helvetica-Bold",
            fontSize=15,
            textColor=colors.white,
            alignment=TA_RIGHT,
            backColor=_TEAL,
            borderPadding=(4, 8, 4, 8),
            leading=20,
        ),
        "label": ParagraphStyle(
            "label",
            parent=base,
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=_MUTED,
            leading=10,
        ),
        "label_right": ParagraphStyle(
            "label_right",
            parent=base,
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=_MUTED,
            alignment=TA_RIGHT,
            leading=10,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base,
            fontName="Helvetica",
            fontSize=10,
            textColor=_INK,
            leading=14,
        ),
        "cell": ParagraphStyle(
            "cell",
            parent=base,
            fontName="Helvetica",
            fontSize=10,
            textColor=_INK,
            leading=13,
        ),
        "cell_right": ParagraphStyle(
            "cell_right",
            parent=base,
            fontName="Helvetica",
            fontSize=10,
            textColor=_INK,
            alignment=TA_RIGHT,
            leading=13,
        ),
        "cell_center": ParagraphStyle(
            "cell_center",
            parent=base,
            fontName="Helvetica",
            fontSize=10,
            textColor=_INK,
            alignment=1,
            leading=13,
        ),
        "th": ParagraphStyle(
            "th",
            parent=base,
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=colors.white,
            leading=10,
        ),
        "footer": ParagraphStyle(
            "footer",
            parent=base,
            fontName="Helvetica",
            fontSize=7.5,
            textColor=_MUTED,
            alignment=1,
            leading=10,
        ),
    }
