import fitz
import os

def analyze_pdf(file_path):
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return

    try:
        doc = fitz.open(file_path)
        total_text_len = sum(len(page.get_text()) for page in doc)
        print(f"--- Analyzing: {file_path} ---")
        print(f"Page count: {len(doc)}")
        print(f"Total text length: {total_text_len}")
        if len(doc) > 0:
            first_page_text = doc[0].get_text()
            print(f"First page text length: {len(first_page_text)}")
            print(f"First page text sample: '{first_page_text[:200].strip()}'")
        print("-" * (20 + len(file_path)))
        doc.close()
    except Exception as e:
        print(f"Could not process {file_path}: {e}")

analyze_pdf("samples/lending_package.pdf")
analyze_pdf("samples/bank-statement-multipage.pdf")
