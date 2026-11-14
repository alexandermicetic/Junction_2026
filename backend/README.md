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

If the backend reports that the imported `jwt` module is not PyJWT, remove the
conflicting `jwt` distribution and reinstall the required package in the same
Python environment used to launch Uvicorn:

```powershell
python -m pip uninstall jwt
python -m pip install --force-reinstall PyJWT
```
