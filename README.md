# 🚀 Pipeline Batch Bovespa

> Ingestão, ETL e consumo de dados do IBOV da B3 na AWS

---

\
\
\


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
   - [Glue Studio – ETL Visual](#glue-studio--etl-visual)
   - [Athena & Visualizações](#athena--visualizações)
   - [Agendamento Opcional](#agendamento-opcional)
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

---

## Arquitetura



1. 🌐 **API B3**
2. 🟡 **Lambda\_Ingestão** → S3 `raw/`
3. 🟡 **Lambda\_Trigger\_Glue** → **Glue Studio**
4. 🔵 **Glue ETL** → S3 `refined/` + **Glue Catalog**
5. 📗 **Athena** (Query & Notebook)

---

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

---

## Configuração

### S3 Buckets

```text
tech-challenge-bovespa/
├── raw/       # Parquet raw particionado (date=YYYY-MM-DD)
└── refined/   # Parquet refinado particionado (date=…/Setor=…)
```

### IAM Roles

- **lambda-execution-role**

  - Políticas:
    - `AWSLambdaBasicExecutionRole`
    - Acesso S3 (`s3:GetObject`, `s3:PutObject`, `s3:ListBucket` em `raw/*` e `refined/*`)
    - `glue:StartJobRun` (para trigger)

- **glue-service-role**

  - Políticas:
    - `AWSGlueServiceRole`
    - Acesso S3 (`s3:GetObject`, `s3:PutObject`, `s3:ListBucket` em `raw/*` e `refined/*`)
    - `iam:PassRole`

---

## Lambda de Ingestão (Raw)

**Função:** `lambda_ingestao_bovespa_raw`\
**Runtime:** Python 3.11\
**Layer:** `AWSSDKPandas-Python311:7`

**Variáveis de Ambiente:**

| Nome           | Valor                    |
| -------------- | ------------------------ |
| `S3_BUCKET`    | `tech-challenge-bovespa` |
| `SEGMENT`      | `2`                      |
| `PAGE_SIZE`    | `1000`                   |
| `HTTP_TIMEOUT` | `15`                     |
| `FILENAME`     | `ibov_setor.parquet`     |

**Código (**``**):**

```python
import os
import json
import base64
import logging
from datetime import datetime
import requests
import pandas as pd
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

S3_BUCKET   = os.environ['S3_BUCKET']
SEGMENT     = os.environ.get('SEGMENT', '2')
PAGE_SIZE   = int(os.environ.get('PAGE_SIZE', 1000))
HTTP_TIMEOUT= int(os.environ.get('HTTP_TIMEOUT', 15))
FILENAME    = os.environ.get('FILENAME', 'ibov_setor.parquet')


def fetch_ibov_por_setor(segment, page_size, timeout):
    page, all_rows, data_date = 1, [], None
    session = requests.Session()

    while True:
        payload = {
            'language': 'pt-br',
            'pageNumber': page,
            'pageSize': page_size,
            'index': 'IBOV',
            'segment': segment
        }
        encoded = base64.b64encode(
            json.dumps(payload, ensure_ascii=False).encode('utf-8')
        ).decode('utf-8')
        url = f"https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall/GetPortfolioDay/{encoded}"

        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

        if data_date is None:
            date_str = data.get('header', {}).get('date')
            data_date = datetime.strptime(date_str, '%d/%m/%y').date()

        results = data.get('results', [])
        if not results:
            break

        all_rows.extend(results)
        if len(results) < page_size:
            break

        page += 1

    df = pd.DataFrame(all_rows)
    df['DataCarteira'] = data_date

    for col in ['part', 'partAcum']:
        if col in df.columns:
            df[col] = df[col].str.replace(',', '.').astype(float)

    if 'theoricalQty' in df.columns:
        df['theoricalQty'] = df['theoricalQty'] \
            .astype(str) \
            .str.replace('.', '', regex=False) \
            .astype(float)

    return df


def lambda_handler(event, context):
    try:
        df = fetch_ibov_por_setor(SEGMENT, PAGE_SIZE, HTTP_TIMEOUT)
        partition = df['DataCarteira'].iloc[0].strftime('date=%Y-%m-%d')
        s3_key = f"raw/{partition}/{FILENAME}"

        local_path = f"/tmp/{FILENAME}"
        df.to_parquet(local_path, index=False, compression='snappy')

        boto3.client('s3').upload_file(local_path, S3_BUCKET, s3_key)

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Parquet gerado e enviado com sucesso.',
                's3_uri': f's3://{S3_BUCKET}/{s3_key}'
            })
        }

    except Exception as e:
        logger.exception('Falha na ingestão')
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
```

---

## Event Notification

No **S3 → Bucket raw → Properties → Event notifications → Create Event Notification**:

- **Name:** `trigger-lambda-glue-job`
- **Event types:** `All object create events`
- **Prefix:** `raw/`
- **Destination:** Lambda function `lambda_trigger_glue_job`

---

## Lambda Trigger Glue

**Função:** `lambda_trigger_glue_job`\
**Runtime:** Python 3.11

```python
import os
import json
import logging
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)
GLUE_JOB = os.environ['GLUE_JOB_NAME']


def lambda_handler(event, context):
    try:
        client = boto3.client('glue')
        response = client.start_job_run(JobName=GLUE_JOB)
        job_id = response['JobRunId']
        logger.info(f"Glue Job iniciado: {job_id}")
        return {
            'statusCode': 200,
            'body': json.dumps({'job_run_id': job_id})
        }
    except Exception as e:
        logger.exception('Falha ao iniciar Glue Job')
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
```

---

## Glue Studio – ETL Visual

1. **Source**
   - S3 raw (`s3://<bucket>/raw/`), **Recursive**, format **Parquet**, infer schema.
2. **Aggregate**
   - Group by: `segment`, `DataCarteira`
   - Sum(`part`) → `soma_part`
   - Count(`cod`) → `total_codigo`
   - Sum(`theoricalQty`) → `soma_qtd_teorica`
3. **ApplyMapping**
   - `segment` → `Setor`
   - `DataCarteira` → `Data`
   - `soma_part`, `total_codigo`, `soma_qtd_teorica` (tipos ajustados)
4. **SQL Query**
   ```sql
   SELECT
     Setor,
     Data,
     soma_part,
     total_codigo,
     soma_qtd_teorica,
     DATEDIFF(CURRENT_DATE(), Data) AS dias_desde_carteira
   FROM myDataSource;
   ```
5. **Target**
   - S3 refined (`parquet`), partition keys: `Data`, `Setor`
   - Enable **Create tables in Glue Data Catalog** → Database `default`, Table `tb_ibov_refined`

---

## Athena & Visualizações

### Queries de Exemplo

```sql
-- 10 primeiros registros\SELECT * FROM default.tb_ibov_refined LIMIT 10;

-- Soma total de participação\SELECT SUM(soma_part) AS total_participacao FROM default.tb_ibov_refined;

-- Participação por setor
SELECT setor, SUM(soma_part) AS total_part
FROM default.tb_ibov_refined
GROUP BY setor
ORDER BY total_part DESC;
```

### Notebook Spark

```sql
%%sql
SELECT
  Setor,
  SUM(soma_part) AS total_participacao
FROM default.tb_ibov_refined
GROUP BY Setor
ORDER BY total_participacao DESC
LIMIT 10;
```

Clique em **Visualize** (📊) ou use:

```python
df = spark.sql("...sua query...")
pdf = df.toPandas()
import matplotlib.pyplot as plt
plt.figure(figsize=(10,5))
plt.bar(pdf['Setor'], pdf['total_participacao'])
%matplot plt
```

---

## Agendamento Opcional

No **EventBridge → Rules → Create Rule**:

- Schedule expression: `rate(1 day)` ou
- Cron expression: `cron(0 10 * * ? *)` (diário às 10:00 UTC)
- Target: Lambda `lambda_ingestao_bovespa_raw`

---

## Ambiente & Variáveis

| Variável        | Descrição                                | Valor Exemplo                  |
| --------------- | ---------------------------------------- | ------------------------------ |
| `S3_BUCKET`     | Bucket S3 para raw/ e refined/           | `tech-challenge-bovespa`       |
| `SEGMENT`       | Segmento IBOV na API                     | `2`                            |
| `PAGE_SIZE`     | Tamanho da página na API                 | `1000`                         |
| `HTTP_TIMEOUT`  | Timeout em segundos para requisição HTTP | `15`                           |
| `FILENAME`      | Nome do arquivo Parquet                  | `ibov_setor.parquet`           |
| `GLUE_JOB_NAME` | Nome do Glue Job de refinamento          | `glue_job_refinamento_bovespa` |

---

## Monitoramento

- **CloudWatch Logs**: Monitore logs das Lambdas e do Glue Job.
- **CloudWatch Alarms**: Configure alarmes para falhas de execução.

---

## Próximos Passos

- **CI/CD**: Deploy automatizado com AWS CDK ou CloudFormation.
- **Data Quality**: Validar dados usando AWS Deequ ou Glue DataBrew.
- **Dashboards**: Criar painéis no QuickSight ou Grafana.

