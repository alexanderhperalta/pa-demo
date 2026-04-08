"""
Prior Authorization Browser Agent
Automates end-to-end PA submission using data extracted by the doc_intel module.
"""
import sys
import os
import json
import time
import datetime
from pathlib import Path
from dotenv import load_dotenv

from playwright.sync_api import sync_playwright, Page, expect

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent.parent))
from doc_intel.extractor import extract_fields, map_to_portal_fields

load_dotenv()

PORTAL_URL    = "http://127.0.0.1:5050"
USERNAME      = os.getenv("PORTAL_USERNAME")
PASSWORD      = os.getenv("PORTAL_PASSWORD")
PDF_PATH      = str(Path(__file__).parent.parent / "sample_docs" / "treatment_plan.pdf")
OUTPUT_PATH   = str(Path(__file__).parent.parent / "outputs" / "agent_run.json")

# ── Payer Normalization ───────────────────────────────────────────────────────

# Canonical portal options: {display_label: value_attribute}
PORTAL_PAYERS = {
    "Aetna":                        "Aetna",
    "Anthem Blue Cross Blue Shield": "Anthem",
    "Cigna":                        "Cigna",
    "United Healthcare":            "United Healthcare",
    "Humana":                       "Humana",
    "Medicaid — New York":          "Medicaid - NY",
}

# Keyword hints for fuzzy normalization
PAYER_KEYWORDS = {
    "Aetna":             ["aetna"],
    "Anthem Blue Cross Blue Shield": ["anthem", "bcbs", "blue cross", "blue shield"],
    "Cigna":             ["cigna"],
    "United Healthcare": ["united", "uhc", "unitedhealthcare"],
    "Humana":            ["humana"],
    "Medicaid — New York": ["medicaid", "mcd", "ny medicaid"],
}

def normalize_payer(raw: str) -> str:
    """
    Map a raw payer string from Claude to the exact portal dropdown label.
    Uses keyword matching so variations like 'Aetna Commercial PPO',
    'Anthem BCBS', or 'UHC' all resolve correctly.
    Falls back to 'Aetna' with a warning if no match found.
    """
    normalized = raw.lower().strip()
    for label, keywords in PAYER_KEYWORDS.items():
        if any(kw in normalized for kw in keywords):
            return label
    print(f"  ⚠  Unknown payer '{raw}' — defaulting to Aetna. Add to PAYER_KEYWORDS if needed.")
    return "Aetna"

# ── Logging ───────────────────────────────────────────────────────────────────

class AgentLog:
    def __init__(self):
        self.steps: list[dict] = []
        self.start_time = time.time()

    def log(self, action: str, detail: str = "", status: str = "ok"):
        entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "elapsed_s": round(time.time() - self.start_time, 2),
            "action":    action,
            "detail":    detail,
            "status":    status,
        }
        self.steps.append(entry)
        icon = {"ok": "✓", "error": "✗", "info": "·"}.get(status, "·")
        print(f"  {icon} [{entry['elapsed_s']:5.1f}s] {action}" +
              (f": {detail}" if detail else ""))


# ── Agent Steps ───────────────────────────────────────────────────────────────

def step_login(page: Page, log: AgentLog):
    log.log("Navigate to login", PORTAL_URL)
    page.goto(PORTAL_URL)
    page.wait_for_load_state("domcontentloaded")

    log.log("Fill credentials")
    page.fill("#username", USERNAME)
    page.fill("#password", PASSWORD)

    log.log("Submit login form")
    page.click("button[type=submit]")
    page.wait_for_url(f"{PORTAL_URL}/submit", timeout=8000)
    log.log("Login successful", "Redirected to /submit")


def step_fill_form(page: Page, log: AgentLog, fields: dict):
    log.log("Navigate to PA submission form")
    page.goto(f"{PORTAL_URL}/submit")
    page.wait_for_load_state("domcontentloaded")

    log.log("Fill patient name", fields["patient_name"])
    page.fill("#patient_name", fields["patient_name"])

    log.log("Fill date of birth", fields["dob"])
    page.fill("#dob", fields["dob"])

    log.log("Fill diagnosis code", fields["diagnosis_code"])
    page.fill("#diagnosis_code", fields["diagnosis_code"])

    log.log("Fill CPT code", fields["cpt_code"])
    page.fill("#cpt_code", fields["cpt_code"])

    log.log("Fill provider NPI", fields["provider_npi"])
    page.fill("#provider_npi", fields["provider_npi"])

    log.log("Fill requested units", fields["requested_units"])
    page.fill("#requested_units", fields["requested_units"])

    # Resolve payer name to dropdown option label
    raw_payer = fields.get("payer", "")
    portal_payer = normalize_payer(raw_payer)
    log.log("Select payer", f"{raw_payer!r} → {portal_payer}")
    page.select_option("#payer", label=portal_payer)

    log.log("Fill medical necessity notes")
    page.fill("#notes", fields.get("notes", ""))

    log.log("Form fields populated", f"{len(fields)} fields")


def step_submit(page: Page, log: AgentLog) -> str:
    log.log("Click submit button")
    page.click("#submit-btn")

    # Wait for redirect to status page
    page.wait_for_url(f"{PORTAL_URL}/status*", timeout=10000)
    log.log("Redirected to status page", "Submission accepted")

    # Extract the PA reference number from the page
    pa_ref = page.inner_text("#pa-ref").strip()
    log.log("PA reference confirmed", pa_ref)
    return pa_ref


def step_verify_status(page: Page, log: AgentLog, pa_ref: str):
    log.log("Verify status page content")

    # Confirm reference number is displayed
    expect(page.locator("#pa-ref")).to_contain_text(pa_ref.replace("PA-", ""))

    # Confirm patient name is displayed
    patient_el = page.locator("#pa-patient")
    patient_name = patient_el.inner_text().strip()
    log.log("Patient name on status page", patient_name)

    # Confirm status badge shows Pending
    badge = page.locator(".badge.pending").first
    expect(badge).to_be_visible()
    log.log("Status badge verified", "PENDING — as expected")

def step_check_status(page: Page, log: AgentLog, pa_ref: str) -> str:
    """
    Second agent flow: log back in, navigate to the status page,
    find the PA by reference number, and return its current status.
    Mirrors Silna's per-payer follow-up cadence.
    """
    log.log("Status check — navigate to portal", PORTAL_URL)
    page.goto(PORTAL_URL)
    page.wait_for_load_state("domcontentloaded")

    # Re-authenticate if session has expired
    if page.url == f"{PORTAL_URL}/":
        log.log("Session expired — re-authenticating")
        page.fill("#username", USERNAME)
        page.fill("#password", PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_url(f"{PORTAL_URL}/submit", timeout=8000)
        log.log("Re-authentication successful")

    log.log("Navigate to status page", f"Looking for {pa_ref}")
    page.goto(f"{PORTAL_URL}/status")
    page.wait_for_load_state("domcontentloaded")

    # Find the row in the submissions table matching our PA reference
    row = page.locator(f"td:has-text('{pa_ref}')").first
    if not row.is_visible():
        log.log("PA reference not found on status page", pa_ref, "error")
        return "NOT FOUND"

    # Status badge is the last <td> in the same row
    status_badge = row.locator("xpath=../td[last()]").inner_text().strip()
    log.log("Status retrieved", f"{pa_ref} → {status_badge}")
    return status_badge


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    if not USERNAME or not PASSWORD:
        raise ValueError("PORTAL_USERNAME and PORTAL_PASSWORD must be set in .env")
    os.makedirs(Path(OUTPUT_PATH).parent, exist_ok=True)
    log = AgentLog()
    pa_ref = None
    success = False

    print("\n── Phase 1: Document Intelligence ────────────────────────")
    log.log("Extract fields from treatment plan", PDF_PATH, "info")
    extraction_result = extract_fields(PDF_PATH)
    portal_fields = map_to_portal_fields(extraction_result)
    log.log("Extraction complete", f"{len(portal_fields)} fields ready")

    print("\n── Phase 2: Browser Agent — Submission ───────────────────")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=600)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        try:
            step_login(page, log)
            step_fill_form(page, log, portal_fields)

            print("\n  ⏸  Form filled — review in browser. Submitting in 3s...")
            time.sleep(3)

            pa_ref = step_submit(page, log)
            step_verify_status(page, log, pa_ref)
            log.log("Submission flow complete", pa_ref)
            success = True

        except Exception as e:
            log.log("Submission error", str(e), "error")
            raise

        finally:
            time.sleep(2)
            browser.close()

    print("\n── Phase 3: Status Check — Follow-up cadence ─────────────")
    print("  Simulating Silna follow-up loop (1 check, 5s delay)...")
    time.sleep(5)  # In production: tuned per payer/specialty cadence

    pa_status = "UNKNOWN"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=500)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        try:
            pa_status = step_check_status(page, log, pa_ref)
        except Exception as e:
            log.log("Status check error", str(e), "error")
        finally:
            time.sleep(3)
            browser.close()

    # Save results
    output = {
        "success":                  success,
        "pa_reference":             pa_ref,
        "pa_status_after_followup": pa_status,
        "portal_fields_submitted":  portal_fields,
        "extraction_metadata":      extraction_result["metadata"],
        "agent_steps":              log.steps,
        "total_elapsed_seconds":    round(time.time() - log.start_time, 2),
    }
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n  Results saved → {OUTPUT_PATH}")

    print("\n── Summary ────────────────────────────────────────────────")
    print(f"  Success:          {success}")
    print(f"  PA Reference:     {pa_ref}")
    print(f"  Status (follow-up): {pa_status}")
    print(f"  Steps logged:     {len(log.steps)}")
    print(f"  Total time:       {output['total_elapsed_seconds']}s")
    print("────────────────────────────────────────────────────────────\n")

if __name__ == "__main__":
    run()