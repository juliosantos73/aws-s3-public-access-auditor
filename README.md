# aws-s3-public-access-auditor

🌐 [English](README.md) | [Português](README.pt-BR.md)

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Python 3.12](https://img.shields.io/badge/Python-3.12-blue?logo=python)
![AWS Lambda](https://img.shields.io/badge/AWS-Lambda-orange?logo=amazon-aws)

An AWS Lambda function that **audits all S3 buckets** for public access misconfigurations and sends alerts via **SNS (email)** and/or **Slack**. Runs daily via EventBridge.

---

## How it works

```
EventBridge (daily cron) ──► Lambda ──► list_buckets (all buckets)
                                    │       ├── check PublicAccessBlock settings
                                    │       └── check bucket policy status
                                    │
                                    └── (if public bucket found)
                                        ├──► SNS Topic ──► Email
                                        └──► Slack Webhook
```

For each bucket, the function performs two independent checks:

| Check | What it verifies |
|---|---|
| **PublicAccessBlock** | All four block settings must be enabled (`BlockPublicAcls`, `IgnorePublicAcls`, `BlockPublicPolicy`, `RestrictPublicBuckets`) |
| **Bucket Policy Status** | The bucket policy must not grant public access |

---

## Features

- Audits **all S3 buckets** in the account (S3 is a global service — no region loop needed)
- Two independent checks per bucket: PublicAccessBlock and policy status
- Alerts via **SNS (email)** and/or **Slack webhook**
- Structured JSON logs — compatible with CloudWatch Insights queries
- Dry run mode — lists findings without sending notifications
- Adaptive retry — handles AWS API throttling automatically

---

## Prerequisites

- An AWS account
- Python 3.12+ (for local development only)
- AWS CLI configured (optional, for CLI-based deployment)
- An SNS topic and/or Slack webhook for notifications

---

## 1. Create the SNS topic (optional)

```bash
TOPIC_ARN=$(aws sns create-topic --name s3-audit-alert --query TopicArn --output text)
aws sns subscribe --topic-arn "$TOPIC_ARN" --protocol email --notification-endpoint your@email.com
echo "Topic ARN: $TOPIC_ARN"
```

---

## 2. Create the IAM execution role

**Policy document** — save as `s3-auditor-policy.json`:

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
      "Resource": "<your-sns-topic-arn>"
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

## 3. Deploy the Lambda function

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

## 4. Configure the EventBridge rule

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

## Configuration

| Variable            | Default  | Description                                              |
|---------------------|----------|----------------------------------------------------------|
| `SNS_TOPIC_ARN`     | _(none)_ | SNS topic ARN for email notifications                    |
| `SLACK_WEBHOOK_URL` | _(none)_ | Slack incoming webhook URL                               |
| `DRY_RUN`           | `false`  | Set to `true` to log findings without sending alerts     |

---

## Testing

```bash
# Dry run via AWS CLI
aws lambda invoke \
  --function-name s3-public-access-auditor \
  --payload '{"dry_run":true}' \
  --cli-binary-format raw-in-base64-out \
  response.json && cat response.json
```

---

## Example response

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

## Monitoring

```
fields @timestamp, public_bucket.bucket, public_bucket.reasons
| filter ispresent(public_bucket)
| sort @timestamp desc
```

---

## Local development

```bash
pip install -r requirements-dev.txt
python -c "from lambda_function import lambda_handler; print(lambda_handler({'dry_run': True}, None))"
```

---

## Contributing

1. Fork the repository
2. Create a branch: `git checkout -b feature/your-feature`
3. Commit and push, then open a Pull Request

---

## License

[MIT](LICENSE) — © Júlio César Santos
