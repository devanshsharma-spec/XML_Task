import xml.etree.ElementTree as ET
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
)
from reportlab.lib.styles import getSampleStyleSheet
import pikepdf


def find_text(node, path, default=""):
    found = node.find(path)
    if found is not None and found.text:
        return found.text.strip()
    return default


def parse_invoice_xml(xml_path):
    tree = ET.parse(xml_path)
    root = tree.getroot()

    invoice = root.find(".//Invoice")
    if invoice is None:
        raise ValueError("Could not find <Invoice> node in XML.")

    data = {
        "invoice_number": find_text(invoice, "InvoiceNumber", "N/A"),
        "invoice_date": find_text(invoice, "InvoiceDate", "N/A"),
        "client_number": find_text(invoice, "ClientNumber", ""),
        "matter_reference": find_text(invoice, "MatterReference", ""),
        "federal_tax_id": find_text(invoice, "FederalTaxId", ""),
        "vendor_name": find_text(invoice, "Vendor/Name", "N/A"),
        "vendor_address_1": find_text(invoice, "Vendor/AddressLine1", ""),
        "vendor_city": find_text(invoice, "Vendor/City", ""),
        "vendor_state": find_text(invoice, "Vendor/State", ""),
        "vendor_postal": find_text(invoice, "Vendor/PostalCode", ""),
        "vendor_phone": find_text(invoice, "Vendor/Phone", ""),
        "vendor_website": find_text(invoice, "Vendor/Website", ""),
        "billto_name": find_text(invoice, "BillTo/Name", "N/A"),
        "billto_careof": find_text(invoice, "BillTo/CareOf", ""),
        "billto_address_1": find_text(invoice, "BillTo/AddressLine1", ""),
        "billto_address_2": find_text(invoice, "BillTo/AddressLine2", ""),
        "billto_city": find_text(invoice, "BillTo/City", ""),
        "billto_state": find_text(invoice, "BillTo/State", ""),
        "billto_postal": find_text(invoice, "BillTo/PostalCode", ""),
        "attention": find_text(invoice, "BillTo/Attention", ""),
        "currency": find_text(invoice, "Currency", "USD"),
        "current_invoice_amount": find_text(invoice, "Totals/CurrentInvoiceAmount", ""),
        "balance_due": find_text(invoice, "Totals/BalanceDue", ""),
        "please_remit": find_text(invoice, "Totals/PleaseRemit", ""),
        "current_invoice_hours": find_text(invoice, "Totals/CurrentInvoiceHours", ""),
    }

    line_items = []
    for i, item in enumerate(invoice.findall(".//LineItems/LineItem"), start=1):
        line_items.append({
            "line_number": find_text(item, "LineNumber", str(i)),
            "service_date": find_text(item, "ServiceDate", ""),
            "timekeeper_code": find_text(item, "TimekeeperCode", ""),
            "timekeeper_name": find_text(item, "TimekeeperName", ""),
            "description": find_text(item, "Description", ""),
            "quantity": find_text(item, "Quantity", ""),
            "unit_price": find_text(item, "UnitPrice", ""),
            "line_amount": find_text(item, "LineAmount", ""),
            "category": find_text(item, "Category", ""),
        })

    return data, line_items


def create_pdf_from_xml(xml_path, output_pdf):
    data, line_items = parse_invoice_xml(xml_path)

    doc = SimpleDocTemplate(
        output_pdf,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("Invoice", styles["Title"]))
    elements.append(Spacer(1, 6))

    # Header table
    header_rows = [
        ["Invoice No", data["invoice_number"], "Invoice Date", data["invoice_date"]],
        ["Client Number", data["client_number"], "Matter", data["matter_reference"]],
        ["Tax ID", data["federal_tax_id"], "Currency", data["currency"]],
        ["Current Invoice Amount", data["current_invoice_amount"], "Balance Due", data["balance_due"]],
    ]

    header_table = Table(header_rows, colWidths=[35*mm, 55*mm, 40*mm, 45*mm])
    header_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
        ("BACKGROUND", (2, 0), (2, -1), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 10))

    # Vendor / Bill To
    vendor_lines = [
        data["vendor_name"],
        data["vendor_address_1"],
        " ".join(x for x in [data["vendor_city"], data["vendor_state"], data["vendor_postal"]] if x),
        f"Phone: {data['vendor_phone']}" if data["vendor_phone"] else "",
        data["vendor_website"],
    ]
    vendor_text = "<br/>".join(line for line in vendor_lines if line)

    billto_lines = [
        data["billto_name"],
        data["billto_careof"],
        data["billto_address_1"],
        data["billto_address_2"],
        " ".join(x for x in [data["billto_city"], data["billto_state"], data["billto_postal"]] if x),
        f"Attention: {data['attention']}" if data["attention"] else "",
    ]
    billto_text = "<br/>".join(line for line in billto_lines if line)

    party_table = Table(
        [
            [
                Paragraph("<b>Vendor</b><br/>" + vendor_text, styles["BodyText"]),
                Paragraph("<b>Bill To</b><br/>" + billto_text, styles["BodyText"]),
            ]
        ],
        colWidths=[90 * mm, 90 * mm],
    )
    party_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(party_table)
    elements.append(Spacer(1, 10))

    # Line items
    table_data = [[
        "Date", "TK", "Description", "Hours", "Rate", "Amount"
    ]]

    for item in line_items:
        table_data.append([
            item["service_date"],
            item["timekeeper_code"],
            Paragraph(item["description"], styles["BodyText"]),
            item["quantity"],
            item["unit_price"],
            item["line_amount"],
        ])

    line_table = Table(
        table_data,
        colWidths=[22*mm, 14*mm, 86*mm, 18*mm, 22*mm, 24*mm]
    )
    line_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4F81BD")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (3, 1), (5, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(line_table)
    elements.append(Spacer(1, 10))

    # Totals
    totals_rows = [
        ["Current Invoice Hours", data["current_invoice_hours"]],
        ["Current Invoice Amount", data["current_invoice_amount"]],
        ["Please Remit", data["please_remit"] or data["balance_due"]],
    ]
    totals_table = Table(totals_rows, colWidths=[60*mm, 35*mm], hAlign="RIGHT")
    totals_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    elements.append(totals_table)

    doc.build(elements)


def embed_xml_into_pdf(input_pdf_path, xml_path, output_pdf_path, embedded_name=None):
    embedded_name = embedded_name or Path(xml_path).name

    with pikepdf.open(input_pdf_path) as pdf:
        with open(xml_path, "rb") as f:
            pdf.attachments[embedded_name] = f.read()

        pdf.docinfo["/EmbeddedXML"] = embedded_name
        pdf.docinfo["/Producer"] = "ReportLab + pikepdf"
        pdf.save(output_pdf_path)


def xml_to_embedded_pdf(xml_path, generated_pdf_path="generated_invoice.pdf", final_pdf_path="final_invoice_with_xml.pdf"):
    create_pdf_from_xml(xml_path, generated_pdf_path)
    embed_xml_into_pdf(generated_pdf_path, xml_path, final_pdf_path)
    print("Generated PDF:", generated_pdf_path)
    print("Embedded XML PDF:", final_pdf_path)


if __name__ == "__main__":
    xml_to_embedded_pdf("invoice.xml")
