# RPT-1.5 Payment Delay Prediction — SAP Analytics Cloud Demo

[![REUSE status](https://api.reuse.software/badge/github.com/SAP-samples/analytics-and-insights-samples)](https://api.reuse.software/info/github.com/SAP-samples/analytics-and-insights-samples)

## Description

Run **RPT-1.5** predictions directly from **SAP Analytics Cloud (SAC)**.

This project is the backend for an end-to-end setup that predicts **how many days late a customer will pay**. RPT-1.5 is deployed in **SAP AI Core**, the data lives in **SAP Datasphere**, and this **FastAPI** service — deployed to **Cloud Foundry** — wraps the prediction call. From SAC, a **Multi Action** button triggers the prediction, polls for the result, and writes the predicted values back so they show up in a story.

### How it works

```
SAC Multi Action  ──POST /predict──▶  FastAPI (Cloud Foundry)
      │                                     │
      │                                     ├─ read V_PAYMENT_DELAY_PREDICTION (Datasphere / HANA)
      │                                     ├─ call RPT-1.5 deployment (AI Core)
      │                                     └─ write predictions → PREDICTION_RESULTS (HANA)
      │                                     │
      └──GET /predict/{job_id}──poll──────▶ status / result
```

1. SAC calls `POST /predict`, which starts a background job and returns a `jobId` plus a `Location` header (async pattern SAC's *External API step* expects).
2. The job reads every row from the `V_PAYMENT_DELAY_PREDICTION` view. Rows with a `NULL` `Days_Late` are marked `[PREDICT]`; all other rows are sent as **context** so RPT-1.5 can make accurate in-context predictions.
3. Predictions (value + confidence interval) are upserted into a staging table (`<HANA_USER>.PREDICTION_RESULTS`).
4. SAC polls `GET /predict/{job_id}` until the job is `done`, then reads the results back into the story.

### Project structure

| File | Purpose |
| --- | --- |
| `main.py` | FastAPI app — async `/predict` (start job) and `/predict/{job_id}` (poll), with HTTP Basic auth |
| `prediction.py` | Reads from HANA, builds the RPT-1.5 payload, calls the AI Core deployment, writes results back |
| `manifest.yaml` | Cloud Foundry deployment manifest |
| `requirements.txt` | Python dependencies |
| `.env.example` | Template for required environment variables |
| `cleaned_up_table_data.csv` | Sample dataset for local testing |

### API

All endpoints require **HTTP Basic auth** (`API_USERNAME` / `API_PASSWORD`).

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | Health check → `{"status": "ok"}` |
| `POST` | `/predict` | Start a prediction job. Returns `202` with `jobId` and a `Location` header |
| `GET` | `/predict/{job_id}` | Poll job status → `running` / `done` / `failed`, plus `predicted` count |

## Requirements

- **SAP AI Core** with an RPT-1.5 Large deployment
- **SAP Datasphere / SAP HANA Cloud** with a `V_PAYMENT_DELAY_PREDICTION` view
- **Cloud Foundry** space (SAP BTP) for deployment
- Python 3.10+

## Download and Installation

### Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in your values
uvicorn main:app --reload
```

Run the prediction pipeline directly (without the API):

```bash
python prediction.py
```

### Deploy to Cloud Foundry

```bash
cf push
```

Set the environment variables in Cloud Foundry (e.g. `cf set-env rpt1-demo <KEY> <VALUE>`) or bind them through a service — do **not** commit your `.env`.

### Configuration

Copy `.env.example` to `.env` and fill in the values:

- **SAP HANA Cloud** — `HANA_HOST`, `HANA_PORT`, `HANA_USER`, `HANA_SCHEMA`, `HANA_PASSWORD`
- **SAP AI Core** — `AICORE_AUTH_URL`, `AICORE_CLIENT_ID`, `AICORE_CLIENT_SECRET`, `AICORE_BASE_URL`, `AICORE_RESOURCE_GROUP`, `RPT1.5LARGE_DEPLOYMENT_ID`
- **API auth** — `API_USERNAME`, `API_PASSWORD`

## Known Issues

No known issues.

## How to obtain support

[Create an issue](https://github.com/SAP-samples/analytics-and-insights-samples/issues) in this repository if you find a bug or have questions about the content.

For additional support, [ask a question in SAP Community](https://answers.sap.com/questions/ask.html).

## Contributing

If you wish to contribute code, offer fixes or improvements, please send a pull request. Due to legal reasons, contributors will be asked to accept a DCO when they create the first pull request to this project. This happens in an automated fashion during the submission process. SAP uses [the standard DCO text of the Linux Foundation](https://developercertificate.org/).

## License

Copyright 2026 SAP SE or an SAP affiliate company and analytics-and-insights-samples contributors. Please see our [LICENSE](LICENSE) for copyright and license information. Detailed information including third-party components and their licensing/copyright information is available [via the REUSE tool](https://api.reuse.software/info/github.com/SAP-samples/analytics-and-insights-samples).
