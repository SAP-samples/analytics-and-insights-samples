"""
Predicts missing Days_Late values in the SAP Datasphere payment_delay_prediction_table
using the SAP AI Core RPT1.5 model. Reads all rows from V_PAYMENT_DELAY_PREDICTION —
rows with NULL Days_Late are marked as [PREDICT], all other rows are sent as context
so the model can make accurate predictions. Only the predicted rows are written into
a staging table (RPT1DEMO#PYTHON_DB_USER.PREDICTION_RESULTS).
"""
import os
import requests
import pandas as pd
from decimal import Decimal
from dotenv import load_dotenv
from hdbcli import dbapi


def get_access_token():
    response = requests.post(
        f"{os.environ['AICORE_AUTH_URL']}/oauth/token",
        auth=(os.environ["AICORE_CLIENT_ID"], os.environ["AICORE_CLIENT_SECRET"]),
        data={"grant_type": "client_credentials"},
    )
    response.raise_for_status()
    return response.json()["access_token"]


def get_hana_connection():
    return dbapi.connect(
        address=os.getenv("HANA_HOST"),
        port=int(os.getenv("HANA_PORT", 443)),
        user=os.getenv("HANA_USER"),
        password=os.getenv("HANA_PASSWORD"),
        encrypt=True,
        currentSchema=os.getenv("HANA_SCHEMA"),
    )


def read_table(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM V_PAYMENT_DELAY_PREDICTION")
    df = pd.DataFrame(cursor.fetchall(), columns=[d[0] for d in cursor.description])
    cursor.close()
    return df


def build_payload(df):
    rows = []
    for _, row in df.iterrows():
        r = {}
        for k, v in row.items():
            if isinstance(v, Decimal):
                r[k] = float(v)
            elif v is None:
                r[k] = None
            else:
                try:
                    r[k] = None if pd.isna(v) else v
                except (TypeError, ValueError):
                    r[k] = v
        if r["Days_Late"] is None:
            r["Days_Late"] = "[PREDICT]"
        rows.append(r)

    return {
        "prediction_config": {
            "target_columns": [
                {
                    "name": "Days_Late",
                    "prediction_placeholder": "[PREDICT]",
                    "task_type": "regression",
                }
            ]
        },
        "index_column": "Transaction_ID",
        "rows": rows,
    }


def call_rpt1(payload, access_token):
    base_url = os.environ["AICORE_BASE_URL"].rstrip("/")
    deployment_id = os.environ["RPT1.5LARGE_DEPLOYMENT_ID"]
    resource_group = os.environ.get("AICORE_RESOURCE_GROUP", "default")

    response = requests.post(
        f"{base_url}/v2/inference/deployments/{deployment_id}/predict",
        headers={
            "Authorization": f"Bearer {access_token}",
            "AI-Resource-Group": resource_group,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


def parse_predictions(result):
    predictions = result.get("predictions", result.get("rows", []))
    parsed = []
    for p in predictions:
        info = p["Days_Late"][0]
        low, high = info.get("confidence_interval", [None, None])
        parsed.append({
            "Transaction_ID": p["Transaction_ID"],
            "Predicted_Days_Late": round(info["prediction"], 1),
            "Confidence_Interval": f"{low} – {high}",
        })
    return pd.DataFrame(parsed)


def write_predictions(conn, results_df):
    staging_schema = os.getenv("HANA_USER")
    cursor = conn.cursor()

    # Create staging table if it doesn't exist (HANA doesn't support IF NOT EXISTS)
    cursor.execute("""
        SELECT COUNT(*) FROM SYS.TABLES
        WHERE SCHEMA_NAME = ? AND TABLE_NAME = 'PREDICTION_RESULTS'
    """, (staging_schema,))
    if cursor.fetchone()[0] == 0:
        cursor.execute(f"""
            CREATE TABLE \"{staging_schema}\".\"PREDICTION_RESULTS\" (
                \"Transaction_ID\"      NVARCHAR(50),
                \"Predicted_Days_Late\" DECIMAL(38,19),
                \"Confidence_Interval\" NVARCHAR(50),
                \"Predicted_At\"        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (\"Transaction_ID\")
            )
        """)

    # Upsert predictions
    for _, row in results_df.iterrows():
        cursor.execute(
            f'UPSERT \"{staging_schema}\".\"PREDICTION_RESULTS\" '
            f'(\"Transaction_ID\", \"Predicted_Days_Late\", \"Confidence_Interval\", \"Predicted_At\") '
            f'VALUES (?, ?, ?, CURRENT_TIMESTAMP) WITH PRIMARY KEY',
            (row["Transaction_ID"], row["Predicted_Days_Late"], row["Confidence_Interval"]),
        )
    conn.commit()
    cursor.close()


def run_prediction():
    load_dotenv(override=True)

    print("Authenticating...")
    access_token = get_access_token()
    print("Auth OK")

    print("Reading table from HANA...")
    conn = get_hana_connection()
    try:
        df = read_table(conn)

        predict_count = df["Days_Late"].isna().sum()
        print(f"Total rows: {len(df)} | To predict: {predict_count} | Context rows: {len(df) - predict_count}")

        if predict_count == 0:
            print("No rows to predict.")
            return pd.DataFrame()

        payload = build_payload(df)

        print("Calling RPT1.5 ...")
        result = call_rpt1(payload, access_token)
        print("Prediction OK")

        results_df = parse_predictions(result)

        print(f"Writing {len(results_df)} predictions back to HANA...")
        write_predictions(conn, results_df)
        print("Done.")

    finally:
        conn.close()

    context = df[df["Days_Late"].isna()][
        ["Transaction_ID", "Customer_ID", "Customer_Type", "Industry", "Region", "Invoice_Amount"]
    ].reset_index(drop=True)

    return context.merge(results_df, on="Transaction_ID", how="left")


if __name__ == "__main__":
    results = run_prediction()
    print(results.to_string(index=False))
