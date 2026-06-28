import { S3Client } from "@aws-sdk/client-s3";
import { SQSClient } from "@aws-sdk/client-sqs";

function buildClientConfig() {
  // This function returns shared AWS client config from env values.
  return {
    region: process.env.AWS_REGION,
    credentials: {
      accessKeyId: process.env.AWS_ACCESS_KEY_ID || "",
      secretAccessKey: process.env.AWS_SECRET_ACCESS_KEY || ""
    }
  };
}

export const s3Client = new S3Client(buildClientConfig());
export const sqsClient = new SQSClient(buildClientConfig());
