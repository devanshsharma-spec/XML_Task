import argparse
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pdfplumber
import pikepdf
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


VENDOR_DEFAULTS = {
    "name": "Hellmuth & Johnson",
    "address_1": "8050 West 78th Street",
    "city": "Edina",
    "state": "MN",
    "postal": "55439",
    "phone": "952-941-4005",
    "fax": "952-941-2337",
    "website": "www.hjlawfirm.com",
}

GREENSTEIN_DEFAULTS = {
    "name": "Greenstein Sellers PLLC",
    "address_1": "121 South 8th Street, Suite 1450",
    "city": "Minneapolis",
    "state": "MN",
    "postal": "55402",
    "phone": "",
    "fax": "",
    "website": "",
}

CARLSON_DEFAULTS = {
    "name": "Carlson & Associates, Ltd.",
    "address_1": "1052 Centerville Circle",
    "city": "Vadnais Heights",
    "state": "MN",
    "postal": "55127",
    "phone": "(651) 287-8640",
    "fax": "",
    "website": "",
}


def find_text(node, path, default=""):
    found = node.find(path)
    if found is not None and found.text:
        return found.text.strip()
    return default


def clean_amount(value):
    return value.replace("$", "").replace(",", "").strip()


def money_or_blank(value):
    return value.strip() if value else ""


def parse_city_state_postal(line):
    match = re.match(r"^(.*?),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)$", line.strip())
    if not match:
        return "", "", ""
    return match.group(1).strip(), match.group(2).strip(), match.group(3).strip()


def extract_pdf_text(pdf_path):
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return "\n".join(page for page in pages if page.strip())


def extract_field(pattern, text, default=""):
    match = re.search(pattern, text, re.MULTILINE)
    return match.group(1).strip() if match else default


def parse_billto(lines):
    cleaned = [line.strip() for line in lines if line.strip()]
    city = state = postal = ""
    if cleaned and re.search(r",\s*[A-Z]{2}\s+\d{5}", cleaned[-1]):
        city, state, postal = parse_city_state_postal(cleaned[-1])
        cleaned = cleaned[:-1]

    careof = ""
    if cleaned:
        for line in list(cleaned):
            if line.lower().startswith("c/o"):
                careof = line
                cleaned.remove(line)
                break

    attention = ""
    name = cleaned[0] if cleaned else ""
    if len(cleaned) >= 2:
        first = cleaned[0].lower()
        second = cleaned[1].lower()
        organization_markers = ("association", "hoa", "condominium", "condo", "llc", "inc.", "inc", "family")
        if not any(marker in first for marker in organization_markers) and any(
            marker in second for marker in organization_markers
        ):
            attention = cleaned[0]
            name = cleaned[1]
            cleaned = cleaned[2:]
        else:
            cleaned = cleaned[1:]
    else:
        cleaned = cleaned[1:]

    address_1 = cleaned[0] if cleaned else ""
    address_2 = cleaned[1] if len(cleaned) > 1 else ""
    return {
        "name": name,
        "careof": careof,
        "attention": attention,
        "address_1": address_1,
        "address_2": address_2,
        "city": city,
        "state": state,
        "postal": postal,
    }


def parse_billto_greenstein(lines):
    cleaned = [line.strip() for line in lines if line.strip()]
    city = state = postal = ""
    if cleaned and re.search(r",\s+[A-Za-z ]+\s+\d{5}", cleaned[-1]):
        match = re.match(r"^(.*?),\s*([A-Za-z ]+)\s+(\d{5}(?:-\d{4})?)$", cleaned[-1])
        if match:
            city, state, postal = match.group(1).strip(), match.group(2).strip(), match.group(3).strip()
            cleaned = cleaned[:-1]

    careof = ""
    remaining = []
    for line in cleaned[1:]:
        if line.lower().startswith("c/o"):
            careof = line
        else:
            remaining.append(line)

    return {
        "name": cleaned[0] if cleaned else "",
        "careof": careof,
        "attention": "",
        "address_1": remaining[0] if remaining else "",
        "address_2": remaining[1] if len(remaining) > 1 else "",
        "city": city,
        "state": state,
        "postal": postal,
    }


def parse_line_items(lines):
    items = []
    current = None
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^(\d{2}/\d{2}/\d{4})\s+(\S+)\s+(.*)$", line)
        if match:
            if current:
                items.append(current)
            current = {
                "service_date": match.group(1),
                "timekeeper_code": match.group(2),
                "description_parts": [match.group(3)],
            }
            continue
        if current:
            current["description_parts"].append(line)

    if current:
        items.append(current)

    parsed = []
    for index, item in enumerate(items, start=1):
        combined = " ".join(part for part in item["description_parts"] if part)
        match = re.match(
            r"^(.*)\s+(\d[\d,]*\.\d{2})\s+(\d[\d,]*\.\d{2})\s+(\d[\d,]*\.\d{2})$",
            combined,
        )
        description = combined
        unit_price = quantity = line_amount = ""
        if match:
            description = match.group(1).strip()
            unit_price = clean_amount(match.group(2))
            quantity = clean_amount(match.group(3))
            line_amount = clean_amount(match.group(4))
        parsed.append(
            {
                "line_number": str(index),
                "service_date": item["service_date"],
                "timekeeper_code": item["timekeeper_code"],
                "timekeeper_name": "",
                "description": description,
                "quantity": quantity,
                "unit_price": unit_price,
                "line_amount": line_amount,
                "category": "Professional Services",
            }
        )
    return parsed


def parse_aged_receivables(lines):
    rows = []
    for raw_line in lines:
        line = raw_line.strip()
        match = re.match(
            r"^(\d{2}/\d{2}/\d{4})\s+(\S+)\s+(\d[\d,]*\.\d{2})\s+(\d[\d,]*\.\d{2})$",
            line,
        )
        if not match:
            continue
        rows.append(
            {
                "stmt_date": match.group(1),
                "stmt_number": match.group(2),
                "billed": clean_amount(match.group(3)),
                "due": clean_amount(match.group(4)),
            }
        )
    return rows


def parse_timekeeper_summary(lines):
    entries = []
    for raw_line in lines:
        line = raw_line.strip()
        match = re.match(r"^(.*?)\s+\$?(\d[\d,]*\.\d{2})$", line)
        if not match:
            continue
        entries.append({"name": match.group(1).strip(), "amount": clean_amount(match.group(2))})
    return entries


def parse_greenstein_line_items(lines):
    items = []
    current = None
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^(Expense|Service)\s+(\d{2}/\d{2}/\d{4})\s+(.*)$", line)
        if match:
            if current:
                items.append(current)
            current = {
                "category": match.group(1),
                "service_date": match.group(2),
                "description_parts": [match.group(3)],
            }
            continue
        if current:
            current["description_parts"].append(line)

    if current:
        items.append(current)

    parsed = []
    for index, item in enumerate(items, start=1):
        combined = " ".join(item["description_parts"])
        match = re.match(
            r"^(.*)\s+(\d[\d,]*\.\d{2})\s+\$?(\d[\d,]*\.\d{2})\s+\$?(\d[\d,]*\.\d{2})$",
            combined,
        )
        description = combined
        quantity = unit_price = line_amount = ""
        if match:
            description = match.group(1).strip()
            quantity = clean_amount(match.group(2))
            unit_price = clean_amount(match.group(3))
            line_amount = clean_amount(match.group(4))
        parsed.append(
            {
                "line_number": str(index),
                "service_date": item["service_date"],
                "timekeeper_code": item["category"],
                "timekeeper_name": "",
                "description": description,
                "quantity": quantity,
                "unit_price": unit_price,
                "line_amount": line_amount,
                "category": item["category"],
            }
        )
    return parsed


def parse_carlson_line_items(lines):
    items = []
    current = None
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^(\d{1,2}/\d{1,2}/\d{4})\s+(\S+)\s+(.*)$", line)
        if match:
            if current:
                items.append(current)
            current = {
                "service_date": match.group(1),
                "timekeeper_code": match.group(2),
                "description_parts": [match.group(3)],
            }
            continue
        if current:
            current["description_parts"].append(line)

    if current:
        items.append(current)

    parsed = []
    for index, item in enumerate(items, start=1):
        combined = " ".join(item["description_parts"])
        match = re.match(r"^(.*)\s+(\d[\d,]*\.\d{2})\s+(\d[\d,]*\.\d{2})$", combined)
        description = combined
        quantity = line_amount = ""
        if match:
            description = match.group(1).strip()
            quantity = clean_amount(match.group(2))
            line_amount = clean_amount(match.group(3))
        parsed.append(
            {
                "line_number": str(index),
                "service_date": item["service_date"],
                "timekeeper_code": item["timekeeper_code"],
                "timekeeper_name": "",
                "description": description,
                "quantity": quantity,
                "unit_price": "",
                "line_amount": line_amount,
                "category": "Professional Services",
            }
        )
    return parsed


def parse_source_pdf(pdf_path):
    text = extract_pdf_text(pdf_path)
    lines = text.splitlines()

    vendor_defaults = VENDOR_DEFAULTS
    line_items = []
    aged_rows = []
    timekeeper_summary = []
    document_type = "invoice"

    if "Greenstein Sellers PLLC" in text:
        vendor_defaults = GREENSTEIN_DEFAULTS
        invoice_date = extract_field(r"Date:\s*([0-9/]+)", text)
        tax_id = ""
        invoice_number = extract_field(r"Invoice #\s*:?\s*([^\n]+)", text)
        client_number = extract_field(r"^(\d{5}-[^\n]+)$", text)
        matter_reference = extract_field(r"^(\d{5}-[^\n]+)$", text)
        previous_balance = extract_field(r"Outstanding Balance\s+\$?([0-9,]+\.\d{2})", text)
        current_invoice_amount = extract_field(r"^Total\s+\$?([0-9,]+\.\d{2})$", text)
        balance_due = extract_field(
            r"^\S+\s+\d{2}/\d{2}/\d{4}\s+\$?[\d,]+\.\d{2}\s+\$?[\d,]+\.\d{2}\s+\$?([\d,]+\.\d{2})$",
            text,
        ) or extract_field(r"Total Amount Outstanding\s+\$?([0-9,]+\.\d{2})", text)
        please_remit = balance_due

        submitted_index = next((i for i, line in enumerate(lines) if line.strip() == "Greenstein Sellers PLLC"), None)
        matter_index = next((i for i, line in enumerate(lines) if re.match(r"^\d{5}-", line.strip())), None)
        billto = parse_billto_greenstein(lines[submitted_index + 4 : matter_index] if submitted_index is not None and matter_index is not None else [])

        item_start = next((i for i, line in enumerate(lines) if line.strip() == "Type Date Notes Quantity Rate Total"), None)
        item_end = next((i for i, line in enumerate(lines) if re.match(r"^Total\s+\$", line.strip())), None)
        if item_start is not None and item_end is not None:
            line_items = parse_greenstein_line_items(lines[item_start + 1 : item_end])

    elif "Carlson & Associates, Ltd." in text:
        vendor_defaults = CARLSON_DEFAULTS
        invoice_date = extract_field(r"^([A-Za-z]+\s+\d{1,2},\s+\d{4})", text)
        tax_id = extract_field(r"Tax ID\s*([0-9-]+)", text)
        invoice_number = extract_field(r"Invoice #\s*:?\s*([^\n]+)", text)
        client_number = ""
        matter_reference = extract_field(r"In Reference To:\s*([^\n]+)", text)
        previous_balance = extract_field(r"Previous balance\s+\$?([0-9,]+\.\d{2})", text)
        current_invoice_amount = extract_field(r"For professional services rendered\s+[0-9,]+\.\d{2}\s+\$?([0-9,]+\.\d{2})", text)
        balance_due = extract_field(r"Balance due\s+\$?([0-9,]+\.\d{2})", text)
        please_remit = balance_due

        submitted_index = next((i for i, line in enumerate(lines) if line.strip() == "Invoice submitted to:"), None)
        date_index = next((i for i, line in enumerate(lines) if re.match(r"^[A-Za-z]+\s+\d{1,2},\s+\d{4}$", line.strip())), None)
        billto = parse_billto(lines[submitted_index + 1 : date_index] if submitted_index is not None and date_index is not None else [])

        item_start = next((i for i, line in enumerate(lines) if line.strip() == "Hours Amount"), None)
        item_end = next((i for i, line in enumerate(lines) if line.startswith("For professional services rendered")), None)
        if item_start is not None and item_end is not None:
            line_items = parse_carlson_line_items(lines[item_start + 1 : item_end])

    else:
        invoice_date = extract_field(r"^([A-Za-z]+\s+\d{1,2},\s+\d{4})", text)
        tax_id = extract_field(r"Federal Tax ID No\.\s*:?\s*([0-9-]+)", text)
        invoice_number = extract_field(r"Invoice #:\s*([^\n]+)", text)
        client_number = extract_field(r"Client Number:\s*([^\n]+)", text)
        matter_reference = extract_field(r"In Reference To:\s*([^\n]+)", text)
        previous_balance = extract_field(r"Previous balance\s+\$?([0-9,]+\.\d{2})", text)
        balance_due = extract_field(
            r"Balance due \(Previous Balance \+ Current Invoice Amounts\)\s+\$?([0-9,]+\.\d{2})",
            text,
        ) or extract_field(r"Balance due\s+\$?([0-9,]+\.\d{2})", text)
        please_remit = extract_field(r"Please Remit\s+\$?([0-9,]+\.\d{2})", text)
        current_invoice_amount = extract_field(r"Total amount of this bill\s+([0-9,]+\.\d{2})", text)
        current_invoice_hours = extract_field(
            r"For professional services rendered\s+([0-9,]+\.\d{2})\s+[0-9,]+\.\d{2}",
            text,
        )

        invoice_index = next((i for i, line in enumerate(lines) if line.startswith("Invoice #:")), None)
        tax_index = next((i for i, line in enumerate(lines) if "Federal Tax ID No." in line), None)
        billto = parse_billto(lines[tax_index + 1 : invoice_index] if tax_index is not None and invoice_index is not None else [])

        professional_start = next((i for i, line in enumerate(lines) if line.strip() == "Professional services"), None)
        professional_end = next((i for i, line in enumerate(lines) if line.startswith("For professional services rendered")), None)
        if professional_start is not None and professional_end is not None:
            line_items = parse_line_items(lines[professional_start + 2 : professional_end])

        aged_start = next((i for i, line in enumerate(lines) if line.strip() == "Aged Accounts Receivable"), None)
        aged_end = next((i for i, line in enumerate(lines) if line.startswith("Please Remit")), None)
        if aged_start is not None and aged_end is not None:
            aged_rows = parse_aged_receivables(lines[aged_start + 2 : aged_end])
            if aged_rows and not line_items:
                document_type = "statement"

        summary_start = next((i for i, line in enumerate(lines) if line.strip() == "Name Amount"), None)
        summary_end = next((i for i, line in enumerate(lines) if line.startswith("Total amount of this bill")), None)
        timekeeper_summary = parse_timekeeper_summary(
            lines[summary_start + 1 : summary_end] if summary_start is not None and summary_end is not None else []
        )

        if not current_invoice_amount and balance_due:
            current_invoice_amount = balance_due if document_type == "invoice" else ""

        if not balance_due:
            ending_retainer = extract_field(r"Ending Retainer Fund Balance\s+\$?([0-9,]+\.\d{2})", text)
            if ending_retainer:
                document_type = "statement"
                balance_due = ending_retainer
                please_remit = ending_retainer
        if not please_remit:
            please_remit = balance_due
        return {
            "source_file": Path(pdf_path).name,
            "document_type": document_type,
            "invoice": {
                "invoice_number": invoice_number,
                "invoice_date": invoice_date,
                "client_number": client_number,
                "matter_reference": matter_reference,
                "federal_tax_id": tax_id,
                "vendor": vendor_defaults,
                "billto": billto,
                "currency": "USD",
                "line_items": line_items,
                "aged_accounts": aged_rows,
                "timekeeper_summary": timekeeper_summary,
                "totals": {
                    "previous_balance": clean_amount(previous_balance) if previous_balance else "",
                    "current_invoice_hours": clean_amount(current_invoice_hours) if current_invoice_hours else "",
                    "current_invoice_amount": clean_amount(current_invoice_amount) if current_invoice_amount else "",
                    "balance_due": clean_amount(balance_due) if balance_due else "",
                    "please_remit": clean_amount(please_remit) if please_remit else "",
                },
            },
        }

    current_invoice_hours = ""
    if not please_remit:
        please_remit = balance_due

    return {
        "source_file": Path(pdf_path).name,
        "document_type": document_type,
        "invoice": {
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "client_number": client_number,
            "matter_reference": matter_reference,
            "federal_tax_id": tax_id,
            "vendor": vendor_defaults,
            "billto": billto,
            "currency": "USD",
            "line_items": line_items,
            "aged_accounts": aged_rows,
            "timekeeper_summary": timekeeper_summary,
            "totals": {
                "previous_balance": clean_amount(previous_balance) if previous_balance else "",
                "current_invoice_hours": clean_amount(current_invoice_hours) if current_invoice_hours else "",
                "current_invoice_amount": clean_amount(current_invoice_amount) if current_invoice_amount else "",
                "balance_due": clean_amount(balance_due) if balance_due else "",
                "please_remit": clean_amount(please_remit) if please_remit else "",
            },
        },
    }


def append_text(parent, tag, value):
    child = ET.SubElement(parent, tag)
    child.text = value
    return child


def build_invoice_xml(data):
    root = ET.Element("InvoiceExtraction")
    append_text(root, "SourceFile", data["source_file"])
    append_text(root, "DocumentType", data["document_type"])

    invoice_data = data["invoice"]
    invoice = ET.SubElement(root, "Invoice")
    append_text(invoice, "InvoiceNumber", invoice_data["invoice_number"])
    append_text(invoice, "InvoiceDate", invoice_data["invoice_date"])
    append_text(invoice, "ClientNumber", invoice_data["client_number"])
    append_text(invoice, "MatterReference", invoice_data["matter_reference"])
    append_text(invoice, "FederalTaxId", invoice_data["federal_tax_id"])

    vendor = ET.SubElement(invoice, "Vendor")
    append_text(vendor, "Name", invoice_data["vendor"]["name"])
    append_text(vendor, "AddressLine1", invoice_data["vendor"]["address_1"])
    append_text(vendor, "City", invoice_data["vendor"]["city"])
    append_text(vendor, "State", invoice_data["vendor"]["state"])
    append_text(vendor, "PostalCode", invoice_data["vendor"]["postal"])
    append_text(vendor, "Phone", invoice_data["vendor"]["phone"])
    append_text(vendor, "Fax", invoice_data["vendor"]["fax"])
    append_text(vendor, "Website", invoice_data["vendor"]["website"])

    billto = ET.SubElement(invoice, "BillTo")
    append_text(billto, "Name", invoice_data["billto"]["name"])
    append_text(billto, "CareOf", invoice_data["billto"]["careof"])
    append_text(billto, "AddressLine1", invoice_data["billto"]["address_1"])
    append_text(billto, "AddressLine2", invoice_data["billto"]["address_2"])
    append_text(billto, "City", invoice_data["billto"]["city"])
    append_text(billto, "State", invoice_data["billto"]["state"])
    append_text(billto, "PostalCode", invoice_data["billto"]["postal"])
    append_text(billto, "Attention", invoice_data["billto"]["attention"])

    append_text(invoice, "Currency", invoice_data["currency"])

    line_items = ET.SubElement(invoice, "LineItems")
    for item in invoice_data["line_items"]:
        line_item = ET.SubElement(line_items, "LineItem")
        append_text(line_item, "LineNumber", item["line_number"])
        append_text(line_item, "ServiceDate", item["service_date"])
        append_text(line_item, "TimekeeperCode", item["timekeeper_code"])
        append_text(line_item, "TimekeeperName", item["timekeeper_name"])
        append_text(line_item, "Description", item["description"])
        append_text(line_item, "UnitType", "Hours")
        append_text(line_item, "Quantity", item["quantity"])
        append_text(line_item, "UnitPrice", item["unit_price"])
        append_text(line_item, "LineAmount", item["line_amount"])
        append_text(line_item, "Category", item["category"])

    aged_accounts = ET.SubElement(invoice, "AgedAccountsReceivable")
    for row in invoice_data["aged_accounts"]:
        entry = ET.SubElement(aged_accounts, "Entry")
        append_text(entry, "StmtDate", row["stmt_date"])
        append_text(entry, "StmtNumber", row["stmt_number"])
        append_text(entry, "Billed", row["billed"])
        append_text(entry, "Due", row["due"])

    timekeeper_summary = ET.SubElement(invoice, "TimekeeperSummary")
    for row in invoice_data["timekeeper_summary"]:
        entry = ET.SubElement(timekeeper_summary, "Timekeeper")
        append_text(entry, "Name", row["name"])
        append_text(entry, "Amount", row["amount"])

    totals = ET.SubElement(invoice, "Totals")
    append_text(totals, "PreviousBalance", invoice_data["totals"]["previous_balance"])
    append_text(totals, "CurrentInvoiceHours", invoice_data["totals"]["current_invoice_hours"])
    append_text(totals, "CurrentInvoiceAmount", invoice_data["totals"]["current_invoice_amount"])
    append_text(totals, "BalanceDue", invoice_data["totals"]["balance_due"])
    append_text(totals, "PleaseRemit", invoice_data["totals"]["please_remit"])

    return ET.ElementTree(root)


def indent_xml(elem, level=0):
    indent = "\n" + level * "  "
    child_indent = "\n" + (level + 1) * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = child_indent
        for child in elem:
            indent_xml(child, level + 1)
            if not child.tail or not child.tail.strip():
                child.tail = child_indent
        if not elem[-1].tail or not elem[-1].tail.strip():
            elem[-1].tail = indent
    elif not elem.text:
        elem.text = ""


def write_xml(tree, xml_path):
    root = tree.getroot()
    indent_xml(root)
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)


def parse_invoice_xml(xml_path):
    tree = ET.parse(xml_path)
    root = tree.getroot()
    invoice = root.find(".//Invoice")
    if invoice is None:
        raise ValueError("Could not find <Invoice> node in XML.")

    data = {
        "document_type": find_text(root, "DocumentType", "invoice"),
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
        "previous_balance": find_text(invoice, "Totals/PreviousBalance", ""),
        "current_invoice_amount": find_text(invoice, "Totals/CurrentInvoiceAmount", ""),
        "balance_due": find_text(invoice, "Totals/BalanceDue", ""),
        "please_remit": find_text(invoice, "Totals/PleaseRemit", ""),
        "current_invoice_hours": find_text(invoice, "Totals/CurrentInvoiceHours", ""),
    }

    line_items = []
    for i, item in enumerate(invoice.findall(".//LineItems/LineItem"), start=1):
        line_items.append(
            {
                "line_number": find_text(item, "LineNumber", str(i)),
                "service_date": find_text(item, "ServiceDate", ""),
                "timekeeper_code": find_text(item, "TimekeeperCode", ""),
                "description": find_text(item, "Description", ""),
                "quantity": find_text(item, "Quantity", ""),
                "unit_price": find_text(item, "UnitPrice", ""),
                "line_amount": find_text(item, "LineAmount", ""),
            }
        )

    aged_rows = []
    for row in invoice.findall(".//AgedAccountsReceivable/Entry"):
        aged_rows.append(
            {
                "stmt_date": find_text(row, "StmtDate", ""),
                "stmt_number": find_text(row, "StmtNumber", ""),
                "billed": find_text(row, "Billed", ""),
                "due": find_text(row, "Due", ""),
            }
        )

    return data, line_items, aged_rows


def create_pdf_from_xml(xml_path, output_pdf):
    data, line_items, aged_rows = parse_invoice_xml(xml_path)

    doc = SimpleDocTemplate(
        str(output_pdf),
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    elements = []

    title = "Statement" if data["document_type"] == "statement" else "Invoice"
    elements.append(Paragraph(title, styles["Title"]))
    elements.append(Spacer(1, 6))

    header_rows = [
        ["Invoice No", data["invoice_number"], "Invoice Date", data["invoice_date"]],
        ["Client Number", data["client_number"], "Matter", data["matter_reference"]],
        ["Tax ID", data["federal_tax_id"], "Currency", data["currency"]],
    ]
    if data["previous_balance"]:
        header_rows.append(["Previous Balance", data["previous_balance"], "Balance Due", data["balance_due"]])
    else:
        header_rows.append(["Current Invoice Amount", data["current_invoice_amount"], "Balance Due", data["balance_due"]])

    header_table = Table(header_rows, colWidths=[35 * mm, 55 * mm, 40 * mm, 45 * mm])
    header_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                ("BACKGROUND", (2, 0), (2, -1), colors.whitesmoke),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    elements.append(header_table)
    elements.append(Spacer(1, 10))

    vendor_lines = [
        data["vendor_name"],
        data["vendor_address_1"],
        " ".join(x for x in [data["vendor_city"], data["vendor_state"], data["vendor_postal"]] if x),
        f"Phone: {data['vendor_phone']}" if data["vendor_phone"] else "",
        data["vendor_website"],
    ]
    billto_lines = [
        data["billto_name"],
        data["billto_careof"],
        data["billto_address_1"],
        data["billto_address_2"],
        " ".join(x for x in [data["billto_city"], data["billto_state"], data["billto_postal"]] if x),
        f"Attention: {data['attention']}" if data["attention"] else "",
    ]
    party_table = Table(
        [
            [
                Paragraph("<b>Vendor</b><br/>" + "<br/>".join(line for line in vendor_lines if line), styles["BodyText"]),
                Paragraph("<b>Bill To</b><br/>" + "<br/>".join(line for line in billto_lines if line), styles["BodyText"]),
            ]
        ],
        colWidths=[90 * mm, 90 * mm],
    )
    party_table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.4, colors.grey),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("PADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    elements.append(party_table)
    elements.append(Spacer(1, 10))

    if line_items:
        table_data = [["Date", "TK", "Description", "Hours", "Rate", "Amount"]]
        for item in line_items:
            table_data.append(
                [
                    item["service_date"],
                    item["timekeeper_code"],
                    Paragraph(item["description"], styles["BodyText"]),
                    item["quantity"],
                    item["unit_price"],
                    item["line_amount"],
                ]
            )

        line_table = Table(table_data, colWidths=[22 * mm, 14 * mm, 86 * mm, 18 * mm, 22 * mm, 24 * mm])
        line_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4F81BD")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ALIGN", (3, 1), (5, -1), "RIGHT"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        elements.append(line_table)
        elements.append(Spacer(1, 10))
    elif aged_rows:
        table_data = [["Stmt Date", "Stmt #", "Billed", "Due"]]
        for row in aged_rows:
            table_data.append([row["stmt_date"], row["stmt_number"], row["billed"], row["due"]])
        aged_table = Table(table_data, colWidths=[35 * mm, 35 * mm, 40 * mm, 40 * mm])
        aged_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4F81BD")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("ALIGN", (2, 1), (3, -1), "RIGHT"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                ]
            )
        )
        elements.append(Paragraph("Aged Accounts Receivable", styles["Heading3"]))
        elements.append(aged_table)
        elements.append(Spacer(1, 10))

    totals_rows = []
    if data["previous_balance"]:
        totals_rows.append(["Previous Balance", money_or_blank(data["previous_balance"])])
    if data["current_invoice_hours"]:
        totals_rows.append(["Current Invoice Hours", money_or_blank(data["current_invoice_hours"])])
    if data["current_invoice_amount"]:
        totals_rows.append(["Current Invoice Amount", money_or_blank(data["current_invoice_amount"])])
    totals_rows.append(["Balance Due", money_or_blank(data["balance_due"])])
    totals_rows.append(["Please Remit", money_or_blank(data["please_remit"] or data["balance_due"])])

    totals_table = Table(totals_rows, colWidths=[60 * mm, 35 * mm], hAlign="RIGHT")
    totals_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]
        )
    )
    elements.append(totals_table)
    doc.build(elements)


def embed_xml_into_pdf(input_pdf_path, xml_path, output_pdf_path):
    with pikepdf.open(input_pdf_path) as pdf:
        with open(xml_path, "rb") as handle:
            pdf.attachments[Path(xml_path).name] = handle.read()
        pdf.docinfo["/EmbeddedXML"] = Path(xml_path).name
        pdf.docinfo["/Producer"] = "pdf_xml_roundtrip.py"
        pdf.save(output_pdf_path)


def extract_embedded_xml_from_pdf(pdf_path, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    extracted = []
    with pikepdf.open(pdf_path) as pdf:
        for name, file_spec in pdf.attachments.items():
            if not name.lower().endswith(".xml"):
                continue
            target = output_dir / name
            target.write_bytes(file_spec.get_file().read_bytes())
            extracted.append(target)
    return extracted


def run_pipeline(input_pdf, output_dir):
    input_pdf = Path(input_pdf)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    data = parse_source_pdf(input_pdf)
    xml_path = output_dir / f"{input_pdf.stem}.xml"
    generated_pdf = output_dir / f"{input_pdf.stem}_generated.pdf"
    final_pdf = output_dir / f"{input_pdf.stem}_with_xml.pdf"
    extracted_dir = output_dir / "extracted_xml"

    write_xml(build_invoice_xml(data), xml_path)
    create_pdf_from_xml(xml_path, generated_pdf)
    embed_xml_into_pdf(generated_pdf, xml_path, final_pdf)
    extracted_files = extract_embedded_xml_from_pdf(final_pdf, extracted_dir)

    print(f"Source PDF: {input_pdf}")
    print(f"XML created: {xml_path}")
    print(f"Generated PDF: {generated_pdf}")
    print(f"Embedded XML PDF: {final_pdf}")
    print("Extracted XML:", ", ".join(str(path) for path in extracted_files) if extracted_files else "none")


def main():
    parser = argparse.ArgumentParser(description="Convert a source PDF into XML, regenerate a PDF, and embed the XML.")
    parser.add_argument("input_pdf", help="Path to the source PDF")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for XML/PDF outputs. Defaults to output/<input-pdf-name>/",
    )
    args = parser.parse_args()

    input_pdf = Path(args.input_pdf)
    output_dir = Path(args.output_dir) if args.output_dir else Path("output") / input_pdf.stem
    run_pipeline(input_pdf, output_dir)


if __name__ == "__main__":
    main()
