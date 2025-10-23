#!/bin/bash
# Central test runner for fiscalshield-idp-core

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Project paths
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$PROJECT_ROOT/idp-linux/bin/python"
VENV_PYTEST="$PROJECT_ROOT/idp-linux/bin/pytest"

cd "$PROJECT_ROOT" || exit 1

# Check if virtual environment exists
if [ ! -f "$VENV_PYTEST" ]; then
    echo -e "${RED}Error: Virtual environment not found at $PROJECT_ROOT/idp-linux${NC}"
    echo "Please activate your virtual environment first."
    exit 1
fi

# Function to display help
show_help() {
    echo "Usage: $0 [command] [options]"
    echo ""
    echo "Commands:"
    echo "  unit                     - Run all unit tests"
    echo "  integration              - Run integration tests"
    echo "  lambda <name>            - Run tests for specific lambda"
    echo "  coverage                 - Run tests with coverage report"
    echo "  html                     - Generate HTML coverage report"
    echo "  watch                    - Watch mode (rerun on changes)"
    echo "  markers                  - List available test markers"
    echo "  parallel                 - Run tests in parallel"
    echo "  user-scoping, scoping    - Run user-scoping tests only"
    echo "  verbose, -v              - Verbose output"
    echo "  help, -h                 - Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 unit                              # Run all unit tests"
    echo "  $0 lambda create_document_resolver   # Test specific lambda"
    echo "  $0 user-scoping                      # Run user-scoping tests"
    echo "  $0 coverage                          # Run with coverage"
    echo "  $0 unit -v                           # Verbose unit tests"
    echo "  $0 parallel                          # Run tests in parallel"
    echo ""
    echo "Test Markers:"
    echo "  -m unit          - Unit tests only"
    echo "  -m integration   - Integration tests only"
    echo "  -m lambda        - Lambda function tests"
    echo "  -m smoke         - Quick smoke tests"
}

# Parse command
case "$1" in
    "unit")
        echo -e "${BLUE}Running unit tests...${NC}"
        shift
        $VENV_PYTEST tests/unit/ -v --tb=short "$@"
        ;;
    
    "integration")
        echo -e "${BLUE}Running integration tests...${NC}"
        shift
        $VENV_PYTEST tests/integration/ -v "$@"
        ;;
    
    "lambda")
        if [ -z "$2" ]; then
            echo -e "${RED}Error: Lambda name required${NC}"
            echo "Usage: $0 lambda <lambda_name>"
            echo "Example: $0 lambda create_document_resolver"
            exit 1
        fi
        echo -e "${BLUE}Running tests for lambda: $2${NC}"
        shift 2
        $VENV_PYTEST "tests/unit/lambda/$1/" -v "$@"
        ;;
    
    "coverage"|"cov")
        echo -e "${BLUE}Running tests with coverage...${NC}"
        shift
        $VENV_PYTEST tests/unit/ -v \
            --cov=src/lambda \
            --cov-report=term-missing \
            --cov-report=html \
            "$@"
        echo -e "${GREEN}Coverage report: htmlcov/index.html${NC}"
        ;;
    
    "html")
        echo -e "${BLUE}Generating HTML coverage report...${NC}"
        shift
        $VENV_PYTEST tests/ -v \
            --cov=src/lambda \
            --cov-report=html \
            "$@"
        echo -e "${GREEN}Coverage report generated: htmlcov/index.html${NC}"
        ;;
    
    "watch")
        echo -e "${BLUE}Running tests in watch mode...${NC}"
        shift
        # Requires pytest-watch: pip install pytest-watch
        if ! command -v ptw &> /dev/null; then
            echo -e "${YELLOW}Installing pytest-watch...${NC}"
            $VENV_PYTHON -m pip install pytest-watch
        fi
        ptw tests/ -- -v "$@"
        ;;
    
    "markers")
        echo -e "${BLUE}Available test markers:${NC}"
        $VENV_PYTEST --markers
        ;;
    
    "parallel")
        echo -e "${BLUE}Running tests in parallel with isolated workers...${NC}"
        shift
        # Using -n auto runs tests in separate processes, avoiding module conflicts
        # Each worker gets its own Python interpreter
        $VENV_PYTEST tests/unit/ -v -n auto --tb=short "$@"
        ;;
    
    "verbose"|"-v")
        echo -e "${BLUE}Running all tests (verbose)...${NC}"
        shift
        $VENV_PYTEST tests/unit/ -vv "$@"
        ;;
    
    "all"|"")
        echo -e "${BLUE}Running all unit tests...${NC}"
        # Run each lambda test directory separately to avoid module caching issues
        # This prevents Python from caching 'index' modules across different lambdas
        echo -e "${YELLOW}Running tests in isolation to prevent module conflicts...${NC}"
        
        # Find all lambda test directories
        lambda_test_dirs=$(find tests/unit/lambda -mindepth 1 -maxdepth 1 -type d -not -name "__pycache__" -not -name ".*" | sort)
        
        # Track overall pass/fail
        overall_status=0
        total_passed=0
        total_failed=0
        
        for test_dir in $lambda_test_dirs; do
            lambda_name=$(basename "$test_dir")
            echo -e "${BLUE}Testing: ${lambda_name}${NC}"
            
            if $VENV_PYTEST "$test_dir" -v --tb=short; then
                echo -e "${GREEN}✓ ${lambda_name} passed${NC}"
            else
                echo -e "${RED}✗ ${lambda_name} failed${NC}"
                overall_status=1
            fi
            echo ""
        done
        
        # Run other unit tests (non-lambda)
        if [ -d "tests/unit/lib" ]; then
            echo -e "${BLUE}Testing: lib (idp_common_pkg)${NC}"
            if $VENV_PYTEST tests/unit/lib -v --tb=short; then
                echo -e "${GREEN}✓ lib tests passed${NC}"
            else
                echo -e "${RED}✗ lib tests failed${NC}"
                overall_status=1
            fi
        fi
        
        # Run idp_common_pkg tests
        if [ -d "lib/idp_common_pkg/tests/unit/dynamodb" ]; then
            echo -e "${BLUE}Testing: idp_common dynamodb${NC}"
            if $VENV_PYTEST lib/idp_common_pkg/tests/unit/dynamodb/ -v --tb=short; then
                echo -e "${GREEN}✓ idp_common dynamodb tests passed${NC}"
            else
                echo -e "${RED}✗ idp_common dynamodb tests failed${NC}"
                overall_status=1
            fi
        fi
        
        # Run integration flow tests
        if [ -f "tests/unit/test_user_scoped_document_flow.py" ]; then
            echo -e "${BLUE}Testing: user-scoped document flow${NC}"
            if $VENV_PYTEST tests/unit/test_user_scoped_document_flow.py -v --tb=short; then
                echo -e "${GREEN}✓ user-scoped flow tests passed${NC}"
            else
                echo -e "${RED}✗ user-scoped flow tests failed${NC}"
                overall_status=1
            fi
        fi
        
        # Exit with overall status
        exit $overall_status
        ;;
    
    "user-scoping"|"scoping")
        echo -e "${BLUE}Running user-scoping tests...${NC}"
        shift
        echo -e "${YELLOW}Testing user-scoped document flow...${NC}"
        $VENV_PYTEST tests/unit/test_user_scoped_document_flow.py -v --tb=short "$@"
        echo ""
        echo -e "${YELLOW}Testing DocumentDynamoDBService user scoping...${NC}"
        $VENV_PYTEST lib/idp_common_pkg/tests/unit/dynamodb/test_service_user_scoping.py -v --tb=short "$@"
        echo ""
        echo -e "${YELLOW}Testing create_document_resolver with user scoping...${NC}"
        $VENV_PYTEST tests/unit/lambda/create_document_resolver/test_handler.py -v --tb=short "$@"
        ;;
    
    "help"|"-h"|"--help")
        show_help
        ;;
    
    *)
        echo -e "${RED}Unknown command: $1${NC}"
        echo ""
        show_help
        exit 1
        ;;
esac

# Show summary if tests passed
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Tests completed successfully${NC}"
else
    echo -e "${RED}✗ Tests failed${NC}"
    exit 1
fi
