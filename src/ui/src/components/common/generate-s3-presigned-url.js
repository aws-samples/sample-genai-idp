// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { HttpRequest } from '@aws-sdk/protocol-http';
import { S3RequestPresigner } from '@aws-sdk/s3-request-presigner';
import { parseUrl } from '@aws-sdk/url-parser';
import { Sha256 } from '@aws-crypto/sha256-browser';
import { formatUrl } from '@aws-sdk/util-format-url';
import { Logger } from 'aws-amplify';

const logger = new Logger('generate-s3-presigned-url');

const generateS3PresignedUrl = async (url, credentials) => {
  // If it's already a special URL (like detailType), return as is
  if (url.includes('detailType')) {
    return url;
  }

  try {
    logger.debug('Generating presigned URL for:', url);
    // Parse the URL into components
    const urlObj = new URL(url);

    // Extract bucket name from hostname
    const bucketName = urlObj.hostname.split('.')[0];

    // Extract region from env
    const region = process.env.REACT_APP_AWS_REGION;

    // Remove leading slash and get the full key path
    const key = urlObj.pathname.substring(1);

    // Construct the canonical S3 URL
    const newUrl = `https://${bucketName}.s3.${region}.amazonaws.com/${key}`;

    // Parse the URL for the presigner
    const s3ObjectUrl = parseUrl(newUrl);
    logger.debug('Canonical URL:', newUrl);

    // Create presigner instance
    const presigner = new S3RequestPresigner({
      credentials,
      region,
      sha256: Sha256,
    });

    // Generate presigned URL
    const presignedResponse = await presigner.presign(new HttpRequest(s3ObjectUrl));
    const presignedUrl = formatUrl(presignedResponse);

    return presignedUrl;
  } catch (error) {
    throw new Error(`Failed to generate presigned URL: ${error.message}`);
  }
};

export default generateS3PresignedUrl;
