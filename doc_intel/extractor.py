"""
Document Intelligence Module
Extracts structured PA fields from an ABA treatment plan PDF using Claude API.
"""
import anthropic, asyncio, base64, json, os, time
from anthropic import AsyncAnthropic
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=5)

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
async def extract_fields(pdf_path: str) -> dict:
    """Send PDF to Claude and extract structured PA fields."""
    start = time.time()
    pdf_data = load_pdf_as_base64(pdf_path)
    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": [
            {"type": "document", "source": {"type": "base64",
            "media_type": "application/pdf", "data": pdf_data}},
            {"type": "text", "text": EXTRACTION_PROMPT}]}],)

    elapsed = round(time.time() - start, 2)
    raw = response.content[0].text.strip()

    try:
        extracted = json.loads(raw)
    except json.JSONDecodeError:
        # Strip markdown fences if model added them despite instructions
        extracted = json.loads(raw.replace("```json", "").replace("```", "").strip())

    result = {
        "extracted_fields": extracted,
        "metadata": {
            "source_file": Path(pdf_path).name,
            "model": response.model,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "elapsed_seconds": round(time.time() - start, 2),
        },}

    return result


def map_to_portal_fields(result: dict) -> dict:
    """Map extracted fields to the exact form field IDs used by the portal."""
    f = result.get("extracted_fields", {})
    return {
        "pdf_name":         result["metadata"]["source_file"],
        "patient_name":     f.get("patient_name", ""),
        "dob":              f.get("dob", ""),
        "diagnosis_code":   f.get("diagnosis_code", ""),
        "cpt_code":         f.get("cpt_code", ""),
        "provider_npi":     f.get("provider_npi", ""),
        "requested_units":  f.get("requested_units", ""),
        "payer":            f.get("payer", ""),
        "notes":            f.get("medical_necessity_summary", ""),
    }

async def main():
    cases_dir = Path(__file__).parent.parent / "sample_docs" / "cases"
    pdf_paths = sorted(cases_dir.glob("*.pdf"))

    sem = asyncio.Semaphore(5)                       # cap concurrency / respect rate limits
    async def extract_one(p):
        async with sem:
            return await extract_fields(str(p))

    # return_exceptions=True → one bad PDF doesn't kill the whole run
    results = await asyncio.gather(*(extract_one(p) for p in pdf_paths),
                                    return_exceptions=True)

    for p, r in zip(pdf_paths, results):
        if isinstance(r, Exception):
            print(f"  ✗ {p.name}: {r}")
            continue
        print(f"  ✓ {p.name}: {json.dumps(map_to_portal_fields(r))}")
    
    with open("data.json", "w") as file:
        json.dump(results, file, indent=4)

if __name__ == "__main__":
    asyncio.run(main())