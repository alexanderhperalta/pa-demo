"""
Document Intelligence Module
Extracts structured PA fields from an ABA treatment plan PDF using Claude API.
"""
import anthropic
import base64
import json
import os
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

EXTRACTION_PROMPT = """You are a healthcare document intelligence system specializing in 
prior authorization workflows. Extract the following structured fields from this ABA 
treatment plan document.

Return ONLY a valid JSON object with exactly these keys. If a field is not found, use null.

{"patient_name": "Full legal name of the patient",
  # Normalize to YYYY-MM-DD regardless of how the date appears in the document
  "dob": "Date of birth in YYYY-MM-DD format",
  "diagnosis_code": "Primary ICD-10 diagnosis code only (e.g. F84.0)",
  "diagnosis_description": "Full diagnosis name",
  "cpt_code": "Primary CPT procedure code for the main service requested",
  "requested_units": "Units/hours requested per month for the primary service",
  "provider_name": "Full name and credentials of the treating provider",
  "provider_npi": "10-digit NPI number",
  "payer": "Insurance payer name",
  "auth_period": "Requested authorization period",
  "medical_necessity_summary": "2-3 sentence summary of the medical necessity justification",
  "primary_treatment_goal": "The single most important 90-day treatment goal"}

Return only the JSON object. No markdown, no explanation, no code fences."""


# Load in the pdf as unstructured text to be extracted
def load_pdf_as_base64(pdf_path: str) -> str:
    with open(pdf_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


# Uses the Messages API to extract fields from a pdf
def extract_fields(pdf_path: str) -> dict:
    """Send PDF to Claude and extract structured PA fields."""
    print(f"  Loading PDF: {pdf_path}")
    start = time.time()

    pdf_data = load_pdf_as_base64(pdf_path)

    print("  Sending to Claude for extraction...")
    # Use the Messages API
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[
            {"role": "user",
             "content": [{
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_data,},
                            },
                    {
                        "type": "text",
                        "text": EXTRACTION_PROMPT, # The Messages API knows which fields to look for because of EXTRACTION_PROMPT
                    },],}],)

    elapsed = round(time.time() - start, 2)
    raw_text = response.content[0].text.strip()

    try:
        extracted = json.loads(raw_text)
    except json.JSONDecodeError:
        # Strip markdown fences if model added them despite instructions
        cleaned = raw_text.replace("```json", "").replace("```", "").strip()
        extracted = json.loads(cleaned)

    result = {
        "extracted_fields": extracted,
        "metadata": {
            "source_file": Path(pdf_path).name,
            "model": response.model,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "elapsed_seconds": elapsed,
        },}

    return result


def map_to_portal_fields(extracted: dict) -> dict:
    """Map extracted fields to the exact form field IDs used by the portal."""
    fields = extracted.get("extracted_fields", {})
    return {
        "patient_name": fields.get("patient_name", ""),
        "dob":          fields.get("dob", ""),
        "diagnosis_code": fields.get("diagnosis_code", ""),
        "cpt_code":     fields.get("cpt_code", ""),
        "provider_npi": fields.get("provider_npi", ""),
        "requested_units": fields.get("requested_units", ""),
        "payer":        fields.get("payer", ""),
        "notes":        fields.get("medical_necessity_summary", ""),
    }


if __name__ == "__main__":
    pdf_path = os.path.join(os.path.dirname(__file__), "../sample_docs/treatment_plan.pdf")

    print("\n── Document Intelligence Extraction ──────────────────────")
    result = extract_fields(pdf_path)

    print("\n  Raw extracted fields:")
    print(json.dumps(result["extracted_fields"], indent=2))

    print("\n  Portal field mapping:")
    print(json.dumps(map_to_portal_fields(result), indent=2))

    print(f"\n  Metadata: {result['metadata']}")
    print("──────────────────────────────────────────────────────────\n")