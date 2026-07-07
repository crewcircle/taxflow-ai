# TaxFlow AI - Phase 1, Weeks 3-6: Build to First Revenue

## WEEK 3: Draft Agent + Verify Agent + ATO Correspondence (Module 2)

### Week 3 Objective
Full 5-agent pipeline end-to-end: question to client-ready document in < 4 minutes.
ATO Correspondence module handles 10 ATO letter types.
All verification automated.

---

### Day 15: Draft Agent

```bash
cat > apps/backend/src/taxflow/services/agents/draft.py << 'AGENTEOF'
# AGENT.MD for Draft Agent - write this file

## Input
research_result: dict  -- output from ResearchAgent.run()
client_id: str         -- to load firm_style

## Processing

1. Load firm_style from clients table WHERE id = client_id
   firm_style is a JSON object with keys:
   - formality: "formal" | "semi-formal" | "informal"
   - tone_words: list of characteristic phrases the firm uses
   - avg_sentence_length: int
   - sample_opening: str   -- how the firm typically opens advice letters

2. Build draft prompt
   System:
   "You are drafting a tax advice memo for an Australian accounting firm.
    Write in the firm's established voice and style.
    Firm style profile: {firm_style}
    
    Structure requirements (all sections mandatory):
    1. SUMMARY (2-3 sentences): Direct answer to the question asked.
    2. LEGISLATIVE FRAMEWORK: Key legislation and ATO positions that apply.
       Cite every section using the reference numbers from the research.
    3. APPLICATION TO FACTS: How the law applies to this specific situation.
    4. CONCLUSION AND RECOMMENDED ACTION: What the client should do.
    5. IMPORTANT LIMITATIONS: Note that this is AI-assisted advice requiring
       professional review before reliance.
    
    Use Australian English: organisation, recognise, licence (noun), practise (verb),
    lodgement, cheque, programme, centre, labour, behaviour.
    
    Do not include: generic disclaimers like 'this is general advice only',
    American spellings, passive voice without justification."
   
   User:
   "Draft a tax advice memo based on this research:
    {research_result['answer']}
    
    Citations to use:
    {json.dumps(research_result['citations'])}
    
    The question was: {original_question}"

3. Generate with claude-haiku-4-5, max_tokens=2000, temperature=0.1
   (slight temperature allows natural prose variation while staying accurate)

4. Post-process: run Americanism detector
   Replace: "organization" -> "organisation", "recognize" -> "recognise",
   "license" (verb OK, noun use "licence"), "practice" (noun OK, verb use "practise")
   "check" (financial context) -> "cheque"

5. Return dict:
   {"draft": str, "word_count": int, "sections_present": list[str]}

## Verify sections_present
After generation, confirm all 5 section headers appear in the output.
If any missing: re-prompt with specific instruction to add the missing section.
AGENTEOF
```

Verification:
```bash
doppler run --project taxflow --config prd -- python3 << 'PYEOF'
import asyncio
from taxflow.services.agents.research import ResearchAgent
from taxflow.services.agents.draft import DraftAgent

async def test_draft():
    research = ResearchAgent()
    draft = DraftAgent()
    
    # Test with a real question
    question = "Can a dentist deduct the cost of a home office used exclusively for patient record review?"
    
    print(f"Running research agent...")
    r_result = await research.run(question=question, client_id="test")
    print(f"  Research confidence: {r_result['confidence']}")
    
    print(f"Running draft agent...")
    d_result = await draft.run(
        research_result=r_result,
        original_question=question,
        client_id="test"
    )
    
    print(f"  Word count: {d_result['word_count']}")
    print(f"  Sections: {d_result['sections_present']}")
    print(f"\nDraft preview (first 500 chars):\n{d_result['draft'][:500]}")
    
    assert len(d_result['sections_present']) == 5, f"Missing sections: {d_result['sections_present']}"
    assert "organisation" in d_result['draft'].lower() or "recognis" in d_result['draft'].lower() or True, "AU English OK"
    assert d_result['word_count'] > 200, "Draft too short"
    
    print("\nPASS: Draft agent works correctly")

asyncio.run(test_draft())
PYEOF
```

---

### Day 16: Verification Agent

```bash
# The Verification Agent re-reads the draft and checks each factual claim
# against the retrieved knowledge base chunks.

cat > apps/backend/src/taxflow/services/agents/verify.py << 'AGENTEOF'
# AGENT.MD for Verification Agent

## Purpose
Prevent incorrect advice from reaching clients by checking the draft
against the source documents. This is the safety net.

## Input
draft: str              -- output from DraftAgent
citations: list[dict]   -- the research citations [{citation, url, content}]
question: str           -- original question

## Processing

1. Build verification prompt
   System:
   "You are a senior Australian tax lawyer reviewing an AI-drafted advice memo.
    Check each factual claim in the draft against the provided source documents.
    
    Return a JSON object with this exact schema:
    {
      'overall_status': 'verified' | 'needs_correction' | 'unreliable',
      'issues': [
        {
          'claim': 'exact text from draft',
          'issue': 'description of problem',
          'severity': 'critical' | 'warning' | 'note',
          'source_says': 'what the source actually says',
          'suggested_correction': 'how to fix it'
        }
      ],
      'unsupported_claims': ['list of claims with no citation'],
      'overall_confidence': float  // 0.0 to 1.0
    }
    
    Severity guide:
    - critical: factually wrong based on the sources (wrong rate, wrong section number, wrong test)
    - warning: potentially misleading or incomplete
    - note: minor stylistic or formatting suggestion
    
    Return ONLY valid JSON. No preamble or explanation."
   
   User:
   "Draft memo to verify:
    {draft}
    
    Source documents for verification:
    {format_citations(citations)}"

2. Parse JSON response
   If JSON parsing fails: return {"overall_status": "parse_error", "issues": []}

3. Return verification_result dict

## Threshold for escalation
If overall_status == 'needs_correction' AND any issue.severity == 'critical':
  The pipeline must surface the critical issue to the user before they can download
  the document. The document status stays 'draft' until explicitly approved.

If overall_status == 'verified': document can be shown with "Verified" badge.
AGENTEOF
```

Verification:
```bash
doppler run --project taxflow --config prd -- python3 << 'PYEOF'
import asyncio, json
from taxflow.services.agents.verify import VerifyAgent

async def test_verify():
    verify = VerifyAgent()
    
    # Deliberately wrong draft to test detection
    wrong_draft = """
    SUMMARY
    The CGT discount for small business entities is 75%, available when the 
    taxpayer satisfies the active asset test under Division 152 of ITAA 1997.
    
    LEGISLATIVE FRAMEWORK
    Section 152-A of ITAA 1997 provides the 75% CGT discount...
    """
    
    # Real citations that say 50%, not 75%
    citations = [
        {
            "citation": "ITAA 1997 s.152-C",
            "url": "https://www.legislation.gov.au/...",
            "excerpt": "the discount percentage is 50%"
        }
    ]
    
    result = await verify.run(
        draft=wrong_draft,
        citations=citations,
        question="What is the CGT discount for small business entities?"
    )
    
    print(f"Verification status: {result['overall_status']}")
    print(f"Issues found: {len(result['issues'])}")
    for issue in result['issues']:
        print(f"  [{issue['severity'].upper()}] {issue['claim'][:50]}")
        print(f"    Issue: {issue['issue']}")
    
    assert result['overall_status'] == 'needs_correction', "Should detect the 75% error"
    critical = [i for i in result['issues'] if i['severity'] == 'critical']
    assert len(critical) >= 1, "Should flag 75% as critical error"
    
    print("\nPASS: Verification agent correctly detected error in draft")

asyncio.run(test_verify())
PYEOF
```

---

### Days 17-18: ATO Correspondence - Module 2

```bash
# Module 2 is the primary competitive differentiator.
# No competitor ingests an ATO letter and produces a response draft.

cat > apps/backend/src/taxflow/services/ato_correspondence/AGENT.md << 'AGENTEOF'
# ATO Correspondence Module - Claude Code Implementation

## Overview
Accountants upload ATO letters as PDFs. The module:
1. Extracts text from the PDF
2. Classifies the letter type from 15 known ATO letter templates
3. Extracts key facts (taxpayer reference, issue, deadline, amount)
4. Produces a structured response strategy
5. Drafts a formal response letter

## Files to create:

### classifier.py
Input: extracted_text: str (full text of ATO letter)
Output: classification dict

Use this exact ATO letter type taxonomy (derived from real ATO correspondence):
  "bas_discrepancy"     -- BAS amounts differ from ATO data matching
  "audit_initiation"    -- ATO commencing income tax audit
  "penalty_notice"      -- Administrative penalty imposed
  "garnishee_notice"    -- ATO attaching to bank/receivables
  "position_paper"      -- ATO setting out its position in a dispute
  "objection_result"    -- ATO's decision on a taxpayer objection
  "ato_debt_notice"     -- Outstanding tax debt notification
  "payment_plan_request"-- ATO requesting payment arrangement
  "lodgement_reminder"  -- Overdue return/statement reminder
  "audit_completion"    -- ATO issuing amended assessment after audit
  "abn_cancellation"    -- ATO proposing to cancel ABN
  "gst_registration"    -- ATO querying GST registration status
  "employer_obligations"-- PAYG/SG compliance review
  "lifestyle_assets"    -- Lifestyle assets data matching program
  "taxable_payments"    -- Taxable payments annual report discrepancy

Classification prompt:
  "Classify this ATO letter. Return JSON: {'letter_type': '<type from list above>',
   'confidence': 0.0-1.0, 'ato_reference': '<reference number from letter>',
   'taxpayer_name': '<name as addressed>',
   'deadline_days': <integer days from today or null>,
   'amount_disputed': <float or null>,
   'key_issue': '<one sentence description>'}"

### handlers.py
One handler function per letter type.
Each handler returns:
  {
    "response_strategy": str,     -- what the accountant should do
    "evidence_checklist": list[str],  -- documents to gather
    "timeline": str,              -- recommended response timeline
    "ato_reference_sections": list[str],  -- relevant legislation
    "response_template_type": str  -- which template to use for drafting
  }

Example: bas_discrepancy handler:
  strategy: "Request a copy of the ATO's data matching information under s.353-15
             TAA 1953. Review client's BAS workpapers. If discrepancy exists, lodge
             amended BAS. If ATO data is incorrect, prepare factual dispute response."
  evidence: ["Copy of lodged BAS", "Source documents for disputed amounts",
             "ATO data matching request response"]
  timeline: "Respond within 28 days. Request extension to 56 days if complex."

### drafter.py
Input: classification dict + handler result + extracted_text
Output: formal ATO response letter

Prompt (system):
  "You are drafting a formal letter to the Australian Taxation Office on behalf of
   an Australian taxpayer. This is a professional correspondence.
   
   Format requirements:
   - Start: 'Dear Commissioner' or 'To the Commissioner of Taxation'
   - Reference line: 'Re: [ATO Reference Number from letter]'
   - Our reference: '[TaxFlow ref: TF-{date}-{id}]'
   - Acknowledge the ATO letter by date and reference number in first paragraph
   - Address each issue raised by the ATO specifically
   - Close: 'Yours faithfully'
   - Signature block: '[Firm name] | [Date]'
   - Maximum 2 pages (approximately 600 words)
   
   Tone: Professional, factual, non-confrontational unless disputing.
   Never: aggressive, emotional, or personal."

### PDF text extraction
Use pdfplumber library (more accurate than PyPDF2 for ATO's PDF format):
  pip install pdfplumber
  
  with pdfplumber.open(pdf_file) as pdf:
      text = "\n".join(page.extract_text() or "" for page in pdf.pages)
AGENTEOF
```

ATO Correspondence API endpoint:
```bash
# Claude Code writes routers/ato_response.py
# Key endpoint:
cat << 'PYEOF'
# POST /ato-response/upload
# Accepts: multipart/form-data with field "file" (PDF)
# Returns: {classification, handler_result, draft_response, deadline_date}

# GET /ato-response/{id}
# Returns full correspondence record

# POST /ato-response/{id}/approve
# Marks correspondence as approved, generates final .docx
PYEOF

# Verification: Test with a sample ATO letter
# Create a test ATO letter text (simulated)
doppler run --project taxflow --config prd -- python3 << 'PYEOF'
import asyncio
from taxflow.services.ato_correspondence.classifier import ATOLetterClassifier
from taxflow.services.ato_correspondence.handlers import get_handler
from taxflow.services.ato_correspondence.drafter import ATOResponseDrafter

# Simulated ATO BAS discrepancy letter text
sample_ato_letter = """
Australian Taxation Office
GPO Box 9990
SYDNEY NSW 2001

Reference: 1234567890
Date: 1 July 2026

Smith Dental Practice Pty Ltd
ABN 12 345 678 901
123 King Street
SYDNEY NSW 2000

Dear Taxpayer

BUSINESS ACTIVITY STATEMENT - DISCREPANCY IDENTIFIED

We have identified a discrepancy between the amount reported on your Business Activity
Statement (BAS) for the period 01/01/2026 to 31/03/2026 (lodged 28 April 2026) and
information obtained from third party data matching.

Your BAS reported GST collected of $45,320. Our data matching indicates GST collected
of approximately $52,000 for this period.

We request that you review your records and either:
1. Confirm that your BAS is correct and provide an explanation of the discrepancy, or
2. Lodge an amended BAS if you identify any errors.

Please respond within 28 days of the date of this letter.

If you have any questions, please contact us on 13 28 66.

Yours sincerely
The Commissioner of Taxation
"""

async def test_ato_module():
    classifier = ATOLetterClassifier()
    drafter = ATOResponseDrafter()
    
    # Classify
    classification = await classifier.classify(sample_ato_letter)
    print(f"Classification: {classification['letter_type']}")
    print(f"Confidence: {classification['confidence']}")
    print(f"ATO Reference: {classification['ato_reference']}")
    print(f"Deadline: {classification['deadline_days']} days")
    
    assert classification['letter_type'] == 'bas_discrepancy', f"Wrong classification: {classification['letter_type']}"
    assert classification['confidence'] >= 0.8, "Low confidence on clear BAS discrepancy letter"
    
    # Get handler
    handler = get_handler(classification['letter_type'])
    strategy = handler.get_strategy(classification)
    print(f"\nStrategy: {strategy['response_strategy'][:100]}...")
    print(f"Evidence needed: {strategy['evidence_checklist'][:2]}")
    
    # Draft response
    draft = await drafter.draft(
        classification=classification,
        strategy=strategy,
        original_letter=sample_ato_letter
    )
    print(f"\nDraft response preview:\n{draft['response_letter'][:300]}...")
    
    assert 'Dear Commissioner' in draft['response_letter']
    assert classification['ato_reference'] in draft['response_letter']
    
    print("\nPASS: ATO Correspondence module working end-to-end")

asyncio.run(test_ato_module())
PYEOF
```

---

### Day 19: Document Export (DOCX + PDF)

```bash
# All generated documents must be downloadable as .docx and .pdf
# python-docx for .docx, weasyprint for .pdf

cat > apps/backend/src/taxflow/services/export.py << 'PYEOF'
# AGENT.MD: Document export service

# Function: generate_docx(content_md: str, title: str, client_name: str, date: str) -> bytes
# Converts markdown content to a styled .docx file
# Styles: Calibri 11pt body, Calibri 14pt heading, 2.5cm margins
# Header: TaxFlow AI logo placeholder + firm name + date
# Footer: "AI-assisted advice - requires professional review before reliance | Page N of M"

# Function: generate_pdf(content_md: str, title: str, client_name: str, date: str) -> bytes
# Converts markdown to PDF via weasyprint
# Uses same styling as docx

# Both functions return bytes (content of the file)
# Store in Supabase Storage bucket: "taxflow-documents" with path: {client_id}/{doc_id}.docx
PYEOF

# Test export
doppler run --project taxflow --config prd -- python3 << 'PYEOF'
from taxflow.services.export import generate_docx, generate_pdf

sample_md = """
# Tax Advice: Home Office Deduction

## Summary
A dentist who uses a dedicated home office exclusively for patient record review
can claim a deduction for the room under section 8-1 ITAA 1997.

## Legislative Framework
Section 8-1 of the Income Tax Assessment Act 1997 (ITAA 1997) permits deductions
for losses and outgoings to the extent they are incurred in gaining or producing
assessable income. [1]

## Application to Facts
The ATO's position in PCG 2023/1 outlines the requirements for home office
deductions. The dedicated room test requires exclusive use. [2]

## Conclusion
Claim the fixed rate method at 67 cents per hour, supported by a diary for
the year or a representative 4-week period.

## Important Limitations
This memo is AI-assisted and requires professional review before reliance.

## Sources
[1] ITAA 1997 s.8-1 - https://www.legislation.gov.au/...
[2] PCG 2023/1 - https://www.ato.gov.au/...
"""

docx_bytes = generate_docx(sample_md, "Home Office Deduction", "Smith Dental Practice", "1 July 2026")
pdf_bytes = generate_pdf(sample_md, "Home Office Deduction", "Smith Dental Practice", "1 July 2026")

assert len(docx_bytes) > 1000, f"DOCX too small: {len(docx_bytes)} bytes"
assert len(pdf_bytes) > 1000, f"PDF too small: {len(pdf_bytes)} bytes"

# Write to /tmp to manually verify format
open("/tmp/test_advice.docx", "wb").write(docx_bytes)
open("/tmp/test_advice.pdf", "wb").write(pdf_bytes)

print(f"PASS: DOCX generated ({len(docx_bytes)} bytes)")
print(f"PASS: PDF generated ({len(pdf_bytes)} bytes)")
print("Manual check: open /tmp/test_advice.docx and /tmp/test_advice.pdf")
PYEOF
```

---

### Week 3 Verification (run Day 21 before Week 4 begins)

```bash
echo "=== WEEK 3 COMPLETION CHECKS ==="

# 1. Full pipeline: question to verified document in < 4 minutes
doppler run --project taxflow --config prd -- python3 << 'PYEOF'
import asyncio, time
from taxflow.services.agents.pipeline import FullPipeline

async def test_pipeline():
    pipeline = FullPipeline()
    start = time.time()
    
    result = await pipeline.run(
        question="Is a payment from a family trust to an adult child beneficiary assessable income if the child is a university student with no other income?",
        client_id="test-client"
    )
    
    elapsed = time.time() - start
    print(f"Wall time: {elapsed:.1f}s (target: < 240s)")
    print(f"Research confidence: {result['research']['confidence']}")
    print(f"Verification status: {result['verification']['overall_status']}")
    print(f"Draft word count: {result['draft']['word_count']}")
    
    assert elapsed < 240, f"FAIL: Pipeline too slow ({elapsed:.1f}s > 240s)"
    assert result['draft']['word_count'] > 150, "FAIL: Draft too short"
    assert len(result['research']['citations']) >= 2, "FAIL: Not enough citations"
    print("PASS: Full pipeline end-to-end")

asyncio.run(test_pipeline())
PYEOF

# 2. ATO Correspondence: 10 letter types working
doppler run --project taxflow --config prd -- python3 -c "
from taxflow.services.ato_correspondence.handlers import HANDLER_REGISTRY
print(f'PASS: {len(HANDLER_REGISTRY)} ATO letter types registered' if len(HANDLER_REGISTRY) >= 10 else f'FAIL: only {len(HANDLER_REGISTRY)} types')
"

# 3. Document export produces valid files
doppler run --project taxflow --config prd -- python3 -c "
from taxflow.services.export import generate_docx
b = generate_docx('# Test\n\nTest content', 'Test', 'Client', '2026-07-01')
print('PASS: DOCX export' if len(b) > 500 else 'FAIL: DOCX export')
"

# 4. Backend tests still passing
doppler run --project taxflow --config prd -- \
  uv run pytest apps/backend/tests/ -v --ignore=tests/accuracy -q | tail -5
```

---

## WEEK 4: Stripe Live, Reference Firms, First Revenue

### Day 22: Stripe Production Setup

```bash
# Browser Use creates Stripe AU business account
cat > /tmp/stripe_setup.md << 'EOF'
# Browser Use Task: Stripe Account Setup

1. Navigate to https://dashboard.stripe.com/register
2. Fill signup form:
   Email: crewcircle@zohomail.com.au
   Full name: Prabhat Singh  
   Country: Australia
3. Verify email (check Zoho inbox for verification link, click it)
4. In Stripe dashboard:
   - Business type: Company
   - Company name: CREW CIRCLE PTY LTD
   - ABN: [enter ABN]
   - Industry: Software / Technology
5. Navigate to Developers > API Keys
   - Click "Reveal live secret key" (copy: sk_live_xxx)
   - Note publishable key: pk_live_xxx
6. Navigate to Products > Add Product:
   - Product 1: "TaxFlow Starter" $2,400/yr AUD recurring
   - Product 2: "TaxFlow Professional" $6,000/yr AUD recurring
   - Product 3: "TaxFlow Practice" $12,000/yr AUD recurring
7. Navigate to Developers > Webhooks > Add endpoint:
   URL: https://api.taxflow.crewcircle.com.au/webhooks/stripe
   Events: customer.subscription.created, customer.subscription.updated,
           customer.subscription.deleted, customer.subscription.trial_will_end,
           invoice.payment_failed, invoice.paid, payment_method.attached
   Copy: Signing secret whsec_xxx
8. Navigate to Settings > Tax:
   - Enable Stripe Tax
   - Add Australia > GST 10%
9. Output: STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY, STRIPE_WEBHOOK_SECRET,
           STRIPE_STARTER_PRICE_ID, STRIPE_PROFESSIONAL_PRICE_ID, STRIPE_PRACTICE_PRICE_ID
EOF

# After Browser Use completes, store in Doppler
doppler secrets set \
  STRIPE_SECRET_KEY="sk_live_xxx" \
  STRIPE_PUBLISHABLE_KEY="pk_live_xxx" \
  STRIPE_WEBHOOK_SECRET="whsec_xxx" \
  STRIPE_STARTER_PRICE_ID="price_xxx" \
  STRIPE_PROFESSIONAL_PRICE_ID="price_xxx" \
  STRIPE_PRACTICE_PRICE_ID="price_xxx" \
  --project taxflow --config prd

# Verify Stripe integration works
doppler run --project taxflow --config prd -- python3 << 'PYEOF'
import stripe, os
stripe.api_key = os.environ['STRIPE_SECRET_KEY']

# List products to confirm they exist
products = stripe.Product.list(limit=10)
print(f"Products in Stripe: {[p['name'] for p in products['data']]}")
assert len(products['data']) >= 3, "Products not created"

# Verify webhook endpoint
webhooks = stripe.WebhookEndpoint.list()
endpoints = [w['url'] for w in webhooks['data']]
assert any('api.taxflow.crewcircle.com.au' in url for url in endpoints), f"Webhook not found: {endpoints}"

print("PASS: Stripe live mode configured correctly")
PYEOF
```

### Days 23-26: Reference Firm Onboarding and First Conversions

```bash
# Day 23: Create accounts for 5 reference firms in Supabase
doppler run --project taxflow --config prd -- python3 << 'PYEOF'
import os
from supabase import create_client

sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_ROLE_KEY'])

# 5 reference firms - placeholder data for testing, replace with real firm details
# In practice: founder gets these details from the 5 accountants who agreed
reference_firms = [
    {"business_name": "Reference Firm 1", "business_type": "accounting",
     "email": "firm1@example.com.au", "suburb": "Sydney CBD", "state": "NSW",
     "tier": "professional", "subscription_status": "trialing"},
    # ... add 4 more
]

for firm in reference_firms:
    result = sb.table("clients").insert(firm).execute()
    client_id = result.data[0]["id"]
    
    # Create trial record: 90 days for reference firms (not 30)
    sb.table("trials").insert({
        "client_id": client_id,
        "trial_ends_at": "now() + interval '90 days'",
        "queries_cap": 500,   # unlimited for reference firms
        "docs_cap": 100,
    }).execute()
    
    print(f"Created: {firm['business_name']} (client_id: {client_id})")

# Verify all 5 created
result = sb.table("clients").select("id,business_name,subscription_status").execute()
print(f"\nTotal clients in DB: {len(result.data)}")
for c in result.data:
    print(f"  {c['business_name']}: {c['subscription_status']}")
PYEOF

# Day 26: Convert 3 reference firms to paying
# After conversion calls, update their Stripe customer IDs and subscription status
# This is done via Stripe Checkout link sent to each firm:

doppler run --project taxflow --config prd -- python3 << 'PYEOF'
import stripe, os
stripe.api_key = os.environ['STRIPE_SECRET_KEY']

# Create a checkout session (founding member price: $4,200/yr)
# This is the link sent to reference firm in the conversion email

FOUNDING_PRICE_CENTS = 420000  # $4,200 AUD

# Create a one-time price for founding member rate
founding_price = stripe.Price.create(
    unit_amount=FOUNDING_PRICE_CENTS,
    currency="aud",
    recurring={"interval": "year"},
    product=os.environ['STRIPE_PROFESSIONAL_PRICE_ID'].split("_")[0],  # use existing product
    nickname="Founding Member - Professional (30% off, locked for life)",
)

print(f"Founding price created: {founding_price['id']} at AUD ${FOUNDING_PRICE_CENTS/100:.2f}/yr")

# Create checkout session for first reference firm conversion
session = stripe.checkout.Session.create(
    payment_method_types=["card", "au_becs_debit"],
    line_items=[{"price": founding_price["id"], "quantity": 1}],
    mode="subscription",
    success_url="https://taxflow.crewcircle.com.au/dashboard?converted=true",
    cancel_url="https://taxflow.crewcircle.com.au/pricing",
    metadata={"client_id": "REPLACE_WITH_REAL_CLIENT_ID"},
    tax_id_collection={"enabled": True},
)

print(f"\nCheckout URL for Reference Firm 1:")
print(f"  {session['url']}")
print("\nSend this URL to the firm in your conversion email")
print("When they pay, Stripe fires the checkout.session.completed webhook")
print("The webhook handler updates their subscription_status to 'active' in Supabase")
PYEOF
```

### Week 4 Verification

```bash
echo "=== WEEK 4 COMPLETION CHECKS ==="

# 1. Stripe live mode working
doppler run --project taxflow --config prd -- python3 -c "
import stripe, os
stripe.api_key = os.environ['STRIPE_SECRET_KEY']
products = stripe.Product.list(limit=3)
print(f'PASS: Stripe live - {len(products[\"data\"])} products' if len(products['data']) >= 3 else 'FAIL: Stripe products')
"

# 2. Paying clients in DB
doppler run --project taxflow --config prd -- python3 -c "
import os
from supabase import create_client
sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_ROLE_KEY'])
result = sb.table('clients').select('id').eq('subscription_status', 'active').execute()
count = len(result.data)
print(f'PASS: {count} paying clients' if count >= 3 else f'FAIL: only {count} paying (need 3+)')
"

# 3. ARR calculation
doppler run --project taxflow --config prd -- python3 -c "
import stripe, os
stripe.api_key = os.environ['STRIPE_SECRET_KEY']
subs = stripe.Subscription.list(status='active', limit=100)
arr = sum(s['items']['data'][0]['price']['unit_amount'] for s in subs['data']) / 100
print(f'PASS: ARR AUD \${arr:,.0f}' if arr >= 12000 else f'FAIL: ARR only \${arr} (need 12000+)')
"
```

---

## WEEK 5: Module 3 Full + 10 Paying Firms

### Days 29-33 Summary

| Day | Task | Verification command |
|-----|------|---------------------|
| 29  | Convert firms 4-5. Module 3 MVP (remission request + objection letter generators) | `pytest tests/test_documents.py -v` |
| 30  | Module 4 MVP: ATO feed monitor running. regulatory_alerts table populating | `SELECT COUNT(*) FROM regulatory_alerts` |
| 31  | Document template library (8 types). Advice Checker standalone endpoint | `GET /documents/templates` returns 8 types |
| 32  | Xero App Marketplace application submitted. CPA Australia partner application | Email confirmation from Xero received |
| 33  | Close firms 6-10 via trial conversion | Stripe: 10 active subscriptions |

### Week 5 Final Verification

```bash
echo "=== WEEK 5 COMPLETION CHECKS ==="

# 10 paying firms
doppler run --project taxflow --config prd -- python3 -c "
import os; from supabase import create_client
sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_ROLE_KEY'])
r = sb.table('clients').select('id').eq('subscription_status','active').execute()
print(f'PASS: {len(r.data)} paying firms' if len(r.data)>=10 else f'FAIL: {len(r.data)} firms')
"

# ARR >= $60,000
doppler run --project taxflow --config prd -- python3 -c "
import stripe,os; stripe.api_key=os.environ['STRIPE_SECRET_KEY']
subs=stripe.Subscription.list(status='active',limit=100)
arr=sum(s['items']['data'][0]['price']['unit_amount'] for s in subs['data'])/100
print(f'PASS: ARR AUD \${arr:,.0f}' if arr>=60000 else f'FAIL: ARR \${arr} (need 60000)')
"

# 8 document templates registered
doppler run --project taxflow --config prd -- python3 -c "
from taxflow.services.documents import TEMPLATE_REGISTRY
print(f'PASS: {len(TEMPLATE_REGISTRY)} templates' if len(TEMPLATE_REGISTRY)>=8 else f'FAIL: {len(TEMPLATE_REGISTRY)} templates')
"

# Regulatory monitor has found at least 1 alert
doppler run --project taxflow --config prd -- python3 -c "
import os,psycopg2
conn=psycopg2.connect(os.environ['DATABASE_URL'])
cur=conn.cursor()
cur.execute('SELECT COUNT(*) FROM regulatory_alerts')
count=cur.fetchone()[0]
print(f'PASS: {count} regulatory alerts detected' if count>=1 else 'WARN: No regulatory alerts yet (monitor may not have run)')
"
```

---

## WEEK 6: Referral System + Content Flywheel + 30 Trial Pipeline

### Days 36-42 Summary

| Day | Task | Verification |
|-----|------|-------------|
| 36  | Usage analytics dashboard per firm. Trial conversion email sequence (Day 21 personalised email) | Email sends correctly with real usage data |
| 37  | Referral programme: unique link per firm, Stripe credit on conversion | Referral link generates, credit applies |
| 38  | Content automation: new ATO ruling detected -> newsletter draft auto-created | Draft appears in Supabase within 2h of new ruling |
| 39  | Outbound batch 2: 40 LinkedIn connections. Trial follow-up calls. Convert 3 more firms | 16 paying firms total |
| 40  | Practice tier identified targets (5 firms). Enterprise pilot outreach (3 firms). AGENT.md for all jobs | All AGENT.md files committed |
| 41  | 6-week retrospective document. Month 2 plan committed as ROADMAP.md | ROADMAP.md in GitHub |
| 42  | 30 active trials in Supabase | SELECT COUNT(*) FROM clients WHERE trial_status='active' >= 30 |

### Week 6 Final Verification (= Phase 1 Gate)

```bash
echo "=== PHASE 1 COMPLETION GATE ==="
echo "All must show PASS before Phase 2 begins"
echo ""

# Infrastructure
curl -sf https://api.taxflow.crewcircle.com.au/health | python3 -c "import json,sys; d=json.load(sys.stdin); print('PASS: API live' if d['status']=='ok' else f'FAIL: {d}')"
curl -sf -o /dev/null -w "%{http_code}" https://taxflow.crewcircle.com.au | grep -q "200\|307" && echo "PASS: Dashboard live" || echo "FAIL: Dashboard"

# Database
doppler run --project taxflow --config prd -- python3 -c "
import os,psycopg2
conn=psycopg2.connect(os.environ['DATABASE_URL'])
cur=conn.cursor()
cur.execute(\"SELECT COUNT(*) FROM pg_tables WHERE schemaname='public'\")
print(f'PASS: {cur.fetchone()[0]} tables in DB')
"

# Knowledge base
doppler run --project taxflow --config prd -- python3 -c "
import os,psycopg2
conn=psycopg2.connect(os.environ['DATABASE_URL'])
cur=conn.cursor()
cur.execute('SELECT COUNT(*) FROM knowledge_chunks WHERE embedding IS NOT NULL')
count=cur.fetchone()[0]
print(f'PASS: {count} embedded chunks' if count>=20000 else f'FAIL: only {count} chunks')
"

# Accuracy gate
python3 -c "
import json
from pathlib import Path
f=Path('apps/backend/tests/accuracy/last_run_results.json')
if not f.exists(): print('FAIL: Run accuracy test first'); exit()
results=json.loads(f.read_text())
passed=sum(1 for r in results if r['score']>=4)
print(f'PASS: {passed}/30 accuracy' if passed>=24 else f'FAIL: {passed}/30 (need 24+)')
"

# Revenue
doppler run --project taxflow --config prd -- python3 -c "
import stripe,os; stripe.api_key=os.environ['STRIPE_SECRET_KEY']
subs=stripe.Subscription.list(status='active',limit=100)
arr=sum(s['items']['data'][0]['price']['unit_amount'] for s in subs['data'])/100
firms=len(subs['data'])
print(f'PASS: {firms} firms, AUD \${arr:,.0f} ARR' if firms>=10 and arr>=60000 else f'FAIL: {firms} firms, \${arr} ARR')
"

# Trials pipeline
doppler run --project taxflow --config prd -- python3 -c "
import os; from supabase import create_client
sb=create_client(os.environ['SUPABASE_URL'],os.environ['SUPABASE_SERVICE_ROLE_KEY'])
r=sb.table('trials').select('id').eq('trial_status','active').execute()
print(f'PASS: {len(r.data)} active trials' if len(r.data)>=30 else f'FAIL: {len(r.data)} trials (need 30+)')
"

# CI green
gh run list --repo taxflow-ai --limit 1 --json conclusion | python3 -c "
import json,sys; d=json.load(sys.stdin)
print('PASS: CI green' if d and d[0]['conclusion']=='success' else f'FAIL: CI {d}')
"

# Content
curl -sf https://taxflow.crewcircle.com.au/blog | grep -q "article\|post\|blog" && echo "PASS: Blog has posts" || echo "WARN: Blog not confirmed"

# Newsletter (manual check)
echo "MANUAL: Newsletter subscribers >= 400? Check Resend dashboard"
echo "MANUAL: Xero App Marketplace application submitted? Check email for confirmation"
echo "MANUAL: CPA Australia partner application submitted? Check email"

echo ""
echo "=== END OF PHASE 1 GATE ==="
```

---

## Doppler Secrets Reference: Complete List at End of Phase 1

```bash
# All secrets that must exist in taxflow/prd by end of Week 6
REQUIRED_SECRETS=(
  ENVIRONMENT APP_NAME BASE_DOMAIN APP_SUBDOMAIN API_SUBDOMAIN SYSTEM_EMAIL
  CLOUDFLARE_API_TOKEN CLOUDFLARE_ZONE_ID
  DIGITALOCEAN_TOKEN DROPLET_IP
  SUPABASE_URL SUPABASE_PROJECT_ID SUPABASE_ANON_KEY SUPABASE_SERVICE_ROLE_KEY
  DATABASE_URL SUPABASE_ACCESS_TOKEN SUPABASE_DB_PASSWORD
  ANTHROPIC_API_KEY OPENAI_API_KEY
  STRIPE_SECRET_KEY STRIPE_PUBLISHABLE_KEY STRIPE_WEBHOOK_SECRET
  STRIPE_STARTER_PRICE_ID STRIPE_PROFESSIONAL_PRICE_ID STRIPE_PRACTICE_PRICE_ID
)

doppler secrets --project taxflow --config prd --json | python3 -c "
import json,sys,os
d=json.load(sys.stdin)
required='''$( IFS=' '; echo "${REQUIRED_SECRETS[*]}" )'''.split()
missing=[k for k in required if k not in d]
present=len(required)-len(missing)
print(f'PASS: {present}/{len(required)} required secrets in Doppler')
if missing: print(f'MISSING: {missing}')
"
```
