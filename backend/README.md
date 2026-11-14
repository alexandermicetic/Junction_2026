# Backend

Python 3.11+ FastAPI prototype. Synthetic Valio data and demo orders are used. The optional Claude purchase endpoint calls Anthropic's Messages API and must be configured with a server-side API key.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload
```

Set `ANTHROPIC_API_KEY` in the ignored `backend/.env` file. `ANTHROPIC_MODEL` defaults to `claude-sonnet-5`; set `ANTHROPIC_WORKSPACE_ID` if your key is not scoped to a single workspace.

`POST /api/claude/purchase` accepts one natural-language product request. Claude chooses among live quote options, then the backend signs a quote and sends the order through the existing spend, allergen, and substitution guardrails. Orders that fail a guardrail remain `PENDING_APPROVAL`.

The interactive API documentation is available at <http://127.0.0.1:8000/docs>.
