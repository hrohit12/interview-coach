"""
resume_parser.py
Extracts text from uploaded PDF or TXT files.
"""

from pypdf import PdfReader
import os


def extract_text_from_pdf(file_path: str) -> str:
    """Extract text from a PDF file using PyPDF."""
    try:
        reader = PdfReader(file_path)
        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        return text.strip()
    except Exception as e:
        return f"Error reading PDF: {str(e)}"


def extract_text_from_txt(file_path: str) -> str:
    """Extract text from a plain text file."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().strip()
    except Exception as e:
        return f"Error reading file: {str(e)}"


def parse_uploaded_file(file_path: str) -> str:
    """
    Parse an uploaded file and return its text content.
    Supports PDF and TXT/MD files.
    """
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        return extract_text_from_pdf(file_path)
    elif ext in [".txt", ".md"]:
        return extract_text_from_txt(file_path)
    else:
        # Try reading as text anyway
        return extract_text_from_txt(file_path)
