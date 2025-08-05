# 🚀 Pipeline Batch Bovespa

> Ingestão, ETL e consumo de dados do IBOV da B3 na AWS

---

## 📖 Sumário

1. [Visão Geral](#visão-geral)
2. [Arquitetura](#arquitetura)
3. [Componentes](#componentes)
4. [Configuração](#configuração)
   - [S3 Buckets](#s3-buckets)
   - [IAM Roles](#iam-roles)
   - [Lambda de Ingestão (Raw)](#lambda-de-ingestão-raw)
   - [Event Notification](#event-notification)
   - [Lambda Trigger Glue](#lambda-trigger-glue)
   - [Glue Studio – ETL Visual](#glue-studio–etl-visual)
   - [Athena & Visualizações](#athena--visualizações)
5. [Ambiente & Variáveis](#ambiente--variáveis)
6. [Queries de Exemplo](#queries-de-exemplo)
7. [Monitoramento](#monitoramento)
8. [Próximos Passos](#próximos-passos)

---

## Visão Geral

Este projeto implementa um pipeline completo para:

- **Scraping** dos dados do IBOV (B3)
- Armazenar raw em **Parquet** particionado no **S3**
- Orquestrar via **Lambda → Glue**
- Refinar dados no **Glue Studio (modo visual)**
- Publicar no **Glue Catalog**
- Consumir e visualizar no **Athena**

## Arquitetura

1. 🌐 **API B3**
2. 🟡 **LambdaScraperFiap\_Ingestão** → S3 `raw/`
3. 🟡 **Lambda\_Start\_Glue\_Job** → **Glue Studio**
4. 🔵 **Glue ETL** → S3 `refined/` + **Glue Catalog**
5. 📗 **Athena** (Query & Notebook)

## Componentes

| Componente                | Função                                                  |
| ------------------------- | ------------------------------------------------------- |
| **Lambda\_Ingestão**      | Scraping + upload Parquet raw                           |
| **S3 raw/**               | Armazena dados brutos em Parquet particionado por data  |
| **Event Notification**    | Dispara Lambda de trigger ao criar objetos em `raw/`    |
| **Lambda\_Trigger\_Glue** | Inicia o Glue Job de refinamento                        |
| **Glue Studio (ETL)**     | Transformações A, B e C + grava Parquet refinado        |
| **S3 refined/**           | Armazena dados refinados particionados por data e setor |
| **Glue Data Catalog**     | Tabela `default.tb_ibov_refined` criada/atualizada      |
| **AWS Athena**            | Consulta SQL, criação de views e notebooks com gráficos |

## Configuração

### S3 Buckets

```text
tech-challenge-bovespa/
├── raw/       # Parquet raw particionado (date=YYYY-MM-DD)
└── refined/   # Parquet refinado particionado (Data=…/Codigo=…)
```

### Lambda de Ingestão (Raw)

**Função:** `LambdaScraperFiap`\
**Runtime:** Python 3.11\
**Layer:** `AWSSDKPandas-Python311:7`

**Variáveis de Ambiente:**

| Nome       | Valor                    |
| ---------- | ------------------------ |
| S3\_BUCKET | `boves-dados-fiap` |

```python
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
```

### Event Notification

No **S3 → Bucket raw → Properties → Event notifications → Create Event Notification**:

- **Name:** `lambda_start_glue_job`
- **Event types:** `All object create events`
- **Prefix:** `raw/`
- **Destination:** Lambda function `lambda_start_glue_job`

### Lambda Trigger Glue

**Função:** `lambda_start_glue_job`\
**Runtime:** Python 3.11

```python
import os
import json
import logging
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

GLUE_JOB_NAME = os.environ.get("GLUE_JOB_NAME")
if not GLUE_JOB_NAME:
    logger.error("Variável de ambiente 'GLUE_JOB_NAME' não definida.")
    raise RuntimeError("Variável de ambiente 'GLUE_JOB_NAME' não definida.")

def lambda_handler(event, context):
    try:
        glue = boto3.client("glue")
        response = glue.start_job_run(JobName=GLUE_JOB_NAME)
        job_run_id = response.get("JobRunId")
        logger.info(f"Glue job '{GLUE_JOB_NAME}' iniciado: {job_run_id}")

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Glue job iniciado com sucesso.",
                "job_run_id": job_run_id
            })
        }

    except Exception as e:
        logger.exception("Erro ao iniciar Glue job")
        return {
            "statusCode": 500,
            "body": json.dumps({
                "message": "Falha ao iniciar Glue job.",
                "error": str(e)
            })
        }
```

### Glue Studio – ETL Visual

1. **Source**

   - S3 raw (`s3://<bucket>/raw/`), **Recursive**, format **Parquet**, infer schema.

2. **Transform A: Aggregate**

   - **Fields to group by (optional):** `cod`, `DataCarteira`
   - **Field to aggregate:** `part` → **sum**
   - **Field to aggregate:** `theoricalQty` → **sum**

   &#x20;*Visão da tela de configuração do nó Aggregate (Glue Studio).*

3. **Transform B: Change Schema (Apply mapping)**

   - Mapear colunas de acordo com padrão:
     | Source key          | Target key         | Data type |
     | ------------------- | ------------------ | --------- |
     | `cod`               | `codigo`           | string    |
     | `DataCarteira`      | `data`             | date      |
     | `sum(part)`         | `soma_part`        | double    |
     | `sum(theoricalQty)` | `soma_qtd_teorica` | double    |

   &#x20;*Tela de Apply mapping com nomes e tipos ajustados.*

4. **Transform C: SQL Query**

   ```sql
   SELECT
   codigo,
   data               AS data_carteira,
   soma_part,
   soma_qtd_teorica,
   DATEDIFF(current_date(), data) AS dias_desde_carteira
   FROM myDataSource
   ```

5. **Target**

   - S3 refined (`parquet`), partition keys: `Data`, `Codigo`
   - Enable **Create tables in Glue Data Catalog** → Database `default`, Table `tb_ibov_refined`

### Athena & Visualizações

#### Queries de Exemplo

```sql
-- 10 primeiros registros
SELECT * FROM default.tb_ibov_refined LIMIT 10;
```

%matplotlib inline

```python
# Notebook Athena: gerar gráficos com matplotlib
```


