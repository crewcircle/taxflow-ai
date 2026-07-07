# TaxFlow AI - Phase 1, Week 2: Research Agent

## Week 2 Objective

By end of Day 14: Module 1 (Research and Advisory) returns cited AU tax answers at
80% accuracy on a 30-question test set curated by the advisory board.
The query interface streams real results with numbered citations.

All work done by Claude Code. All verification is automated.

---

## DAY 8: Research Agent Core

### Step 8.1 - AGENT.md for Research Agent

```bash
cd ~/taxflow-ai

cat > apps/backend/src/taxflow/services/agents/AGENT.md << 'AGENTEOF'
# Research Agent - Claude Code Implementation Instructions

## File: apps/backend/src/taxflow/services/agents/research.py

The Research Agent is a RAG pipeline. It answers AU tax questions by retrieving
relevant chunks from the knowledge base and generating a cited response.

## Input
question: str  -- the accountant's question in plain English
client_id: str -- for firm-knowledge blending
filters: dict  -- optional, e.g. {"source_types": ["ato_ruling", "legislation"]}

## Processing pipeline

Step 1 - Retrieve relevant chunks (hybrid search)
  Call knowledge.retrieval.hybrid_search(question, top_k=10)
  This returns chunks sorted by RRF score (semantic + BM25 fusion)
  
  Also run a firm-specific retrieval:
  SELECT id, content, 1 - (embedding <=> $query_embedding) as sim
  FROM firm_knowledge
  WHERE client_id = $client_id
  ORDER BY embedding <=> $query_embedding
  LIMIT 3
  
  Merge: firm_knowledge chunks get weight 1.5x (they are more specific to the firm)
  Final context: top 8 global chunks + top 2 firm chunks = 10 chunks total

Step 2 - Build context string
  For each chunk, format as:
  [N] Citation: {chunk.citation}
  Source: {chunk.source_url}
  Content: {chunk.content}
  ---
  
  Truncate context to 60,000 tokens total if needed (Haiku context window is 200K but
  we stay well under to keep costs low and latency low)

Step 3 - Generate response
  System prompt (exact, do not change):
  '''
  You are TaxFlow AI, an AI assistant for Australian public practice accounting firms.
  You answer questions about Australian tax law with precision and citations.
  
  Rules:
  1. Base your answer ONLY on the provided source documents. Do not use training knowledge.
  2. Every factual claim must cite a specific source using [N] notation matching the context.
  3. Use Australian English spelling (organisation, licence, recognise, cheque, lodgement).
  4. Never give generic advice. Be specific to Australian law and ATO positions.
  5. If the provided context does not contain enough information, say:
     "The provided sources do not contain sufficient information to answer this question
     with confidence. Consider consulting the full text of [specific source] or requesting
     a Private Binding Ruling from the ATO."
  6. Format: 2-4 paragraphs. First paragraph: direct answer. Subsequent: analysis and
     nuance. Final: practical implications or recommended action.
  7. End with a "Sources" section listing all cited documents.
  '''
  
  User message:
  '''
  Question: {question}
  
  Source documents:
  {context_string}
  '''
  
  Model: claude-haiku-4-5 (default)
  Max tokens: 1500
  Temperature: 0 (deterministic for reproducibility)

Step 4 - Extract confidence score
  After generation, run a self-assessment prompt:
  System: "Rate the confidence of this answer 0.0-1.0 based on: source coverage,
           citation count, question specificity, source recency. Return only a float."
  User: "Question: {question}\nAnswer: {answer}\nSources used: {citation_count}"
  
  Parse float from response. If parsing fails, default to 0.5.
  
  If confidence < 0.72: re-run Step 3 with claude-sonnet-4-6 instead.
  Log model_used = 'haiku' or 'sonnet' in the queries table.

Step 5 - Parse citations
  From the generated response, extract all [N] references.
  Match each N to the corresponding chunk in the context.
  Build citations list: [{citation: str, url: str, excerpt: str (first 200 chars of chunk)}]

## Output (TypedDict)
{
    "answer": str,              -- the generated response text
    "citations": list[dict],    -- [{citation, url, excerpt}]
    "confidence": float,        -- 0.0 to 1.0
    "model_used": str,          -- 'haiku' or 'sonnet'
    "chunks_retrieved": int,    -- how many chunks were retrieved
    "input_tokens": int,
    "output_tokens": int,
    "wall_time_ms": int
}

## Streaming variant
Also implement research_stream(question, client_id) as an async generator.
Yields tokens as they arrive from the Anthropic streaming API.
Useful for the dashboard query interface (shows response building in real-time).
Use anthropic.messages.stream() context manager.
AGENTEOF
```

### Step 8.2 - Implement and Test Research Agent

```bash
# Claude Code implements research.py from the AGENT.md above
# After implementation, run the accuracy test suite

# First, create the 30-question test set
cat > apps/backend/tests/accuracy/questions.json << 'EOF'
[
  {
    "id": "q01",
    "question": "What are the requirements for a small business entity to access the 50% CGT discount under Division 152 of ITAA 1997?",
    "expected_citations": ["ITAA 1997", "TR 2007/2"],
    "expected_topics": ["CGT", "small business entity", "active asset test"]
  },
  {
    "id": "q02",
    "question": "When is a payment from a trust to a beneficiary included in the beneficiary's assessable income?",
    "expected_citations": ["ITAA 1936 s.97", "ITAA 1936 s.99A"],
    "expected_topics": ["trust distribution", "beneficiary", "assessable income"]
  },
  {
    "id": "q03",
    "question": "What is the current FBT rate and when does the FBT year run?",
    "expected_citations": ["FBT Assessment Act", "ATO"],
    "expected_topics": ["FBT rate", "FBT year", "47%"]
  },
  {
    "id": "q04",
    "question": "Is a company's payment of a shareholder's personal expenses a deemed dividend under Division 7A?",
    "expected_citations": ["ITAA 1936 s.109", "Division 7A"],
    "expected_topics": ["Division 7A", "private company", "deemed dividend"]
  },
  {
    "id": "q05",
    "question": "What is the threshold for payroll tax grouping in New South Wales and who is a member of a group?",
    "expected_citations": ["Payroll Tax Act 2007 NSW"],
    "expected_topics": ["payroll tax", "NSW", "grouping", "threshold"]
  },
  {
    "id": "q06",
    "question": "When does the ATO's 4-year amendment period for income tax assessments start?",
    "expected_citations": ["ITAA 1936 s.170", "TAA 1953"],
    "expected_topics": ["amendment period", "4 years", "Commissioner"]
  },
  {
    "id": "q07",
    "question": "What is the GST treatment of a mixed supply and how is the value apportioned?",
    "expected_citations": ["GST Act s.9-80", "GSTR 2001/8"],
    "expected_topics": ["mixed supply", "GST", "apportionment"]
  },
  {
    "id": "q08",
    "question": "What are the residency tests for an individual to be a tax resident of Australia?",
    "expected_citations": ["ITAA 1936 s.6(1)", "IT 2650"],
    "expected_topics": ["residency", "domicile test", "183-day test", "superannuation test"]
  },
  {
    "id": "q09",
    "question": "Can a company claim a deduction for a bad debt write-off and what conditions apply?",
    "expected_citations": ["ITAA 1997 s.25-35", "TR 92/18"],
    "expected_topics": ["bad debt", "deduction", "written off"]
  },
  {
    "id": "q10",
    "question": "What is the instant asset write-off threshold for the current income year?",
    "expected_citations": ["ITAA 1997 Div 40", "ATO"],
    "expected_topics": ["instant asset write-off", "threshold", "small business"]
  },
  {
    "id": "q11",
    "question": "How does the personal services income regime affect a contractor operating through a company?",
    "expected_citations": ["ITAA 1997 Part 2-42", "PSI"],
    "expected_topics": ["personal services income", "PSI", "results test", "alienation"]
  },
  {
    "id": "q12",
    "question": "What records must an employer keep to substantiate FBT car fringe benefits?",
    "expected_citations": ["FBT Assessment Act s.10A", "TD 94/19"],
    "expected_topics": ["car fringe benefit", "logbook", "records"]
  },
  {
    "id": "q13",
    "question": "Is the sale of a commercial property by a GST-registered vendor subject to GST and are there any going concern or farmland concessions?",
    "expected_citations": ["GST Act Div 38", "GSTR 2002/5"],
    "expected_topics": ["GST", "commercial property", "going concern", "farmland"]
  },
  {
    "id": "q14",
    "question": "What are the thin capitalisation rules and when do they apply to a private company with foreign debt?",
    "expected_citations": ["ITAA 1997 Div 820"],
    "expected_topics": ["thin capitalisation", "safe harbour", "arm's length debt test"]
  },
  {
    "id": "q15",
    "question": "How is a lump sum payment on termination of employment taxed and what portion is concessionally taxed?",
    "expected_citations": ["ITAA 1997 Div 83", "ITAA 1936 s.27A"],
    "expected_topics": ["employment termination payment", "ETP", "taxed element"]
  },
  {
    "id": "q16",
    "question": "What are the superannuation guarantee obligations for a sole trader paying a contractor?",
    "expected_citations": ["SGA Act s.12", "SGR 2005/1"],
    "expected_topics": ["superannuation guarantee", "contractor", "labour hire", "ordinary time earnings"]
  },
  {
    "id": "q17",
    "question": "When can a trustee make a section 100A reimbursement agreement finding and what are the tax consequences?",
    "expected_citations": ["ITAA 1936 s.100A", "TR 2022/4"],
    "expected_topics": ["s.100A", "reimbursement agreement", "family trust"]
  },
  {
    "id": "q18",
    "question": "How does the base rate entity concept affect a company's eligibility for the lower 25% corporate tax rate?",
    "expected_citations": ["ITAA 1997 s.23AA", "ITAA 1936 s.23"],
    "expected_topics": ["base rate entity", "25%", "corporate tax rate", "passive income"]
  },
  {
    "id": "q19",
    "question": "What are the eligibility conditions for a PAYG withholding variation and how does an employer apply for one?",
    "expected_citations": ["TAA 1953 s.15-15", "PAYG"],
    "expected_topics": ["PAYG variation", "withholding", "employer", "variation application"]
  },
  {
    "id": "q20",
    "question": "Is a non-compete payment received by an individual when selling their business assessable income or a capital receipt?",
    "expected_citations": ["ITAA 1997 s.6-5", "FCT v Cooling"],
    "expected_topics": ["non-compete", "capital vs income", "personal exertion"]
  },
  {
    "id": "q21",
    "question": "What are the ATO's current guidelines on tax treatment of cryptocurrency gains and losses?",
    "expected_citations": ["TD 2014/25", "ATO cryptocurrency guidance"],
    "expected_topics": ["cryptocurrency", "CGT", "trading stock", "personal use asset"]
  },
  {
    "id": "q22",
    "question": "How does the research and development tax incentive work for a small company spending $200,000 on eligible R&D?",
    "expected_citations": ["ITAA 1997 Div 355", "R&D tax incentive"],
    "expected_topics": ["R&D tax incentive", "43.5%", "refundable offset", "eligible activities"]
  },
  {
    "id": "q23",
    "question": "Can a company carry forward tax losses from a prior year and what is the continuity of ownership test?",
    "expected_citations": ["ITAA 1997 Div 165", "continuity of ownership"],
    "expected_topics": ["tax loss", "carry forward", "continuity of ownership", "same business test"]
  },
  {
    "id": "q24",
    "question": "What is the SMSF contribution cap for concessional contributions in the current financial year?",
    "expected_citations": ["ITAA 1997 s.292-25", "SIS Act"],
    "expected_topics": ["SMSF", "concessional contribution", "cap", "annual limit"]
  },
  {
    "id": "q25",
    "question": "What penalties can the ATO impose for failure to lodge a tax return on time?",
    "expected_citations": ["TAA 1953 s.286-75", "Penalty units"],
    "expected_topics": ["failure to lodge", "FTL penalty", "penalty units", "administrative penalty"]
  },
  {
    "id": "q26",
    "question": "How are professional fees deductible under section 8-1 ITAA 1997 and are legal costs for defending a personal lawsuit deductible?",
    "expected_citations": ["ITAA 1997 s.8-1", "TR 2018/2"],
    "expected_topics": ["deductibility", "professional fees", "legal costs", "personal vs business"]
  },
  {
    "id": "q27",
    "question": "What is the tax treatment of a business selling trading stock at below market value to a related party?",
    "expected_citations": ["ITAA 1997 s.70-90", "trading stock"],
    "expected_topics": ["trading stock", "market value substitution", "related party", "arm's length"]
  },
  {
    "id": "q28",
    "question": "Does the work from home shortcut method still apply and what is the current rate per hour?",
    "expected_citations": ["PCG 2023/1", "ATO work from home"],
    "expected_topics": ["work from home", "shortcut method", "67 cents", "PCG 2023/1"]
  },
  {
    "id": "q29",
    "question": "What are the requirements for a private company to pay a franked dividend and what is the benchmark rule?",
    "expected_citations": ["ITAA 1997 s.202-45", "ITAA 1997 s.203-15"],
    "expected_topics": ["franked dividend", "benchmark franking percentage", "franking account", "private company"]
  },
  {
    "id": "q30",
    "question": "When can the Commissioner apply Part IVA to rearrange a taxpayer's affairs and what must the taxpayer demonstrate to rebut it?",
    "expected_citations": ["ITAA 1936 Part IVA", "s.177C", "FCT v Spotless"],
    "expected_topics": ["Part IVA", "tax avoidance", "dominant purpose", "scheme", "tax benefit"]
  }
]
EOF

# Create the accuracy test runner
cat > apps/backend/tests/accuracy/test_research_accuracy.py << 'PYEOF'
"""
Accuracy test suite for the Research Agent.
Tests 30 AU tax questions against expected topics and citation presence.
Grade: PASS if >= 24/30 questions score >= 4/5 (80% pass rate).

This test is expensive (30 LLM calls). Run manually, not in CI.
Run: uv run pytest tests/accuracy/ -v -s
"""
import pytest
import asyncio
import json
from pathlib import Path
from taxflow.services.agents.research import ResearchAgent

QUESTIONS = json.loads((Path(__file__).parent / "questions.json").read_text())

@pytest.fixture
def agent():
    return ResearchAgent()

def score_answer(question: dict, result: dict) -> dict:
    """
    Score a research agent answer 1-5.
    5: Direct answer, correct citations, covers all expected topics
    4: Good answer, at least one expected citation, covers most topics
    3: Partial answer, some relevant content
    2: Vague or partially relevant
    1: Wrong or no relevant content
    
    Automated scoring heuristic (approximates human review):
    """
    score = 1
    answer = result.get("answer", "").lower()
    citations = [c.get("citation", "").lower() for c in result.get("citations", [])]
    
    # Check topic coverage
    expected_topics = [t.lower() for t in question.get("expected_topics", [])]
    topics_covered = sum(1 for t in expected_topics if t in answer)
    topic_ratio = topics_covered / max(len(expected_topics), 1)
    
    # Check citation presence
    expected_cits = [c.lower() for c in question.get("expected_citations", [])]
    cits_found = sum(1 for ec in expected_cits 
                    if any(ec in c for c in citations) or ec in answer)
    cit_ratio = cits_found / max(len(expected_cits), 1)
    
    # Score
    if topic_ratio >= 0.8 and cit_ratio >= 0.5:
        score = 5
    elif topic_ratio >= 0.6 and cit_ratio >= 0.3:
        score = 4
    elif topic_ratio >= 0.4:
        score = 3
    elif topic_ratio >= 0.2:
        score = 2
    
    return {
        "score": score,
        "topic_ratio": round(topic_ratio, 2),
        "cit_ratio": round(cit_ratio, 2),
        "topics_covered": topics_covered,
        "topics_expected": len(expected_topics),
        "citations_found": cits_found,
        "citations_expected": len(expected_cits),
    }

@pytest.mark.asyncio
async def test_research_accuracy_suite(agent):
    results = []
    passed = 0
    
    for q in QUESTIONS:
        print(f"\n[{q['id']}] {q['question'][:80]}...")
        
        result = await agent.run(
            question=q["question"],
            client_id="test-client-accuracy",
        )
        
        scoring = score_answer(q, result)
        results.append({
            "id": q["id"],
            "question": q["question"][:60],
            "score": scoring["score"],
            "confidence": result.get("confidence"),
            "model": result.get("model_used"),
            "wall_ms": result.get("wall_time_ms"),
            **scoring,
        })
        
        if scoring["score"] >= 4:
            passed += 1
            print(f"  PASS score={scoring['score']}/5 topics={scoring['topic_ratio']} cits={scoring['cit_ratio']}")
        else:
            print(f"  FAIL score={scoring['score']}/5 topics={scoring['topic_ratio']} cits={scoring['cit_ratio']}")
            print(f"  Answer preview: {result.get('answer', '')[:200]}")
    
    pass_rate = passed / len(QUESTIONS)
    print(f"\n=== ACCURACY SUMMARY ===")
    print(f"Passed: {passed}/{len(QUESTIONS)} ({pass_rate:.1%})")
    print(f"Target: 24/30 (80%)")
    
    # Print failures for debugging
    failures = [r for r in results if r["score"] < 4]
    if failures:
        print(f"\nFailures ({len(failures)}):")
        for f in failures:
            print(f"  [{f['id']}] score={f['score']} - {f['question']}")
    
    # Save full results
    Path("tests/accuracy/last_run_results.json").write_text(
        json.dumps(results, indent=2)
    )
    
    assert pass_rate >= 0.80, (
        f"Accuracy gate FAILED: {passed}/{len(QUESTIONS)} ({pass_rate:.1%}) < 80% target. "
        f"See tests/accuracy/last_run_results.json for details."
    )
PYEOF

echo "Accuracy test suite created"
```

### Step 8.3 - Wire Research Agent to API Endpoint

```bash
# Claude Code updates routers/query.py to call ResearchAgent
# Key implementation points:

cat > apps/backend/src/taxflow/routers/query.py << 'PYEOF'
"""
Query router. Handles research queries through the full agent pipeline.
All endpoints require valid Supabase JWT (enforced by auth middleware).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from taxflow.middleware.auth import get_current_client
from taxflow.middleware.trial_gate import check_trial_gate, increment_usage
from taxflow.services.agents.research import ResearchAgent
from taxflow.db import get_db
import json
import time

router = APIRouter(prefix="/query", tags=["query"])
agent = ResearchAgent()

class QueryRequest(BaseModel):
    question: str
    module: str = "research"

@router.post("")
async def submit_query(
    body: QueryRequest,
    client=Depends(get_current_client),
    _trial=Depends(check_trial_gate),
    db=Depends(get_db),
):
    start = time.time()
    
    # Create query record
    query_row = await db.table("queries").insert({
        "client_id": client["id"],
        "user_email": client["email"],
        "question": body.question,
        "module": body.module,
        "status": "processing",
    }).execute()
    query_id = query_row.data[0]["id"]
    
    try:
        result = await agent.run(
            question=body.question,
            client_id=client["id"],
        )
        
        # Update query record with result
        await db.table("queries").update({
            "status": "completed",
            "final_answer": result["answer"],
            "citations": result["citations"],
            "confidence_score": result["confidence"],
            "model_used": result["model_used"],
            "input_tokens": result["input_tokens"],
            "output_tokens": result["output_tokens"],
            "wall_time_ms": int((time.time() - start) * 1000),
            "completed_at": "now()",
        }).eq("id", query_id).execute()
        
        # Increment trial usage
        await increment_usage(client["id"], "queries")
        
        return {
            "query_id": query_id,
            "answer": result["answer"],
            "citations": result["citations"],
            "confidence": result["confidence"],
            "model_used": result["model_used"],
        }
    
    except Exception as e:
        await db.table("queries").update({
            "status": "failed",
            "error_message": str(e),
        }).eq("id", query_id).execute()
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")


@router.get("/stream/{query_id}")
async def stream_query(
    query_id: str,
    question: str,
    client=Depends(get_current_client),
):
    """Server-Sent Events stream of Research Agent output."""
    
    async def generate():
        async for token in agent.run_stream(question=question, client_id=client["id"]):
            yield f"data: {json.dumps({'token': token})}\n\n"
        yield "data: [DONE]\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")
PYEOF
```

### Steps 8.4 - Day 14 Accuracy Gate

Run the 30-question accuracy test. This is the Week 2 gate.

```bash
cd ~/taxflow-ai

# Run accuracy suite (takes ~10 minutes for 30 questions)
doppler run --project taxflow --config prd -- \
  uv run pytest apps/backend/tests/accuracy/test_research_accuracy.py -v -s 2>&1 | tee /tmp/accuracy_run.log

# Parse results
python3 << 'PYEOF'
import json
from pathlib import Path

results_file = Path("apps/backend/tests/accuracy/last_run_results.json")
if not results_file.exists():
    print("FAIL: No results file found. Did the test run?")
    exit(1)

results = json.loads(results_file.read_text())
passed = sum(1 for r in results if r["score"] >= 4)
total = len(results)
rate = passed/total

print(f"=== WEEK 2 ACCURACY GATE ===")
print(f"Score: {passed}/{total} ({rate:.1%})")
print(f"Target: 24/30 (80%)")
print(f"Status: {'PASS - Week 2 gate cleared' if rate >= 0.80 else 'FAIL - iterate before Week 3'}")

if rate < 0.80:
    print("\nFailing questions (score < 4):")
    for r in results:
        if r["score"] < 4:
            print(f"  [{r['id']}] {r['question']}")
            print(f"    Topics: {r['topic_ratio']}, Citations: {r['cit_ratio']}")
PYEOF
```

If accuracy gate fails (< 80%), iterate on these in order:
1. Check if relevant chunks exist in knowledge_chunks for the failing questions
2. Improve retrieval: increase top_k from 10 to 15 for complex questions
3. Improve chunking: re-chunk legislation at section level instead of token count
4. Add missing sources: if a key ruling is missing, add it manually to the scraper

---

## DAYS 9-14: Dashboard Query Interface, Citation Rendering, Streaming

### Steps 9-10 - Connect Dashboard to Research Agent

```bash
# Claude Code updates apps/dashboard/app/dashboard/query/page.tsx

cat > apps/dashboard/app/dashboard/query/AGENT.md << 'AGENTEOF'
# Query Page - Claude Code Implementation

## Current state
The query page has a textarea and submit button but shows stub data.

## Required changes

### Connect to real API
Replace the stub response with a real SSE stream from /api/query/stream.

The flow:
1. User types question in textarea
2. User clicks "Ask TaxFlow" button
3. Button shows loading spinner
4. SSE stream opens to GET /api/query/stream?question=<encoded>
5. As tokens arrive, append them to the response area
6. When [DONE] event received, switch to complete state
7. Show "Sources" section below the response with clickable citation links

### Citation rendering
Citations come as: [{citation: "ITAA 1997 s.8-1", url: "https://...", excerpt: "..."}]
Render as numbered footnotes:
  [1] ITAA 1997 s.8-1 - Income Tax Assessment Act 1997 Section 8-1
      <excerpt text in smaller font>
      <clickable "View source" link>

### Error handling
If SSE stream errors: show inline error message "Query failed - please try again"
If confidence < 0.72 (Sonnet was used): show amber badge "Complex query - used enhanced model"

### Character counter
Textarea shows character count. Warn if question > 2000 characters.

### Copy response button
Clicking "Copy" copies the full response text (without footnotes) to clipboard.
Shows "Copied!" feedback for 2 seconds.

### Save as document button
Shows DEMO badge. On click: toast "Document generation coming in Week 3"

## TypeScript types
interface QueryResult {
  query_id: string;
  answer: string;
  citations: Array<{citation: string; url: string; excerpt: string}>;
  confidence: number;
  model_used: 'haiku' | 'sonnet';
}
AGENTEOF
```

### Steps 11-12 - Hybrid Search Tuning and Firm Knowledge Integration

```bash
# Run a diagnostic to find which queries are missing relevant chunks
doppler run --project taxflow --config prd -- python3 << 'PYEOF'
import asyncio, json
from knowledge.retrieval import hybrid_search

# Test retrieval for the 5 lowest-scoring questions from the accuracy run
failing_questions = [
    "What is the SMSF contribution cap for concessional contributions?",
    "When can the Commissioner apply Part IVA?",
    "What are the thin capitalisation rules?",
]

async def check_retrieval():
    for q in failing_questions:
        results = await hybrid_search(q, top_k=5)
        print(f"\nQuery: {q[:60]}")
        print(f"Retrieved {len(results)} chunks:")
        for r in results:
            print(f"  [{r['score']:.3f}] {r['citation']}: {r['content'][:80]}...")

asyncio.run(check_retrieval())
PYEOF
```

### Week 2 End Verification

```bash
cat << 'VERIFY'
=== WEEK 2 COMPLETION CHECKS ===
VERIFY

# 1. Accuracy gate
python3 -c "
import json
from pathlib import Path
results = json.loads(Path('apps/backend/tests/accuracy/last_run_results.json').read_text())
passed = sum(1 for r in results if r['score'] >= 4)
print(f'PASS: {passed}/30 accuracy' if passed >= 24 else f'FAIL: only {passed}/30 passed')
"

# 2. Research Agent API endpoint responds
curl -sf https://api.taxflow.crewcircle.com.au/health | python3 -c "
import json,sys; d=json.load(sys.stdin)
print('PASS: API live' if d['status']=='ok' else 'FAIL: API not ok')
"

# 3. Dashboard query page loads (basic check)
curl -sf https://taxflow.crewcircle.com.au/dashboard/query | grep -q "query\|Query" && \
  echo "PASS: Query page loads" || echo "FAIL: Query page not loading"

# 4. Knowledge base chunk count
doppler run --project taxflow --config prd -- python3 -c "
import os, psycopg2
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM knowledge_chunks WHERE embedding IS NOT NULL')
count = cur.fetchone()[0]
print(f'PASS: {count} embedded chunks' if count >= 20000 else f'WARN: only {count} chunks (target 20000)')
"

# 5. Advisory board: at least 2 responses received
echo "MANUAL: Advisory board - at least 1 response received? (check LinkedIn)"

# 6. CI still green
gh run list --repo taxflow-ai --limit 3 --json conclusion,createdAt | python3 -c "
import json,sys
runs = json.load(sys.stdin)
all_pass = all(r['conclusion'] in ('success', None) for r in runs)
print('PASS: CI green' if all_pass else f'FAIL: CI failures: {[r for r in runs if r[\"conclusion\"]==\"failure\"]}')
"
```

---

## Reference: Doppler Secrets Populated by End of Week 2

After Week 2, the following secrets must all be set in Doppler `taxflow/prd`:

```bash
doppler secrets --project taxflow --config prd --json | python3 -c "
import json,sys
d = json.load(sys.stdin)
required = [
  'ENVIRONMENT', 'APP_NAME', 'BASE_DOMAIN', 'APP_SUBDOMAIN', 'API_SUBDOMAIN',
  'SYSTEM_EMAIL', 'CLOUDFLARE_API_TOKEN', 'CLOUDFLARE_ZONE_ID',
  'DIGITALOCEAN_TOKEN', 'DROPLET_IP',
  'SUPABASE_URL', 'SUPABASE_PROJECT_ID', 'SUPABASE_ANON_KEY',
  'SUPABASE_SERVICE_ROLE_KEY', 'DATABASE_URL',
  'ANTHROPIC_API_KEY', 'OPENAI_API_KEY',
  'STRIPE_SECRET_KEY', 'STRIPE_WEBHOOK_SECRET',
]
missing = [k for k in required if k not in d]
if missing:
    print(f'FAIL: Missing secrets: {missing}')
else:
    print(f'PASS: All {len(required)} required secrets present ({len(d)} total in Doppler)')
"
```
