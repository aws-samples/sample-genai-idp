#!/usr/bin/env python3
"""
Manual test script to verify user-scoped document tracking.

This script tests the core functionality without requiring full deployment.
Run with: python scripts/test_user_scoping.py
"""

import sys
import os

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib', 'idp_common_pkg'))

from unittest.mock import Mock
from idp_common.models import Document, Status
from idp_common.dynamodb.service import DocumentDynamoDBService


def test_user_scoped_pks():
    """Test that user-scoped PKs are generated correctly."""
    print("\n=== Testing User-Scoped PK Generation ===")
    
    # Create mock client
    mock_client = Mock()
    mock_client.transact_write_items = Mock(return_value={})
    
    # Create service with mock
    service = DocumentDynamoDBService()
    service.client = mock_client
    
    # Test 1: Document with user_id
    print("\nTest 1: Document with user_id")
    doc = Document(
        id='test.pdf',
        input_key='users/user-123/test.pdf',
        user_id='user-123',
        status=Status.QUEUED,
        queued_time='2025-10-17T10:30:00Z',
        initial_event_time='2025-10-17T10:30:00Z'
    )
    
    service.create_document(doc)
    
    call_args = mock_client.transact_write_items.call_args[0][0]
    doc_item = call_args[0]['Put']['Item']
    list_item = call_args[1]['Put']['Item']
    
    expected_pk = 'user#user-123#doc#users/user-123/test.pdf'
    actual_pk = doc_item['PK']
    
    print(f"  Expected PK: {expected_pk}")
    print(f"  Actual PK:   {actual_pk}")
    print(f"  ✓ Match: {expected_pk == actual_pk}")
    print(f"  ✓ UserId in doc item: {'UserId' in doc_item}")
    print(f"  ✓ UserId in list item: {'UserId' in list_item}")
    
    assert expected_pk == actual_pk, "PK mismatch!"
    assert doc_item['UserId'] == 'user-123', "UserId not in doc item!"
    assert list_item['UserId'] == 'user-123', "UserId not in list item!"
    
    # Test 2: Document without user_id (legacy)
    print("\nTest 2: Document without user_id (legacy format)")
    mock_client.reset_mock()
    
    doc_legacy = Document(
        id='legacy.pdf',
        input_key='legacy.pdf',
        user_id=None,
        status=Status.QUEUED,
        queued_time='2025-10-17T10:30:00Z',
        initial_event_time='2025-10-17T10:30:00Z'
    )
    
    service.create_document(doc_legacy)
    
    call_args = mock_client.transact_write_items.call_args[0][0]
    doc_item = call_args[0]['Put']['Item']
    
    expected_pk = 'doc#legacy.pdf'
    actual_pk = doc_item['PK']
    
    print(f"  Expected PK: {expected_pk}")
    print(f"  Actual PK:   {actual_pk}")
    print(f"  ✓ Match: {expected_pk == actual_pk}")
    print(f"  ✓ No UserId in doc item: {'UserId' not in doc_item}")
    
    assert expected_pk == actual_pk, "Legacy PK mismatch!"
    assert 'UserId' not in doc_item, "UserId should not be in legacy doc!"
    
    print("\n✅ All PK generation tests passed!")


def test_update_operations():
    """Test that update operations use correct PKs."""
    print("\n=== Testing Update Operations ===")
    
    # Create mock client
    mock_client = Mock()
    mock_client.update_item = Mock(return_value={
        'Attributes': {
            'PK': 'user#user-456#doc#test.pdf',
            'SK': 'none',
            'ObjectKey': 'test.pdf',
            'ObjectStatus': 'COMPLETED',
            'UserId': 'user-456'
        }
    })
    
    # Create service with mock
    service = DocumentDynamoDBService()
    service.client = mock_client
    
    # Test update with user_id
    print("\nTest: Update with user_id")
    doc = Document(
        id='test.pdf',
        input_key='users/user-456/test.pdf',
        user_id='user-456',
        status=Status.COMPLETED,
        queued_time='2025-10-17T10:30:00Z',
        initial_event_time='2025-10-17T10:30:00Z'
    )
    
    service.update_document(doc)
    
    call_args = mock_client.update_item.call_args[1]
    actual_pk = call_args['key']['PK']
    expected_pk = 'user#user-456#doc#users/user-456/test.pdf'
    
    print(f"  Expected PK: {expected_pk}")
    print(f"  Actual PK:   {actual_pk}")
    print(f"  ✓ Match: {expected_pk == actual_pk}")
    
    assert expected_pk == actual_pk, "Update PK mismatch!"
    
    print("\n✅ All update tests passed!")


def test_get_operations():
    """Test that get operations use correct PKs."""
    print("\n=== Testing Get Operations ===")
    
    # Create mock client
    mock_client = Mock()
    mock_client.get_item = Mock(return_value={
        'PK': 'user#user-789#doc#test.pdf',
        'SK': 'none',
        'ObjectKey': 'test.pdf',
        'ObjectStatus': 'COMPLETED',
        'UserId': 'user-789'
    })
    
    # Create service with mock
    service = DocumentDynamoDBService()
    service.client = mock_client
    
    # Test get with user_id
    print("\nTest: Get with user_id")
    doc = service.get_document('test.pdf', user_id='user-789')
    
    call_args = mock_client.get_item.call_args[0][0]
    actual_pk = call_args['PK']
    expected_pk = 'user#user-789#doc#test.pdf'
    
    print(f"  Expected PK: {expected_pk}")
    print(f"  Actual PK:   {actual_pk}")
    print(f"  ✓ Match: {expected_pk == actual_pk}")
    print(f"  ✓ Document has user_id: {doc.user_id == 'user-789'}")
    
    assert expected_pk == actual_pk, "Get PK mismatch!"
    assert doc.user_id == 'user-789', "Document user_id not set!"
    
    print("\n✅ All get tests passed!")


def test_user_isolation():
    """Test that different users create different PKs."""
    print("\n=== Testing User Isolation ===")
    
    # Create mock client
    mock_client = Mock()
    mock_client.transact_write_items = Mock(return_value={})
    
    # Create service with mock
    service = DocumentDynamoDBService()
    service.client = mock_client
    
    # User 1 document
    doc1 = Document(
        id='invoice.pdf',
        input_key='users/alice/invoice.pdf',
        user_id='alice',
        status=Status.QUEUED,
        queued_time='2025-10-17T10:30:00Z',
        initial_event_time='2025-10-17T10:30:00Z'
    )
    
    service.create_document(doc1)
    pk1 = mock_client.transact_write_items.call_args_list[0][0][0][0]['Put']['Item']['PK']
    
    # User 2 document
    doc2 = Document(
        id='invoice.pdf',
        input_key='users/bob/invoice.pdf',
        user_id='bob',
        status=Status.QUEUED,
        queued_time='2025-10-17T10:30:00Z',
        initial_event_time='2025-10-17T10:30:00Z'
    )
    
    service.create_document(doc2)
    pk2 = mock_client.transact_write_items.call_args_list[1][0][0][0]['Put']['Item']['PK']
    
    print(f"\nAlice's document PK: {pk1}")
    print(f"Bob's document PK:   {pk2}")
    print(f"✓ PKs are different: {pk1 != pk2}")
    
    assert pk1 != pk2, "Users should have different PKs!"
    assert 'alice' in pk1, "Alice's user_id not in PK!"
    assert 'bob' in pk2, "Bob's user_id not in PK!"
    
    print("\n✅ User isolation test passed!")


def test_serialization():
    """Test that user_id survives serialization."""
    print("\n=== Testing Document Serialization ===")
    
    # Create document with user_id
    doc = Document(
        id='test.pdf',
        input_key='users/user-999/test.pdf',
        user_id='user-999',
        status=Status.QUEUED,
        queued_time='2025-10-17T10:30:00Z',
        initial_event_time='2025-10-17T10:30:00Z'
    )
    
    # Serialize to dict
    doc_dict = doc.to_dict()
    print(f"\n✓ user_id in dict: {'user_id' in doc_dict}")
    print(f"  Value: {doc_dict.get('user_id')}")
    
    # Deserialize from dict
    restored_doc = Document.from_dict(doc_dict)
    print(f"✓ user_id restored: {restored_doc.user_id == 'user-999'}")
    
    assert 'user_id' in doc_dict, "user_id not in serialized dict!"
    assert doc_dict['user_id'] == 'user-999', "user_id value incorrect in dict!"
    assert restored_doc.user_id == 'user-999', "user_id not restored from dict!"
    
    print("\n✅ Serialization test passed!")


def main():
    """Run all tests."""
    print("=" * 60)
    print("User-Scoped Document Tracking - Manual Tests")
    print("=" * 60)
    
    try:
        test_user_scoped_pks()
        test_update_operations()
        test_get_operations()
        test_user_isolation()
        test_serialization()
        
        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED!")
        print("=" * 60)
        print("\nThe user-scoped document tracking implementation is working correctly.")
        print("You can now deploy and test with real data.")
        
        return 0
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
