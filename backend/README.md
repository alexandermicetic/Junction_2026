# Backend

<<<<<<< HEAD
Python 3.11+ FastAPI prototype. Synthetic Valio data and demo orders are used. The optional Claude purchase endpoint calls Anthropic's Messages API and must be configured with a server-side API key.
=======
Python 3.11+ FastAPI gateway. It uses the local product catalog and queries the configured Valio on-demand API for quote prices and availability.

`VALIO_BASE_URL` may be the service root, the `/api` root, or the `/api/ping` health-check URL. The client normalizes these forms before calling `/api/price` and `/api/availability`. Keep `VALIO_API_KEY` in `backend/.env` and never commit it.
>>>>>>> 5dc89e70aad3629b33f9fd7cd65bea0dcab48d74

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

If the backend reports that the imported `jwt` module is not PyJWT, remove the
conflicting `jwt` distribution and reinstall the required package in the same
Python environment used to launch Uvicorn:

```powershell
python -m pip uninstall jwt
python -m pip install --force-reinstall PyJWT
```
