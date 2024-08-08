# Azure-to-AWS-Large-File-Transfer-High-Performance-Blob-to-S3-Migration-Tool

## Overview

This project provides a high-performance, serverless solution for transferring large files from Azure Blob Storage to AWS S3 using Azure Functions. It addresses the challenges of transferring very large files between cloud providers efficiently and reliably.

## Key Features

- Parallel downloading from Azure Blob Storage
- Parallel uploading to AWS S3 using multipart upload
- Efficient handling of files up to 150GB and beyond
- MD5 hash validation for data integrity
- Detailed progress logging
- Robust error handling with retry logic
- Resource-efficient operation suitable for serverless environments

## Challenges Addressed

1. **Time Constraints**: Overcomes function timeout limits through parallel processing.
2. **Network Instability**: Implements retry logic for resilience against transient network issues.
3. **Resource Limitations**: Efficiently manages memory and CPU usage through chunked processing.
4. **Data Integrity**: Ensures file integrity with MD5 hash validation.
5. **Progress Tracking**: Provides detailed progress logs for both download and upload phases.

## Prerequisites

- Azure Subscription
- AWS Account
- Python 3.8 or later

## Required 

#### Azure Resources
1. Azure Storage Account
2. Azure Function App with App Service Plan (Recommended with at least `Premium v3 P1V3`)
3. Azure Blob Container

#### AWS Resources
1. S3 Bucket

## Setup Instructions

1. Clone this repository:
   ```
   git clone https://github.com/Orcohen33/Azure-to-AWS-Large-File-Transfer-High-Performance-Blob-to-S3-Migration-Tool.git
   ```

2. Navigate to the project directory:
   ```
   cd Azure-to-AWS-Large-File-Transfer-High-Performance-Blob-to-S3-Migration-Tool
   ```

3. Set up your Azure Function App and configure the following environment variables:
   - `AzureWebJobsStorage`: Connection string for your Azure Storage account
   - `BLOB_CONTAINER_NAME`: Name of your source Azure Blob container
   - `AWS_ACCESS_KEY_ID`: Your AWS access key ID
   - `AWS_SECRET_ACCESS_KEY`: Your AWS secret access key
   - `S3_BUCKET_NAME`: Name of your destination S3 bucket

4. Deploy the Azure Function to your Function App.

## Usage

To trigger a file transfer, send an HTTP POST request to your Azure Function with the following query parameter:

- `blobName`: The name of the blob in your Azure container that you want to transfer

Example:
```
POST https://your-function-app.azurewebsites.net/api/TransferLargeFile?code=<YOUR_FUNCTION_CODE>&blobName=your-large-file.zip
```

## Permissions

### Azure Permissions

The Azure Function's managed identity or the account specified in the connection string should have:
- `Storage Blob Data Reader` permission on the source blob container
- `Storage Blob Data Deleter` permission (if you want to delete the source blob after transfer)

### AWS Permissions

The AWS IAM user associated with the access key should have the following permissions on the destination S3 bucket:
- `s3:PutObject`
- `s3:AbortMultipartUpload`
- `s3:ListMultipartUploadParts`
- `s3:ListBucketMultipartUploads`

## Configuration

You can adjust the following constants in the `function_app.py` file to fine-tune the transfer process:

- `MAX_WORKERS`: Maximum number of concurrent download/upload operations
- `CHUNK_SIZE`: Size of each chunk for download and upload (in bytes)
- `MAX_RETRIES`: Maximum number of retry attempts for failed operations

You can delete the blob after the transfer success here:
```
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
```

Uncomment the following:
```
            # Delete blob from Azure Storage
            # blob_client = blob_service_client.get_blob_client(
            #     container=source_container_name, blob=blob_name
            # )
            # blob_client.delete_blob()
            # log_message(logging.INFO, f"Blob {blob_name} deleted from Azure Storage")
```

## Monitoring and Logging

The function provides detailed logging throughout the transfer process. You can monitor these logs in the Azure Portal or by setting up Application Insights.

Key log messages include:
- Download and upload progress (as percentages)
- MD5 hash of the downloaded file
- Successful completion or any errors encountered

## Security Considerations

- Ensure your Azure Function App is properly secured with appropriate authentication methods.
- Store sensitive information (connection strings, access keys) in Azure Key Vault for enhanced security.
- Regularly rotate your AWS access keys.
- Apply the principle of least privilege when assigning permissions to both Azure and AWS resources.

## Limitations

- The function is designed to handle files up to 150GB, but actual limits may vary based on your Azure Function configuration and available resources.
- Transfer time is dependent on network conditions between Azure, your Function App, and AWS.

## Contributing

Contributions to improve the project are welcome. Please follow the standard fork-and-pull request workflow.

## License

[MIT License](LICENSE)

## Support

For issues, questions, or contributions, please open an issue in the GitHub repository.
