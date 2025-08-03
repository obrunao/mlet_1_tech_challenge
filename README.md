📖 Sumário
Visão Geral

Arquitetura

Componentes

Pré-requisitos

Configuração

1. S3 Buckets

2. IAM Roles

3. Lambda de Ingestão (Raw)

4. Event Notification

5. Lambda Trigger Glue

6. Glue Studio – ETL Visual

7. Athena & Visualizações

8. Agendamento (Opcional)

Ambiente & Variáveis de Ambiente

Queries de Exemplo (Athena)

Notebook Athena

Monitoramento & Logs

Próximos Passos

Visão Geral
Scrape dos dados do IBOV via API da B3 (Base64 + JSON).

Lambda de Ingestão gera Parquet particionado em data e faz upload ao S3 (bucket raw/).

S3 Event Notification dispara Lambda que starta um Glue Job.

Glue Studio (Visual) aplica transformações A, B e C, salva Parquet particionado em refined/ e cataloga dados no Glue Data Catalog.

Athena consome a tabela gerada, suporta queries, views e notebooks com gráficos.

Arquitetura

🌐 Dados IBOV (API B3)

🟡 Lambda_ingestao_bovespa_raw

🟣 S3 Raw (raw/date=YYYY-MM-DD/ibov_setor.parquet)

🟡 Lambda_trigger_glue_job

🔵 AWS Glue Studio (ETL Visual)

🟣 S3 Refined (refined/date=…/Setor=…/…)

📘 Glue Data Catalog (default.tb_ibov_refined)

📗 AWS Athena (Query Editor & Notebook)

Componentes
Componente	Descrição
Lambda_Ingestão	Scraping, limpeza e upload do raw Parquet ao S3.
S3 Raw Bucket	Armazena arquivos brutos em Parquet, particionados por data.
S3 Event Notification	Gatilho que aciona Lambda de trigger ao criar objetos em raw/.
Lambda_Trigger_Glue	Chama start_job_run no Glue Job de refinamento.
Glue Studio Job	ETL visual: agregação, renomeação, cálculo de datas, saída refinada.
S3 Refined Bucket	Armazena arquivos refinados em Parquet, particionados por data e setor.
Glue Data Catalog	Tabela tb_ibov_refined com metadados e partições.
AWS Athena	Engine de consulta SQL, views e notebooks para visualização.

Pré-requisitos
Conta AWS com permissões para Lambda, S3, Glue, Athena, EventBridge e IAM.

Python 3.11 (para desenvolvimento local).

Biblioteca Python: requests, pandas, pyarrow (via Lambda Layer ou empacotamento).

Configuração
1. S3 Buckets
Crie um bucket (ex: tech-challenge-bovespa) com as pastas lógicas:

Copiar
Editar
tech-challenge-bovespa/
├── raw/
└── refined/
2. IAM Roles
lambda-execution-role (para ambas as Lambdas):

AWSLambdaBasicExecutionRole

Acesso S3 (GetObject/ListBucket em raw/*, PutObject em raw/* e refined/*)

glue:StartJobRun (apenas para trigger)

glue-service-role:

AWSGlueServiceRole

Permissões S3 (raw/*, refined/*)

iam:PassRole se usar Glue Catalog

3. Lambda de Ingestão (Raw)
Nome: lambda_ingestao_bovespa_raw
Runtime: Python 3.11
Layers: AWSSDKPandas-Python311:7 (pandas, pyarrow, requests)

python
Copiar
Editar
import os, json, base64, logging
from datetime import datetime
import requests, pandas as pd, boto3

logger = logging.getLogger(); logger.setLevel(logging.INFO)
S3_BUCKET   = os.environ['S3_BUCKET']
SEGMENT     = os.environ.get('SEGMENT','2')
PAGE_SIZE   = int(os.environ.get('PAGE_SIZE',1000))
HTTP_TIMEOUT= int(os.environ.get('HTTP_TIMEOUT',15))
FILENAME    = os.environ.get('FILENAME','ibov_setor.parquet')

def fetch_ibov_por_setor(segment, page_size, timeout):
    page, all_rows, data_date = 1, [], None
    session = requests.Session()
    while True:
        payload = {"language":"pt-br","pageNumber":page,"pageSize":page_size,"index":"IBOV","segment":segment}
        enc = base64.b64encode(json.dumps(payload,ensure_ascii=False).encode()).decode()
        url = f"https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall/GetPortfolioDay/{enc}"
        r = session.get(url, timeout=timeout); r.raise_for_status()
        j = r.json()
        if data_date is None:
            ds = j.get("header",{}).get("date")
            data_date = datetime.strptime(ds,"%d/%m/%y").date()
        results = j.get("results",[])
        if not results: break
        all_rows.extend(results)
        if len(results)<page_size: break
        page+=1

    df = pd.DataFrame(all_rows)
    df["DataCarteira"] = data_date
    for c in ("part","partAcum"):
        if c in df: df[c]=df[c].str.replace(",",".").astype(float)
    if "theoricalQty" in df:
        df["theoricalQty"]=(
          df["theoricalQty"].astype(str).str.replace(".","",regex=False).astype(float)
        )
    return df

def lambda_handler(event, context):
    try:
        df = fetch_ibov_por_setor(SEGMENT,PAGE_SIZE,HTTP_TIMEOUT)
        partition = df["DataCarteira"].iloc[0].strftime("date=%Y-%m-%d")
        key = f"raw/{partition}/{FILENAME}"
        path = f"/tmp/{FILENAME}"
        df.to_parquet(path,index=False,compression="snappy")
        boto3.client("s3").upload_file(path,S3_BUCKET,key)
        return {"statusCode":200,"body":json.dumps({"s3_uri":f"s3://{S3_BUCKET}/{key}"})}
    except Exception as e:
        logger.exception("Falha ingestão")
        return {"statusCode":500,"body":json.dumps({"error":str(e)})}
4. Event Notification
No S3 → Bucket raw → Properties → Event notifications:

Name: trigger-lambda-glue-job

Event types: All object create events

Prefix: raw/

Destination: Lambda function → lambda_trigger_glue_job

5. Lambda Trigger Glue
Nome: lambda_trigger_glue_job
Runtime: Python 3.11

python
Copiar
Editar
import os, json, logging, boto3

logger=logging.getLogger(); logger.setLevel(logging.INFO)
GLUE_JOB = os.environ['GLUE_JOB_NAME']

def lambda_handler(event, context):
    try:
        job_id = boto3.client("glue").start_job_run(JobName=GLUE_JOB)["JobRunId"]
        logger.info(f"Glue Job iniciado: {job_id}")
        return {"statusCode":200,"body":json.dumps({"job_run_id":job_id})}
    except Exception as e:
        logger.exception("Falha Glue trigger")
        return {"statusCode":500,"body":json.dumps({"error":str(e)})}
6. Glue Studio – ETL Visual
Data source: S3 raw (s3://<bucket>/raw/, recursive, Parquet, infer schema).

Aggregate:

Group by: segment, DataCarteira

Sum(part) → soma_part

Count(cod) → total_codigo

Sum(theoricalQty) → soma_qtd_teorica

ApplyMapping:

segment → Setor (string)

DataCarteira → Data (date)

soma_part, total_codigo, soma_qtd_teorica

SQL Query:

sql
Copiar
Editar
SELECT
  Setor, Data,
  soma_part,
  total_codigo,
  soma_qtd_teorica,
  DATEDIFF(CURRENT_DATE(), Data) AS dias_desde_carteira
FROM myDataSource;
Data target: S3 refined (parquet, partition Data, Setor), habilitar Create tables in Glue Data Catalog → default.tb_ibov_refined.

7. Athena & Visualizações
Queries de exemplo
sql
Copiar
Editar
-- 10 primeiros registros
SELECT * FROM default.tb_ibov_refined LIMIT 10;

-- Soma total de participação
SELECT SUM(soma_part) AS total_participacao FROM default.tb_ibov_refined;

-- Agrupamento por setor
SELECT setor, SUM(soma_part) AS total_part FROM default.tb_ibov_refined
GROUP BY setor ORDER BY total_part DESC;
Notebook Athena (Spark)
sql
Copiar
Editar
%%sql
SELECT Setor, SUM(soma_part) AS total_participacao
FROM default.tb_ibov_refined
GROUP BY Setor
ORDER BY total_participacao DESC
LIMIT 10;
Em seguida, clique em Visualize (📊) para Bar chart ou use:

python
Copiar
Editar
df = spark.sql("...mesma query...")
pdf = df.toPandas()
import matplotlib.pyplot as plt
plt.figure(figsize=(10,5))
plt.bar(pdf['Setor'], pdf['total_participacao'])
%matplot plt
8. Agendamento (Opcional)
No EventBridge → Rules → Create rule:

Schedule expression:

rate(1 day) ou

cron(0 10 * * ? *) (diário às 10:00 UTC)

Target: Lambda lambda_ingestao_bovespa_raw

Ambiente & Variáveis de Ambiente
Variável	Função	Exemplo
S3_BUCKET	Bucket onde gravar raw/ e refined/	tech-challenge-bovespa
SEGMENT	Segmento IBOV (API)	2
PAGE_SIZE	Itens por página (API)	1000
HTTP_TIMEOUT	Timeout das requisições (s)	15
FILENAME	Nome do arquivo Parquet	ibov_setor.parquet
GLUE_JOB_NAME	Nome do Glue Job de refinamento	glue_job_refinamento_bovespa

Monitoramento & Logs
CloudWatch Logs: verifique logs de cada Lambda e do Glue Job.

CloudWatch Alarms: crie alarmes em métricas de erro das Lambdas e de runs com falha no Glue.

Próximos Passos
Implementar CI/CD (AWS CDK ou CloudFormation).

Adicionar Data Quality (AWS Deequ ou DataBrew).

Construir dashboards com QuickSight ou Grafana.

