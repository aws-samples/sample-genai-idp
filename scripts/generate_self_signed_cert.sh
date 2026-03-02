#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# Generates a self-signed TLS certificate and imports it to AWS Certificate Manager (ACM).
# Use this for demo/testing with the ALB hosting option.
#
# Usage:
#   ./scripts/generate_self_signed_cert.sh [--region REGION] [--domain DOMAIN] [--days DAYS]
#
# Options:
#   --region  AWS region for ACM import (default: from AWS_DEFAULT_REGION or aws configure)
#   --domain  Domain name for the certificate CN/SAN (default: self-signed.internal)
#   --days    Certificate validity in days (default: 365)
#
# Output:
#   Prints the ACM certificate ARN to stdout (last line).
#
# Example:
#   CERT_ARN=$(./scripts/generate_self_signed_cert.sh --region us-gov-west-1 --domain myapp.internal)
#   echo "Use this ARN for ALBCertificateArn parameter: $CERT_ARN"

set -euo pipefail

REGION=""
DOMAIN="self-signed.internal"
DAYS=365

while [[ $# -gt 0 ]]; do
    case "$1" in
        --region)
            REGION="$2"
            shift 2
            ;;
        --domain)
            DOMAIN="$2"
            shift 2
            ;;
        --days)
            DAYS="$2"
            shift 2
            ;;
        -h|--help)
            head -20 "$0" | grep '^#' | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

# Validate dependencies
for cmd in openssl aws; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "Error: $cmd is required but not installed." >&2
        exit 1
    fi
done

# Build region flag
REGION_FLAG=""
if [[ -n "$REGION" ]]; then
    REGION_FLAG="--region $REGION"
fi

# Create temporary directory for certificate files
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

KEY_FILE="$TMPDIR/private.key"
CERT_FILE="$TMPDIR/certificate.pem"

echo "Generating self-signed certificate for domain: $DOMAIN (valid for $DAYS days)" >&2

# Generate private key and self-signed certificate
openssl req -x509 -nodes \
    -days "$DAYS" \
    -newkey rsa:2048 \
    -keyout "$KEY_FILE" \
    -out "$CERT_FILE" \
    -subj "/CN=$DOMAIN" \
    -addext "subjectAltName=DNS:$DOMAIN" \
    2>/dev/null

echo "Importing certificate to ACM..." >&2

# Import certificate to ACM
# shellcheck disable=SC2086
CERT_ARN=$(aws acm import-certificate \
    --certificate fileb://"$CERT_FILE" \
    --private-key fileb://"$KEY_FILE" \
    --query 'CertificateArn' \
    --output text \
    $REGION_FLAG)

echo "" >&2
echo "Certificate imported successfully." >&2
echo "ACM Certificate ARN: $CERT_ARN" >&2
echo "" >&2
echo "Use this value for the ALBCertificateArn CloudFormation parameter." >&2
echo "" >&2
echo "NOTE: This is a self-signed certificate. Browsers will show a security warning." >&2
echo "For production use, use a certificate issued by a trusted CA or AWS ACM." >&2

# Print just the ARN to stdout for scripting
echo "$CERT_ARN"
