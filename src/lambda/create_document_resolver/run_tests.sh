#!/bin/bash
# Quick test runner script for create_document_resolver Lambda

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="/home/josian/git/fiscalshield-idp-core/idp-linux/bin/python"
VENV_PYTEST="/home/josian/git/fiscalshield-idp-core/idp-linux/bin/pytest"

cd "$SCRIPT_DIR" || exit 1

# Parse command line arguments
case "$1" in
    "fast"|"")
        # Quick test run - no coverage
        echo -e "${BLUE}Running quick tests...${NC}"
        $VENV_PYTEST tests/ -v
        ;;
    "coverage"|"cov")
        # Test with coverage report
        echo -e "${BLUE}Running tests with coverage...${NC}"
        $VENV_PYTEST tests/ -v --cov=index --cov-report=term-missing
        ;;
    "html")
        # Test with HTML coverage report
        echo -e "${BLUE}Running tests with HTML coverage report...${NC}"
        $VENV_PYTEST tests/ -v --cov=index --cov-report=html
        echo -e "${GREEN}Coverage report generated at: htmlcov/index.html${NC}"
        ;;
    "class")
        # Run specific test class
        if [ -z "$2" ]; then
            echo "Usage: $0 class <ClassName>"
            echo "Example: $0 class TestUserIdExtraction"
            exit 1
        fi
        echo -e "${BLUE}Running test class: $2${NC}"
        $VENV_PYTEST "tests/test_index.py::$2" -v
        ;;
    "test")
        # Run specific test method
        if [ -z "$2" ] || [ -z "$3" ]; then
            echo "Usage: $0 test <ClassName> <test_method>"
            echo "Example: $0 test TestHandler test_handler_creates_user_scoped_key"
            exit 1
        fi
        echo -e "${BLUE}Running test: $2::$3${NC}"
        $VENV_PYTEST "tests/test_index.py::$2::$3" -v
        ;;
    "watch")
        # Watch mode - rerun tests on file changes (requires pytest-watch)
        echo -e "${BLUE}Running tests in watch mode...${NC}"
        $VENV_PYTHON -m pytest_watch tests/ -- -v
        ;;
    "help"|"-h"|"--help")
        echo "Usage: $0 [command] [args]"
        echo ""
        echo "Commands:"
        echo "  fast, (default)    - Quick test run without coverage"
        echo "  coverage, cov      - Run tests with coverage report"
        echo "  html               - Generate HTML coverage report"
        echo "  class <name>       - Run specific test class"
        echo "  test <class> <name>- Run specific test method"
        echo "  watch              - Watch mode (rerun on changes)"
        echo "  help               - Show this help message"
        echo ""
        echo "Examples:"
        echo "  $0                                    # Quick run"
        echo "  $0 coverage                           # With coverage"
        echo "  $0 class TestHandler                  # Run all handler tests"
        echo "  $0 test TestHandler test_handler_creates_user_scoped_key"
        ;;
    *)
        echo "Unknown command: $1"
        echo "Run '$0 help' for usage information"
        exit 1
        ;;
esac
