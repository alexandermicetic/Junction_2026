# Backend

Python 3.11+ FastAPI walking skeleton. Data is synthetic and stored in memory; no database or external API is used.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload
```

The interactive API documentation is available at <http://127.0.0.1:8000/docs>.
