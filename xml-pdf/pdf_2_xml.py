import pikepdf
from pathlib import Path


def extract_embedded_xml_from_pdf(pdf_path: str, output_dir: str = "."):
    """
    Extract embedded XML attachments from a PDF.

    Args:
        pdf_path: Path to the input PDF file
        output_dir: Directory where extracted XML files will be saved

    Returns:
        List of extracted XML file paths
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    extracted_files = []
    pdf_file = Path(pdf_path)

    if not pdf_file.exists():
        print(f"❌ PDF file not found: {pdf_path}")
        return extracted_files

    try:
        with pikepdf.open(pdf_path) as pdf:
            attachments = pdf.attachments

            if not attachments:
                print("⚠️ No embedded attachments found in PDF.")
                return extracted_files

            print(f"Found {len(attachments)} attachment(s) in PDF.")

            for name, file_spec in attachments.items():
                print(f"Checking attachment: {name}")

                if not name.lower().endswith(".xml"):
                    print(f"Skipping non-XML attachment: {name}")
                    continue

                try:
                    attached_file = file_spec.get_file()
                    data = attached_file.read_bytes()

                    file_path = output_path / name
                    file_path.write_bytes(data)

                    extracted_files.append(str(file_path))
                    print(f"✅ Extracted XML: {file_path}")

                except Exception as e:
                    print(f"❌ Failed to read attachment {name}: {e}")

    except Exception as e:
        print(f"❌ Failed to open PDF: {e}")
        return extracted_files

    if not extracted_files:
        print("⚠️ No XML files found in embedded attachments.")

    return extracted_files


def extract_all_attachments_from_pdf(pdf_path: str, output_dir: str = "."):
    """
    Extract all embedded attachments from a PDF.

    Args:
        pdf_path: Path to the input PDF file
        output_dir: Directory where extracted files will be saved

    Returns:
        List of extracted file paths
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    extracted_files = []
    pdf_file = Path(pdf_path)

    if not pdf_file.exists():
        print(f"❌ PDF file not found: {pdf_path}")
        return extracted_files

    try:
        with pikepdf.open(pdf_path) as pdf:
            attachments = pdf.attachments

            if not attachments:
                print("⚠️ No embedded attachments found in PDF.")
                return extracted_files

            print(f"Found {len(attachments)} attachment(s) in PDF.")

            for name, file_spec in attachments.items():
                print(f"Extracting attachment: {name}")

                try:
                    attached_file = file_spec.get_file()
                    data = attached_file.read_bytes()

                    file_path = output_path / name
                    file_path.write_bytes(data)

                    extracted_files.append(str(file_path))
                    print(f"✅ Extracted: {file_path}")

                except Exception as e:
                    print(f"❌ Failed to extract {name}: {e}")

    except Exception as e:
        print(f"❌ Failed to open PDF: {e}")
        return extracted_files

    return extracted_files


if __name__ == "__main__":
    pdf_file = "final_invoice_with_xml.pdf"
    output_folder = "extracted_xml"

    print(f"Opening PDF: {pdf_file}")
    xml_files = extract_embedded_xml_from_pdf(pdf_file, output_folder)
    print("Done:", xml_files)
