import os
import json
import base64
import requests
import pandas as pd
from datetime import datetime
import boto3

# Nome do bucket S3 definido nas variáveis de ambiente
S3_BUCKET = os.environ.get('S3_BUCKET')
if not S3_BUCKET:
    raise RuntimeError("Variável de ambiente 'S3_BUCKET' não definida.")

# Nome do arquivo Parquet a ser gerado
FILENAME = "ibov_setor2.parquet"

def fetch_ibov_por_setor(segment: str = "2", page_size: int = 1000) -> pd.DataFrame:
    """
    Faz scraping paginado dos dados IBOV por setor, retorna DataFrame com:
      - part (float)
      - partAcum (float)
      - theoricalQty (float)
      - DataCarteira (date)
      - demais colunas originais
    """
    page = 1
    all_rows = []
    data_carteira = None

    while True:
        payload = {
            "language": "pt-br",
            "pageNumber": page,
            "pageSize": page_size,
            "index": "IBOV",
            "segment": segment
        }
        # Codifica o payload em Base64 para a chamada da API
        encoded = base64.b64encode(
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
        ).decode("utf-8")
        url = f"https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall/GetPortfolioDay/{encoded}"
        
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if data_carteira is None:
            date_str = data["header"].get("date")
            if not date_str:
                raise ValueError(f"Header sem campo 'date': {data['header']}")
            data_carteira = datetime.strptime(date_str, "%d/%m/%y").date()

        results = data.get("results", [])
        if not results:
            break

        all_rows.extend(results)
        if len(results) < page_size:
            break
        page += 1

    # Constrói DataFrame
    df = pd.DataFrame(all_rows)
    df["DataCarteira"] = data_carteira

    # Converte percentuais (vírgula → ponto) e transforma em float
    for col in ["part", "partAcum"]:
        if col in df.columns:
            df[col] = df[col].str.replace(",", ".").astype(float)

    # Converte theoricalQty (string com pontos de milhar) para float
    if "theoricalQty" in df.columns:
        df["theoricalQty"] = (
            df["theoricalQty"]
              .astype(str)
              .str.replace(".", "", regex=False)  # remove separador de milhar
              .astype(float)
        )

    return df

def lambda_handler(event, context):
    """
    Handler da AWS Lambda:
      1. Busca dados via fetch_ibov_por_setor()
      2. Gera Parquet particionado por data
      3. Envia o arquivo para o bucket S3
    """
    # 1) Obter DataFrame com os dados
    df = fetch_ibov_por_setor(segment="2", page_size=1000)

    # 2) Definir partição diária no formato date=YYYY-MM-DD
    partition = df["DataCarteira"].iloc[0].strftime("date=%Y-%m-%d")
    s3_key = f"raw/{partition}/{FILENAME}"

    # 3) Salvar localmente e enviar ao S3
    local_path = f"/tmp/{FILENAME}"
    df.to_parquet(local_path, index=False, compression="snappy")

    s3 = boto3.client("s3")
    s3.upload_file(local_path, S3_BUCKET, s3_key)

    # 4) Resposta de sucesso
    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Parquet gerado e enviado ao S3 com sucesso.",
            "records": len(df),
            "s3_uri": f"s3://{S3_BUCKET}/{s3_key}"
        })
    }
