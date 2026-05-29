import boto3
from botocore.exceptions import ClientError
import os
import uuid
from dotenv import load_dotenv

load_dotenv()

AWS_REGION      = os.getenv("AWS_REGION", "eu-central-1")
S3_BUCKET       = os.getenv("S3_BUCKET", "agrovision-uploads")

# boto3 бере AWS_ACCESS_KEY_ID та AWS_SECRET_ACCESS_KEY з оточення автоматично
# На EC2 можна взагалі не вказувати ключі — використовується IAM Role
s3 = boto3.client("s3", region_name=AWS_REGION)


def upload_image(local_path: str, original_filename: str) -> str:
    """
    Завантажує файл у S3.
    Повертає унікальний S3-ключ (не URL), наприклад: 'uploads/uuid_name.jpg'
    """
    ext = os.path.splitext(original_filename)[-1]
    key = f"uploads/{uuid.uuid4()}{ext}"
    s3.upload_file(
        local_path, S3_BUCKET, key,
        ExtraArgs={"ContentType": _content_type(ext)}
    )
    return key


def get_presigned_url(key: str, expires: int = 3600) -> str:
    """
    Генерує тимчасове посилання для перегляду (1 год за замовчуванням).
    """
    try:
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET, "Key": key},
            ExpiresIn=expires,
        )
        return url
    except ClientError:
        return ""


def delete_image(key: str) -> None:
    """Видаляє об'єкт з S3 (використовується при видаленні аналізу)."""
    try:
        s3.delete_object(Bucket=S3_BUCKET, Key=key)
    except ClientError:
        pass


def _content_type(ext: str) -> str:
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".tiff": "image/tiff",
        ".tif": "image/tiff", ".webp": "image/webp",
    }.get(ext.lower(), "application/octet-stream")