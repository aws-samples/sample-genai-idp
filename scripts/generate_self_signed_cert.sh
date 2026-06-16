#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# Generates a self-signed TLS certificate and imports it to AWS Certificate Manager (ACM).
# Use this for demo/testing with the ALB hosting option.
#
# Usage:
#   ./scripts/generate_self_signed_cert.sh [--region REGION] [--domain DOMAIN] [--days DAYS] [--cert-arn ARN]
#
# Options:
#   --region    AWS region for ACM import (default: from AWS_DEFAULT_REGION or aws configure)
#   --domain    Domain name for the certificate CN/SAN (default: self-signed.internal)
#   --days      Certificate validity in days (default: 365)
#   --cert-arn  Existing ACM certificate ARN to reimport (updates in-place, no stack change needed)
#
# Output:
#   Prints the ACM certificate ARN to stdout (last line).
#
# --- 2-step process for ALB testing (self-signed cert) ---
#
# Step 1 — Before deploying the IDP stack, create a placeholder cert:
#   CERT_ARN=$(./scripts/generate_self_signed_cert.sh --region us-east-1 --domain idp-alb.internal)
#   # Use $CERT_ARN as the ALBCertificateArn parameter when deploying the stack
#
# Step 2 — After the IDP stack is deployed, reimport with the actual ALB hostname as SAN:
#   ALB_DNS=$(aws cloudformation describe-stacks --stack-name IDP-PRIVATE \
#     --query 'Stacks[0].Outputs[?OutputKey==`ApplicationWebURL`].OutputValue' \
#     --output text | sed 's|https://||')
#   ./scripts/generate_self_signed_cert.sh --region us-east-1 --domain "$ALB_DNS" --cert-arn "$CERT_ARN"
#   # The ALB will serve the new cert within ~30 seconds. No stack update needed.
#
# Why 2 steps? The ELB hostname is only known after the stack is deployed.
# The cert domain must match the hostname in the browser's address bar —
# browsers silently block background JS requests to cert-mismatched domains.

set -euo pipefail

REGION=""
DOMAIN="self-signed.internal"
DAYS=365
EXISTING_CERT_ARN=""

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
        --cert-arn)
            EXISTING_CERT_ARN="$2"
            shift 2
            ;;
        -h|--help)
            grep '^#' "$0" | head -40 | sed 's/^# \?//'
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

# CN field is limited to 64 characters; use the full domain only in the SAN.
CN="${DOMAIN:0:64}"

# Generate private key and self-signed certificate
openssl req -x509 -nodes \
    -days "$DAYS" \
    -newkey rsa:2048 \
    -keyout "$KEY_FILE" \
    -out "$CERT_FILE" \
    -subj "/CN=$CN" \
    -addext "subjectAltName=DNS:$DOMAIN" \
    2>/dev/null

if [[ -n "$EXISTING_CERT_ARN" ]]; then
    echo "Reimporting certificate into existing ACM ARN..." >&2
    # shellcheck disable=SC2086
    CERT_ARN=$(aws acm import-certificate \
        --certificate-arn "$EXISTING_CERT_ARN" \
        --certificate fileb://"$CERT_FILE" \
        --private-key fileb://"$KEY_FILE" \
        --query 'CertificateArn' \
        --output text \
        $REGION_FLAG)
    echo "" >&2
    echo "Certificate reimported successfully." >&2
    echo "Same ARN — no CloudFormation stack update needed." >&2
    echo "The ALB will serve the updated cert within ~30 seconds." >&2
else
    echo "Importing certificate to ACM..." >&2
    # shellcheck disable=SC2086
    CERT_ARN=$(aws acm import-certificate \
        --certificate fileb://"$CERT_FILE" \
        --private-key fileb://"$KEY_FILE" \
        --query 'CertificateArn' \
        --output text \
        $REGION_FLAG)
    echo "" >&2
    echo "Certificate imported successfully." >&2
    echo "Use this value for the ALBCertificateArn CloudFormation parameter." >&2
fi

echo "ACM Certificate ARN: $CERT_ARN" >&2
echo "" >&2
echo "NOTE: This is a self-signed certificate for testing only." >&2
echo "Browsers will show a security warning — click through to proceed." >&2
echo "For production, use a certificate from a trusted CA that covers your internal DNS hostname." >&2

# Print just the ARN to stdout for scripting
echo "$CERT_ARN"
