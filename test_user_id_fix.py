#!/usr/bin/env python3
"""
Test script to verify user_id extraction fix for Pattern 2 OCR Lambda.

This script simulates the Document loading flow that happens in the OCR Lambda
and verifies that user_id is properly extracted and available for AppSync updates.
"""

import json
import os
import sys

# Set minimal required environment variables for testing
os.environ['AWS_REGION'] = 'us-east-1'

from idp_common.models import Document, extract_user_id_from_object_key
from idp_common.appsync.service import DocumentAppSyncService


def test_user_id_extraction():
    """Test that user_id is extracted from object keys."""
    print("Testing user_id extraction from object keys...")
    
    # Test case 1: User-scoped path
    user_scoped_key = "users/93c46832-90d1-7096-708c-e7d4f19e6695/invoice7.pdf"
    user_id = extract_user_id_from_object_key(user_scoped_key)
    assert user_id == "93c46832-90d1-7096-708c-e7d4f19e6695", f"Expected user_id, got {user_id}"
    print(f"  ✓ Extracted user_id from user-scoped path: {user_id}")
    
    # Test case 2: Non-user-scoped path
    regular_key = "documents/invoice7.pdf"
    user_id = extract_user_id_from_object_key(regular_key)
    assert user_id is None, f"Expected None for non-user path, got {user_id}"
    print(f"  ✓ Non-user-scoped path returns None")
    
    # Test case 3: Invalid structure
    invalid_key = "users/invalid"
    user_id = extract_user_id_from_object_key(invalid_key)
    assert user_id is None, f"Expected None for invalid path, got {user_id}"
    print(f"  ✓ Invalid path structure returns None")
    
    print()


def test_document_from_dict():
    """Test that Document.from_dict extracts user_id."""
    print("Testing Document.from_dict user_id extraction...")
    
    # Test case 1: user_id not in data, should be extracted from input_key
    doc_data = {
        "input_key": "users/93c46832-90d1-7096-708c-e7d4f19e6695/invoice7.pdf",
        "status": "OCR",
        "num_pages": 1
    }
    doc = Document.from_dict(doc_data)
    assert doc.user_id == "93c46832-90d1-7096-708c-e7d4f19e6695", \
        f"Expected user_id from path, got {doc.user_id}"
    print(f"  ✓ Extracted user_id from input_key: {doc.user_id}")
    
    # Test case 2: user_id explicitly provided, should take precedence
    doc_data_explicit = {
        "input_key": "users/93c46832-90d1-7096-708c-e7d4f19e6695/invoice7.pdf",
        "user_id": "explicit-user-id",
        "status": "OCR"
    }
    doc = Document.from_dict(doc_data_explicit)
    assert doc.user_id == "explicit-user-id", \
        f"Expected explicit user_id, got {doc.user_id}"
    print(f"  ✓ Explicit user_id takes precedence")
    
    # Test case 3: Non-user-scoped path, user_id should be None
    doc_data_regular = {
        "input_key": "documents/invoice7.pdf",
        "status": "OCR"
    }
    doc = Document.from_dict(doc_data_regular)
    assert doc.user_id is None, f"Expected None for non-user path, got {doc.user_id}"
    print(f"  ✓ Non-user-scoped path has None user_id")
    
    print()


def test_document_to_update_input():
    """Test that AppSync update input includes UserId."""
    print("Testing AppSync update input generation...")
    
    # Create a document with user_id extracted from path
    doc_data = {
        "input_key": "users/93c46832-90d1-7096-708c-e7d4f19e6695/invoice7.pdf",
        "status": "OCR",
        "num_pages": 1
    }
    doc = Document.from_dict(doc_data)
    
    # Create AppSync service with a dummy URL (we won't make actual calls)
    service = DocumentAppSyncService(api_url="https://dummy-api.appsync-api.us-east-1.amazonaws.com/graphql")
    update_input = service._document_to_update_input(doc)
    
    # Verify UserId is in the update input
    assert "UserId" in update_input, "UserId missing from update input"
    assert update_input["UserId"] == "93c46832-90d1-7096-708c-e7d4f19e6695", \
        f"Expected user_id in update input, got {update_input.get('UserId')}"
    print(f"  ✓ UserId included in update input: {update_input['UserId']}")
    
    # Verify ObjectKey is correct
    assert update_input["ObjectKey"] == doc.input_key
    print(f"  ✓ ObjectKey matches input_key")
    
    print()


def test_document_serialization():
    """Test that user_id is preserved through serialization."""
    print("Testing Document serialization/deserialization...")
    
    # Create document with user_id
    doc_data = {
        "input_key": "users/93c46832-90d1-7096-708c-e7d4f19e6695/invoice7.pdf",
        "status": "OCR",
        "num_pages": 1
    }
    doc = Document.from_dict(doc_data)
    
    # Serialize to dict
    doc_dict = doc.to_dict()
    assert doc_dict["user_id"] == "93c46832-90d1-7096-708c-e7d4f19e6695", \
        f"user_id lost in to_dict, got {doc_dict.get('user_id')}"
    print(f"  ✓ user_id preserved in to_dict()")
    
    # Serialize to JSON and back
    doc_json = doc.to_json()
    doc_restored = Document.from_json(doc_json)
    assert doc_restored.user_id == "93c46832-90d1-7096-708c-e7d4f19e6695", \
        f"user_id lost in JSON round-trip, got {doc_restored.user_id}"
    print(f"  ✓ user_id preserved through JSON serialization")
    
    print()


def main():
    """Run all tests."""
    print("=" * 70)
    print("User ID Extraction Fix - Verification Tests")
    print("=" * 70)
    print()
    
    try:
        test_user_id_extraction()
        test_document_from_dict()
        test_document_to_update_input()
        test_document_serialization()
        
        print("=" * 70)
        print("All tests passed! ✓")
        print("=" * 70)
        print()
        print("The fix ensures that:")
        print("  1. user_id is automatically extracted from S3 object keys")
        print("  2. Document objects have user_id populated")
        print("  3. AppSync updates include the required UserId field")
        print("  4. OCR Lambda can successfully update user-scoped documents")
        print()
        return 0
        
    except AssertionError as e:
        print()
        print("=" * 70)
        print(f"Test failed: {e}")
        print("=" * 70)
        return 1
    except Exception as e:
        print()
        print("=" * 70)
        print(f"Unexpected error: {e}")
        print("=" * 70)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
