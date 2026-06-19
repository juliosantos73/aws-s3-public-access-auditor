# aws-s3-public-access-auditor

🌐 [English](README.md) | [Português](README.pt-BR.md)

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Python 3.12](https://img.shields.io/badge/Python-3.12-blue?logo=python)
![AWS Lambda](https://img.shields.io/badge/AWS-Lambda-orange?logo=amazon-aws)

Uma função AWS Lambda que **audita todos os buckets S3** em busca de configurações de acesso público incorretas e envia alertas via **SNS (e-mail)** e/ou **Slack**. Executa diariamente via EventBridge.

---

## Como funciona

```
EventBridge (cron diário) ──► Lambda ──► list_buckets (todos os buckets)
                                     │       ├── verifica configuração PublicAccessBlock
                                     │       └── verifica status da bucket policy
                                     │
                                     └── (se bucket público encontrado)
                                         ├──► SNS Topic ──► E-mail
                                         └──► Slack Webhook
```

Para cada bucket, a função realiza duas verificações independentes:

| Verificação | O que valida |
|---|---|
| **PublicAccessBlock** | As quatro configurações de bloqueio devem estar habilitadas (`BlockPublicAcls`, `IgnorePublicAcls`, `BlockPublicPolicy`, `RestrictPublicBuckets`) |
| **Status da Bucket Policy** | A política do bucket não deve conceder acesso público |

---

## Funcionalidades

- Audita **todos os buckets S3** da conta (S3 é um serviço global — sem loop de regiões)
- Duas verificações independentes por bucket
- Alertas via **SNS (e-mail)** e/ou **Slack webhook**
- Logs JSON estruturados — compatíveis com CloudWatch Insights
- Modo dry run — lista os problemas sem enviar notificações
- Retry adaptativo via botocore

---

## Pré-requisitos

- Uma conta AWS
- Python 3.12+ (somente para desenvolvimento local)
- AWS CLI configurado (opcional)

---

## 1. Criar o tópico SNS (opcional)

```bash
TOPIC_ARN=$(aws sns create-topic --name s3-audit-alert --query TopicArn --output text)
aws sns subscribe --topic-arn "$TOPIC_ARN" --protocol email --notification-endpoint seu@email.com
echo "Topic ARN: $TOPIC_ARN"
```

---

## 2. Criar o IAM execution role

**Policy document** — salve como `s3-auditor-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:ListAllMyBuckets",
        "s3:GetBucketPublicAccessBlock",
        "s3:GetBucketPolicyStatus"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": ["sns:Publish"],
      "Resource": "<arn-do-seu-topico-sns>"
    },
    {
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "arn:aws:logs:*:*:*"
    }
  ]
}
```

```bash
aws iam create-role --role-name s3-auditor-role \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

aws iam put-role-policy --role-name s3-auditor-role \
  --policy-name s3-auditor-policy --policy-document file://s3-auditor-policy.json
```

---

## 3. Deploy da função Lambda

```bash
zip lambda_function.zip lambda_function.py
ROLE_ARN=$(aws iam get-role --role-name s3-auditor-role --query Role.Arn --output text)

aws lambda create-function \
  --function-name s3-public-access-auditor \
  --runtime python3.12 --role "$ROLE_ARN" \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://lambda_function.zip --timeout 60
```

---

## 4. Configurar a regra do EventBridge

```bash
LAMBDA_ARN=$(aws lambda get-function --function-name s3-public-access-auditor --query Configuration.FunctionArn --output text)

aws events put-rule --name S3PublicAccessAudit \
  --schedule-expression "cron(0 8 * * ? *)" --state ENABLED

aws events put-targets --rule S3PublicAccessAudit --targets "Id=1,Arn=$LAMBDA_ARN"

aws lambda add-permission --function-name s3-public-access-auditor \
  --statement-id AllowEventBridge --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn $(aws events describe-rule --name S3PublicAccessAudit --query RuleArn --output text)
```

---

## Configuração

| Variável            | Padrão   | Descrição                                                    |
|---------------------|----------|--------------------------------------------------------------|
| `SNS_TOPIC_ARN`     | _(vazio)_| ARN do tópico SNS para notificações por e-mail               |
| `SLACK_WEBHOOK_URL` | _(vazio)_| URL do webhook do Slack                                      |
| `DRY_RUN`           | `false`  | Defina como `true` para listar problemas sem enviar alertas  |

---

## Testes

```bash
aws lambda invoke \
  --function-name s3-public-access-auditor \
  --payload '{"dry_run":true}' \
  --cli-binary-format raw-in-base64-out \
  response.json && cat response.json
```

---

## Exemplo de resposta

```json
{
  "result": "alert",
  "dry_run": false,
  "public_buckets": [
    {
      "bucket": "my-old-assets-bucket",
      "reasons": ["PublicAccessBlock not fully enabled", "bucket policy grants public access"]
    }
  ]
}
```

---

## Desenvolvimento local

```bash
pip install -r requirements-dev.txt
python -c "from lambda_function import lambda_handler; print(lambda_handler({'dry_run': True}, None))"
```

---

## Contribuindo

1. Faça um fork do repositório
2. Crie uma branch: `git checkout -b feature/sua-feature`
3. Faça commit, push e abra um Pull Request

---

## Licença

[MIT](LICENSE) — © Júlio César Santos
