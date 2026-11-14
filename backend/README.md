# Backend

Python 3.11+ FastAPI gateway. It uses the local product catalog and queries the configured Valio on-demand API for quote prices and availability.

`VALIO_BASE_URL` may be the service root, the `/api` root, or the `/api/ping` health-check URL. The client normalizes these forms before calling `/api/price` and `/api/availability`. Keep `VALIO_API_KEY` in `backend/.env` and never commit it.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload
```

The interactive API documentation is available at <http://127.0.0.1:8000/docs>.
