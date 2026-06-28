import { GetObjectCommand, PutObjectCommand, DeleteObjectCommand, CopyObjectCommand, HeadObjectCommand } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";
import { Injectable } from "@nestjs/common";
import { s3Client } from "../../config/aws.config";

@Injectable()
export class S3Service {
  private readonly bucketName = process.env.S3_BUCKET_NAME || "";

  async uploadFile(key: string, buffer: Buffer, contentType = "application/pdf"): Promise<void> {
    // This function uploads a file buffer to S3 at the provided key.
    await s3Client.send(
      new PutObjectCommand({
        Bucket: this.bucketName,
        Key: key,
        Body: buffer,
        ContentType: contentType
      })
    );
  }

  async moveObject(fromKey: string, toKey: string): Promise<void> {
    // This function copies then deletes a file to move it in S3.
    await s3Client.send(
      new CopyObjectCommand({
        Bucket: this.bucketName,
        CopySource: `${this.bucketName}/${fromKey}`,
        Key: toKey
      })
    );
    await this.deleteObject(fromKey);
  }

  async deleteObject(key: string): Promise<void> {
    // This function deletes a file from S3.
    await s3Client.send(new DeleteObjectCommand({ Bucket: this.bucketName, Key: key }));
  }

  async objectExists(key: string): Promise<boolean> {
    // This function checks if a file exists in S3 without downloading it.
    try {
      await s3Client.send(new HeadObjectCommand({ Bucket: this.bucketName, Key: key }));
      return true;
    } catch {
      return false;
    }
  }

  async getSignedUrl(key: string, expiresIn = 300): Promise<string> {
    // This function creates a temporary signed URL for secure PDF viewing.
    return getSignedUrl(
      s3Client,
      new GetObjectCommand({
        Bucket: this.bucketName,
        Key: key
      }),
      { expiresIn }
    );
  }
}
