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
