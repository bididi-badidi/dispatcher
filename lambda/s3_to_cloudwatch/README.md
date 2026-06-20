# s3_to_cloudwatch

S3-triggered AWS Lambda that loads uploaded dispatcher log files into CloudWatch Logs.

When an object is created in the log bucket (e.g. `owner/repo/issue_42-build.log`,
optionally gzipped), the function reads it and writes readable multi-line
CloudWatch log events prefixed with the log's label (`[issue_42-build]`). Large
files are split into chunks that fit CloudWatch Logs event limits.

## Files

| File | Purpose |
|------|---------|
| `handler.py` | Lambda entry point (`handler.lambda_handler`) |
| `template.yaml` | AWS SAM template: function + S3 trigger + IAM + log group |
| `requirements.txt` | Dependency notes (boto3 ships in the runtime) |
| `test_handler.py` | Unit tests (fake S3 / CloudWatch clients, no AWS calls) |

## Environment variables

| Name | Required | Description |
|------|----------|-------------|
| `LOG_GROUP_NAME` | yes | Target CloudWatch log group. Created if missing. |
| `LOG_STREAM_NAME` | no | Pin all uploads to one stream. If unset, the stream name is derived from the S3 key as `owner/repo`, ignoring any leading key prefix. |

## IAM permissions the function needs

- `s3:GetObject` on the log bucket
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` on the target log group

The SAM template grants exactly these.

## Deploy with SAM

```bash
cd lambda/s3_to_cloudwatch
sam build
sam deploy --guided \
  --parameter-overrides \
    LogBucketName=my-dispatcher-logs \
    LogKeyPrefix= \
    TargetLogGroup=/dispatcher/s3-logs
```

> The template defines the bucket so SAM can attach the `s3:ObjectCreated:*`
> notification. If the bucket **already exists**, delete the `LogBucket` resource
> from `template.yaml` and add the notification to the existing bucket manually
> (SAM's S3 event source can only wire a bucket declared in the same stack).

## Wire the trigger manually (no SAM)

1. Create the function (Python 3.11), set `LOG_GROUP_NAME`, attach the IAM policy above.
2. Zip and upload: `zip function.zip handler.py && aws lambda update-function-code --function-name <name> --zip-file fileb://function.zip`
3. In the S3 bucket → **Properties → Event notifications**, add an
   `s3:ObjectCreated:*` notification targeting the function (optionally with a
   key prefix/suffix filter).

## Test

```bash
pytest lambda/s3_to_cloudwatch/test_handler.py
```
