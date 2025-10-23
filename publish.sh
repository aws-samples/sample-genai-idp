#!/bin/bash

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

##############################################################################################
# GenAI IDP Publisher Wrapper Script
#
# This script acts as a wrapper for publish.py, ensuring that:
# 1. Python 3.12+ is available
# 2. Required Python packages are installed
# 3. Proper arguments are passed to the Python script
##############################################################################################

set -e # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print colored output
print_info() {
  echo -e "${BLUE}ℹ️  $1${NC}"
}

print_success() {
  echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
  echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
  echo -e "${RED}❌ $1${NC}"
}

# Print usage information
print_usage() {
  echo "Usage: $0 <cfn_bucket_basename> <cfn_prefix> <region> [public] [--max-workers N] [--verbose] [--no-validate]"
  echo ""
  echo "Arguments:"
  echo "  <cfn_bucket_basename>  Base name for the CloudFormation artifacts bucket"
  echo "  <cfn_prefix>          S3 prefix for artifacts"
  echo "  <region>              AWS region for deployment"
  echo ""
  echo "Options:"
  echo "  public                Make artifacts publicly readable"
  echo "  --max-workers N       Maximum number of concurrent workers"
  echo "  --verbose, -v         Enable verbose output"
  echo "  --no-validate         Skip CloudFormation template validation"
  echo "  --clean-build         Delete all .checksum files to force full rebuild"
  echo ""
  echo "Examples:"
  echo "  $0 my-bucket idp us-east-1"
  echo "  $0 my-bucket idp us-west-2 public --verbose"
  echo "  $0 my-bucket idp us-east-1 --max-workers 2"
}

# Check if Python 3.12+ is available
check_python_version() {
  print_info "Checking Python version..."

  # Try python3 first, then python
  for python_cmd in python3 python; do
    if command -v "$python_cmd" >/dev/null 2>&1; then
      version=$($python_cmd --version 2>&1 | cut -d' ' -f2)
      major=$(echo "$version" | cut -d'.' -f1)
      minor=$(echo "$version" | cut -d'.' -f2)

      if [[ "$major" -eq 3 && "$minor" -ge 12 ]]; then
        PYTHON_CMD="$python_cmd"
        print_success "Found Python $version at $(which $python_cmd)"
        return 0
      elif [[ "$major" -eq 3 ]]; then
        print_warning "Found Python $version, but Python 3.12+ is required"
      fi
    fi
  done

  print_error "Python 3.12+ is required but not found"
  print_info "Please install Python 3.12 or later and try again"
  exit 1
}

# Check if Node.js and npm are available for UI validation
check_nodejs_dependencies() {
  print_info "Checking Node.js dependencies for UI validation..."

  # Check Node.js
  if ! command -v node >/dev/null 2>&1; then
    print_error "Node.js not found but is required for UI build validation"
    print_info "Install Node.js 18+ from: https://nodejs.org/"
    exit 1
  fi

  # Check npm
  if ! command -v npm >/dev/null 2>&1; then
    print_error "npm not found but is required for UI build validation"
    print_info "npm is typically installed with Node.js"
    exit 1
  fi

  # Check Node.js version (require 18+)
  node_version=$(node --version 2>/dev/null | sed 's/v//')
  node_major=$(echo "$node_version" | cut -d'.' -f1)

  if [[ "$node_major" -lt 18 ]]; then
    print_error "Node.js $node_version found, but 18+ is required for UI validation"
    print_info "Please upgrade Node.js to version 18 or later"
    exit 1
  else
    print_success "Found Node.js $node_version and npm $(npm --version)"
  fi
}

# Check if required packages are installed and install them if missing
check_and_install_packages() {
  print_info "Checking required Python packages..."

  # List of required packages (import_name:package_name pairs)
  required_packages=(
    "typer:typer"
    "rich:rich"
    "boto3:boto3"
    "yaml:PyYAML"
    "ruff:ruff"
  )
  missing_packages=()

  # Check each package
  for package_pair in "${required_packages[@]}"; do
    import_name="${package_pair%%:*}"
    package_name="${package_pair##*:}"
    if ! $PYTHON_CMD -c "import $import_name" >/dev/null 2>&1; then
      missing_packages+=("$package_name")
    fi
  done

  # Check ruff separately (command-line tool)
  if ! command -v ruff >/dev/null 2>&1; then
    missing_packages+=("ruff")
  fi

  # Install missing packages if any
  if [[ ${#missing_packages[@]} -gt 0 ]]; then
    print_warning "Missing packages: ${missing_packages[*]}"
    print_info "Installing missing packages..."

    for package in "${missing_packages[@]}"; do
      print_info "Installing $package..."
      if $PYTHON_CMD -m pip install "$package" --quiet; then
        print_success "Installed $package"
      else
        print_error "Failed to install $package"
        print_info "Please install manually: $PYTHON_CMD -m pip install $package"
        exit 1
      fi
    done
  else
    print_success "All required packages are installed"
  fi
}

# Validate input parameters
validate_parameters() {
  if [[ $# -lt 3 ]]; then
    print_error "Missing required parameters"
    print_usage
    exit 1
  fi

  # Basic validation
  if [[ -z "$1" ]]; then
    print_error "Bucket basename cannot be empty"
    exit 1
  fi

  if [[ -z "$2" ]]; then
    print_error "Prefix cannot be empty"
    exit 1
  fi

  if [[ -z "$3" ]]; then
    print_error "Region cannot be empty"
    exit 1
  fi

  # Validate region format (basic check)
  if [[ ! "$3" =~ ^[a-z]{2}-[a-z]+-[0-9]+$ ]]; then
    print_warning "Region '$3' doesn't match expected format (e.g., us-east-1)"
  fi
}

# Main execution
main() {
  print_info "GenAI IDP Publisher Wrapper"
  print_info "============================"

  # Validate parameters first
  validate_parameters "$@"

  # Check Python version
  check_python_version

  # Check Node.js dependencies for UI validation
  check_nodejs_dependencies

  # Check and install required packages
  check_and_install_packages

  # Check if publish.py exists
  if [[ ! -f "publish.py" ]]; then
    print_error "publish.py not found in current directory"
    print_info "Please run this script from the GenAI IDP root directory"
    exit 1
  fi

  # Build arguments for publish.py
  print_info "Launching publish.py..."
  print_info "Arguments: $*"

  # Execute publish.py with all arguments
  exec $PYTHON_CMD publish.py "$@"
}

# Handle help flag
if [[ "$1" == "-h" || "$1" == "--help" ]]; then
  print_usage
  exit 0
fi

# Run main function with all arguments
main "$@"

