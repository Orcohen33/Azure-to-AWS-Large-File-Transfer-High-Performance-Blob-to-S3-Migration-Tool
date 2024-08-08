import azure.functions as func
import logging
import os
import boto3
import hashlib
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import AzureError
from botocore.exceptions import ClientError
from botocore.config import Config
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

# Constants
MAX_RETRIES = 5
MAX_WORKERS = 15
CHUNK_SIZE = 10 * 1024 * 1024  # 10MB chunks


def get_blob_service_client():
    connection_string = os.environ["AzureWebJobsStorage"]
    return BlobServiceClient.from_connection_string(connection_string)


def log_message(level, message):
    logging.log(level, f"[LargeFileTransfer] {message}")


def calculate_md5(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def download_blob_chunk(blob_client, start_range, end_range, file_path, lock):
    download_stream = blob_client.download_blob(
        offset=start_range, length=end_range - start_range + 1
    )
    chunk_data = download_stream.readall()
    with lock:
        with open(file_path, "r+b") as file:
            file.seek(start_range)
            file.write(chunk_data)


def parallel_blob_download(
    blob_service_client, container_name, blob_name, file_path, max_workers=MAX_WORKERS
):
    blob_client = blob_service_client.get_blob_client(
        container=container_name, blob=blob_name
    )
    properties = blob_client.get_blob_properties()
    blob_size = properties.size

    # Create an empty file of the required size
    with open(file_path, "wb") as f:
        f.seek(blob_size - 1)
        f.write(b"\0")

    lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                download_blob_chunk,
                blob_client,
                start_range,
                min(start_range + CHUNK_SIZE - 1, blob_size - 1),
                file_path,
                lock,
            )
            for start_range in range(0, blob_size, CHUNK_SIZE)
        ]
        for i, future in enumerate(as_completed(futures)):
            future.result()
            progress = min((i + 1) / len(futures) * 100, 100)
            log_message(logging.INFO, f"Download progress: {progress:.2f}%")


def upload_part(s3_client, bucket, key, upload_id, part_number, body):
    try:
        response = s3_client.upload_part(
            Bucket=bucket,
            Key=key,
            UploadId=upload_id,
            PartNumber=part_number,
            Body=body,
        )
        return {"PartNumber": part_number, "ETag": response["ETag"]}
    except ClientError as e:
        log_message(logging.ERROR, f"Error uploading part {part_number}: {str(e)}")
        raise


def parallel_s3_upload(
    s3_client, file_path, bucket, object_name, max_workers=MAX_WORKERS
):
    file_size = os.path.getsize(file_path)

    try:
        mpu = s3_client.create_multipart_upload(Bucket=bucket, Key=object_name)
        upload_id = mpu["UploadId"]

        parts = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            with open(file_path, "rb") as file:
                part_number = 1
                while True:
                    data = file.read(CHUNK_SIZE)
                    if not data:
                        break
                    future = executor.submit(
                        upload_part,
                        s3_client,
                        bucket,
                        object_name,
                        upload_id,
                        part_number,
                        data,
                    )
                    futures.append(future)
                    part_number += 1

            for i, future in enumerate(as_completed(futures)):
                parts.append(future.result())
                progress = min((i + 1) / len(futures) * 100, 100)
                log_message(logging.INFO, f"S3 Upload progress: {progress:.2f}%")

        s3_client.complete_multipart_upload(
            Bucket=bucket,
            Key=object_name,
            UploadId=upload_id,
            MultipartUpload={"Parts": sorted(parts, key=lambda x: x["PartNumber"])},
        )
        return True
    except Exception as e:
        log_message(logging.ERROR, f"Error in parallel S3 upload: {str(e)}")
        if "upload_id" in locals():
            s3_client.abort_multipart_upload(
                Bucket=bucket, Key=object_name, UploadId=upload_id
            )
        return False


@app.route(route="TransferLargeFile")
def TransferLargeFile(req: func.HttpRequest) -> func.HttpResponse:
    log_message(logging.INFO, "Large file transfer function triggered")

    # Configuration
    aws_access_key_id = os.environ["AWS_ACCESS_KEY_ID"]
    aws_secret_access_key = os.environ["AWS_SECRET_ACCESS_KEY"]
    s3_bucket_name = os.environ["S3_BUCKET_NAME"]
    source_container_name = os.environ["BLOB_CONTAINER_NAME"]
    blob_name = req.params.get("blobName")

    if not blob_name:
        return func.HttpResponse("Please provide a blobName parameter", status_code=400)

    try:
        blob_service_client = get_blob_service_client()

        # Create a temporary file to store the blob
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file_path = temp_file.name

        # Download blob to temporary file using parallel download
        log_message(
            logging.INFO,
            f"Starting parallel download of blob {blob_name} to temporary file",
        )
        parallel_blob_download(
            blob_service_client, source_container_name, blob_name, temp_file_path
        )
        log_message(logging.INFO, f"Download of blob {blob_name} completed")

        # Calculate MD5 hash of the downloaded file
        md5_hash = calculate_md5(temp_file_path)
        log_message(logging.INFO, f"MD5 hash of downloaded file: {md5_hash}")

        # Create AWS S3 client with retry configuration
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            config=Config(
                retries={"max_attempts": MAX_RETRIES, "mode": "adaptive"},
                connect_timeout=300,
                read_timeout=300,
            ),
        )

        # Upload file to S3 using parallel upload
        log_message(
            logging.INFO, f"Starting parallel upload to S3 for file {blob_name}"
        )
        if parallel_s3_upload(s3_client, temp_file_path, s3_bucket_name, blob_name):
            log_message(logging.INFO, f"File {blob_name} uploaded to S3 successfully")
        else:
            raise Exception("Failed to upload file to S3")

        # Validate the upload
        s3_object = s3_client.head_object(Bucket=s3_bucket_name, Key=blob_name)
        if s3_object["ContentLength"] == os.path.getsize(temp_file_path):
            log_message(logging.INFO, f"File size validated successfully in S3")

            # Delete blob from Azure Storage
            # blob_client = blob_service_client.get_blob_client(
            #     container=source_container_name, blob=blob_name
            # )
            # blob_client.delete_blob()
            # log_message(logging.INFO, f"Blob {blob_name} deleted from Azure Storage")

            return func.HttpResponse(
                f"File {blob_name} transferred successfully", status_code=200
            )
        else:
            raise ValueError("File size mismatch between source and destination")

    except Exception as e:
        log_message(logging.ERROR, f"Error during file transfer: {str(e)}")
        return func.HttpResponse(
            f"Error during file transfer: {str(e)}", status_code=500
        )
    finally:
        # Clean up the temporary file
        if "temp_file_path" in locals():
            os.unlink(temp_file_path)
            log_message(logging.INFO, "Temporary file deleted")
