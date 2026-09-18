import os
import secrets
import uuid
import threading
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from prediction import run_prediction

load_dotenv()

app = FastAPI(title="RPT1 Payment Delay Prediction API")

_security = HTTPBasic()
_API_USER = os.environ["API_USERNAME"]
_API_PASS = os.environ["API_PASSWORD"]


def _require_auth(credentials: HTTPBasicCredentials = Depends(_security)):
    valid_user = secrets.compare_digest(credentials.username.encode(), _API_USER.encode())
    valid_pass = secrets.compare_digest(credentials.password.encode(), _API_PASS.encode())
    if not (valid_user and valid_pass):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials", headers={"WWW-Authenticate": "Basic"})

# In-memory job store: {job_id: {"status": ..., "result": ..., "error": ...}}
jobs: dict = {}


def _run_job(job_id: str):
    try:
        jobs[job_id]["status"] = "running"
        results_df = run_prediction()
        jobs[job_id]["status"] = "done"
        jobs[job_id]["predicted"] = len(results_df)
    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)


@app.get("/")
def health(_: None = Depends(_require_auth)):
    return {"status": "ok"}


@app.post("/predict", status_code=202)
def start_prediction(request: Request, response: Response, _: None = Depends(_require_auth)):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "running", "predicted": None, "error": None}
    thread = threading.Thread(target=_run_job, args=(job_id,), daemon=True)
    thread.start()
    response.headers["Location"] = str(request.url_for("get_prediction", job_id=job_id))
    return {"jobId": job_id, "status": "running"}


@app.get("/predict/{job_id}")
def get_prediction(job_id: str, _: None = Depends(_require_auth)):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")
    return {
        "jobId": job_id,
        "status": job["status"],
        "predicted": job.get("predicted"),
        "error": job.get("error"),
    }
