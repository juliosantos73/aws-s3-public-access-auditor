import json
import logging
import os
import traceback
import urllib.request
from datetime import datetime

import boto3
from botocore.config import Config

SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN', '')
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL', '')
DRY_RUN = os.environ.get('DRY_RUN', 'false').lower() == 'true'

logger = logging.getLogger()
logger.setLevel(logging.INFO)
BOTO_CONFIG = Config(retries={'max_attempts': 3, 'mode': 'adaptive'})


def check_bucket(s3_client, bucket_name: str) -> dict | None:
    reasons = []

    try:
        pab = s3_client.get_bucket_public_access_block(Bucket=bucket_name)
        config = pab['PublicAccessBlockConfiguration']
        if not all([
            config.get('BlockPublicAcls', False),
            config.get('IgnorePublicAcls', False),
            config.get('BlockPublicPolicy', False),
            config.get('RestrictPublicBuckets', False),
        ]):
            reasons.append('PublicAccessBlock not fully enabled')
    except s3_client.exceptions.NoSuchPublicAccessBlockConfiguration:
        reasons.append('PublicAccessBlock not configured')
    except Exception:
        logger.error(json.dumps({'bucket': bucket_name, 'check': 'public_access_block', 'error': traceback.format_exc()}))

    try:
        status = s3_client.get_bucket_policy_status(Bucket=bucket_name)
        if status['PolicyStatus'].get('IsPublic', False):
            reasons.append('bucket policy grants public access')
    except s3_client.exceptions.NoSuchBucketPolicy:
        pass
    except Exception:
        logger.error(json.dumps({'bucket': bucket_name, 'check': 'policy_status', 'error': traceback.format_exc()}))

    return {'bucket': bucket_name, 'reasons': reasons} if reasons else None


def build_message(public_buckets: list[dict]) -> str:
    lines = [
        f"S3 Public Access Alert",
        f"",
        f"{len(public_buckets)} bucket(s) with public access detected:",
        "",
    ]
    for b in public_buckets:
        lines.append(f"  - {b['bucket']}: {', '.join(b['reasons'])}")
    return '\n'.join(lines)


def send_sns(subject: str, message: str) -> None:
    if not SNS_TOPIC_ARN:
        logger.warning(json.dumps({'warning': 'SNS_TOPIC_ARN not configured, skipping'}))
        return
    sns = boto3.client('sns', config=BOTO_CONFIG)
    sns.publish(TopicArn=SNS_TOPIC_ARN, Subject=subject, Message=message)
    logger.info(json.dumps({'notification': 'sns', 'topic': SNS_TOPIC_ARN}))


def send_slack(public_buckets: list[dict]) -> None:
    if not SLACK_WEBHOOK_URL:
        return
    fields = [{'title': b['bucket'], 'value': ', '.join(b['reasons']), 'short': False} for b in public_buckets]
    payload = {
        'attachments': [{
            'color': '#FF0000',
            'title': f"S3 Public Access Alert — {len(public_buckets)} bucket(s)",
            'fields': fields,
            'footer': 'AWS S3 Auditor',
        }]
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(SLACK_WEBHOOK_URL, data=data, headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=10) as resp:
        logger.info(json.dumps({'notification': 'slack', 'status': resp.status}))


def lambda_handler(event: dict, context) -> dict:
    dry_run = bool(event.get('dry_run', DRY_RUN))
    logger.info(json.dumps({'dry_run': dry_run}))

    s3 = boto3.client('s3', config=BOTO_CONFIG)
    buckets = s3.list_buckets().get('Buckets', [])
    logger.info(json.dumps({'total_buckets': len(buckets)}))

    public_buckets = []
    for bucket in buckets:
        result = check_bucket(s3, bucket['Name'])
        if result:
            public_buckets.append(result)
            logger.info(json.dumps({'public_bucket': result}))

    if not public_buckets:
        logger.info(json.dumps({'result': 'no_public_buckets'}))
        return {'statusCode': 200, 'body': json.dumps({'result': 'no_public_buckets'})}

    logger.info(json.dumps({'result': 'alert', 'count': len(public_buckets)}))

    if not dry_run:
        message = build_message(public_buckets)
        subject = f"S3 Public Access Alert — {len(public_buckets)} bucket(s) found"
        try:
            send_sns(subject, message)
        except Exception:
            logger.error(json.dumps({'notification': 'sns', 'error': traceback.format_exc()}))
        try:
            send_slack(public_buckets)
        except Exception:
            logger.error(json.dumps({'notification': 'slack', 'error': traceback.format_exc()}))

    return {
        'statusCode': 200,
        'body': json.dumps({'result': 'alert', 'dry_run': dry_run, 'public_buckets': public_buckets}),
    }
