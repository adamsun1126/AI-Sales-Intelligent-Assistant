# Sales Intelligence Assistant

A two-stage AI prototype for pre-conversation intelligence on senior consulting
professionals (Director / VP / Partner level).

> 📖 For the full design rationale, frameworks, prompt engineering choices and
> cost model, read **[METHODOLOGY.md](METHODOLOGY.md)**.

---

## Quick start

```bash
# 1. Clone / unzip and enter the directory
cd AI-Sales-Intelligent-Assistant

# 2. Set up Python env (Python 3.10+)
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. Install deps
pip install -r requirements.txt

# 4. Add your Gemini API key
cp .env.example .env
# Edit .env and paste your key from https://aistudio.google.com/apikey

# 5. Export (or use python-dotenv if you prefer)
export GEMINI_API_KEY=$(grep GEMINI_API_KEY .env | cut -d= -f2)

# 6. Run
streamlit run app.py
```

The app will open at http://localhost:8501.

---

## What it does

You provide one or more of:
- LinkedIn profile text (pasted)
- Company website URL
- Freeform notes

It produces:
1. **Snapshot** + inferred role context
2. **Commercial priorities** framed via JTBD
3. **Pain points** with confidence levels
4. **Push/Pull motivation hypotheses** for the candidate
5. **Conversation angles** built on Challenger Sale principles
6. **Talking points** — specific, verifiable references to weave in
7. **Outreach drafts** — LinkedIn InMail + follow-up after no reply
8. **Exploratory questions** for the first call
9. **Red flags** to avoid
10. **Sources** for every cited fact
11. **Data gaps** — what's missing instead of guessing

---

## File map

| File | Purpose |
| --- | --- |
| `app.py` | Streamlit UI + orchestration |
| `agents.py` | Two-stage Gemini agent logic |
| `prompts.py` | System prompts + few-shot example |
| `schema.py` | Pydantic models for both stages |
| `scraper.py` | BeautifulSoup helper for About / Careers pages |
| `METHODOLOGY.md` | Full design write-up with workflow diagram |

---

## Scope explicitly excluded (prototype)

- ❌ LinkedIn scraping (user pastes text manually — ToS + cost)
- ❌ PDF / JPG ingestion (UI stubbed; OCR pipeline documented)
- ❌ User authentication / multi-user state
- ❌ Persistent history (no DB)
- ❌ CRM integration

All documented as future work in METHODOLOGY.md §10.
