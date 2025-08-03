# 🚀 Pipeline Batch Bovespa

> Ingestão, ETL e consumo de dados do IBOV na AWS

---

[![Lambda](https://img.shields.io/badge/🐍-Lambda-blue)](#lambda-de-ingestão-raw)  
[![S3](https://img.shields.io/badge/📦-S3-lightgrey)](#s3-buckets)  
[![Glue](https://img.shields.io/badge/🔵-Glue-orange)](#glue-studio–etl-visual)  
[![Athena](https://img.shields.io/badge/📗-Athena-green)](#athena--visualizações)  

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

![Arquitetura AWS](./docs/architecture.png)

1. 🌐 **API B3**  
2. 🟡 **Lambda_Ingestão** → S3 **raw/**  
3. 🟡 **Lambda_Trigger_Glue** → **Glue Studio**  
4. 🔵 **Glue ETL** → S3 **refined/** + **Glue Catalog**  
5. 📗 **Athena** (Query & Notebook)

---

## Componentes

| Componente                 | Função                                  |
|----------------------------|-----------------------------------------|
| `Lambda_Ingestão`          | Scraping + upload Parquet raw           |
| S3 **raw/**                | Armazenar dados brutos                  |
| S3 Event Notification      | Dispara Lambda de trigger               |
| `Lambda_Trigger_Glue`      | Inicia Glue Job                         |
| Glue Studio (ETL Visual)   | Transformações A, B e C + output refinado |
| S3 **refined/**            | Dados refinados particionados           |
| Glue Data Catalog          | Tabela `default.tb_ibov_refined`        |
| Athena                     | Consulta SQL, views e notebook          |

---

## Configuração

### S3 Buckets

```text
tech-challenge-bovespa/
├── raw/       # Parquet raw particionado
└── refined/   # Parquet refinado particionado
