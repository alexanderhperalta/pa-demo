# Prior Authorization Automation Demo
**Document Intelligence + Browser Agent — AI Deployment Analyst Project**

A working demonstration of end-to-end prior authorization workflow automation for specialty healthcare providers.

## What This Does

This project simulates a core insurance workflow automation loop:

1. **Document Intelligence**: A clinical ABA treatment plan PDF is parsed by Claude's API, extracting structured fields (patient name, DOB, ICD-10 code, CPT code, NPI, payer, units, medical necessity summary) with no OCR configuration required.
2. **Browser Agent**: A Playwright agent logs into a mock insurance payer portal, populates the prior authorization form with the extracted data, submits the request, and verifies the confirmation — fully autonomously.
3. **Results Dashboard**: Every agent action is timestamped and logged, displayed alongside extraction metadata and raw JSON output.

Total time from PDF → confirmed PA reference number: **~19 seconds**.

## Project Structure

```
pa-demo/
├── portal/
│   ├── app.py              # Flask mock payer portal + API endpoints
│   ├── storage.json        # File-based PA record store
│   └── templates/
│       ├── login.html      # Provider login page
│       ├── submit_pa.html  # PA submission form
│       └── status.html     # Authorization status dashboard
├── doc_intel/
│   └── extractor.py        # Claude API document intelligence module
├── agent/
│   └── pa_agent.py         # Playwright browser automation agent
├── sample_docs/
│   ├── generate_treatment_plan.py  # Generates realistic ABA treatment plan PDF
│   └── treatment_plan.pdf          # Sample input document
├── dashboard/
│   └── index.html          # Results dashboard
├── outputs/
│   └── agent_run.json      # Agent run log (generated after each run)
└── requirements.txt
```

## Setup

**Requirements:** Python 3.10+, pip

```bash
# Clone and create virtual environment
git clone <repo-url>
cd pa-demo
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Configure API key
echo "ANTHROPIC_API_KEY=your_key_here" > .env

# Add portal credentials to .env
echo "PORTAL_USERNAME=provider_demo" >> .env
echo "PORTAL_PASSWORD=your_password_here" >> .env

# Generate the sample treatment plan PDF
python sample_docs/generate_treatment_plan.py
```

## Running the Demo

**Terminal 1 — Start the portal:**
```bash
cd portal
python app.py
# Running on http://127.0.0.1:5050
```

**Terminal 2 — Run the agent:**
```bash
python agent/pa_agent.py
```

A Chromium browser will open and complete the full workflow autonomously. Results are saved to `outputs/agent_run.json`.

**View the dashboard:**
```
http://127.0.0.1:5050/dashboard
```

## Design Decisions

### Why Claude API over Tesseract OCR
Traditional OCR requires post-processing pipelines to interpret extracted text — you get raw characters, not structured meaning. Claude reads the document as a clinician would, returning a typed JSON object with field-level accuracy. For complex healthcare documents with varied layouts, this is significantly more robust.

### Automation vs. Orchestration
This project is designed around the distinction between *automation* (performing a single task) and *orchestration* (coordinating across systems to deliver a complete outcome). The browser agent is one channel within a larger pipeline. In production, this would sit alongside phone agents, EDI integrations, and fax workflows — each handling the payer channels that require them. `pa_agent.py` is explicitly designed to be callable by an orchestration layer, not just as a standalone script.

### ABA as the Target Specialty
Applied Behavior Analysis therapy was chosen deliberately. It requires frequent re-authorizations (every 6 months), involves complex clinical documentation, and uses payer-specific medical necessity criteria — making it a high-complexity domain to demonstrate the system against.

### Format Normalization at Extraction Time
The treatment plan PDF stores the patient's date of birth as `"March 14, 2018"` — a human-readable format that cannot be directly entered into an HTML date input, which requires `YYYY-MM-DD`.

Rather than parsing and reformatting dates in a post-processing step, the extraction prompt instructs Claude to return DOB in `YYYY-MM-DD` format directly. This is a deliberate design choice: normalization happens at extraction time, so `map_to_portal_fields()` produces values that are immediately portal-ready. The prompt is the single source of transformation logic — not scattered across the pipeline.

### Status Check as a Follow-up Loop
After submission, a second agent flow re-authenticates, navigates to the status page, and retrieves the current PA status by reference number. This mirrors real-world follow-up cadences, where re-check frequency is tuned per payer and specialty.

In production this would run on a cron schedule or event trigger rather than sequentially in the same process. The 5-second delay in the demo is a stand-in for that interval, making the two-phase structure explicit without requiring a scheduler.

## Technologies

- **Python 3.13** with Flask, Playwright, Anthropic SDK
- **Claude claude-sonnet-4-20250514** for document intelligence
- **Playwright/Chromium** for browser automation
- **ReportLab** for synthetic PDF generation
- **Vanilla HTML/CSS/JS** for the portal and dashboard
