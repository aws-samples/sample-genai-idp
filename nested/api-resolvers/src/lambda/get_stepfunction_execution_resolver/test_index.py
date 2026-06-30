# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from datetime import datetime

import pytest
from index import find_step_name_for_failure_event, parse_execution_history


@pytest.mark.unit
def test_parse_execution_history_with_failure():
    """Test that parse_execution_history correctly handles task failures"""
    
    # Mock execution history events that simulate a failure scenario
    events = [
        {
            'id': 1,
            'type': 'ExecutionStarted',
            'timestamp': datetime(2024, 1, 1, 10, 0, 0),
            'executionStartedEventDetails': {}
        },
        {
            'id': 2,
            'type': 'TaskStateEntered',
            'timestamp': datetime(2024, 1, 1, 10, 0, 1),
            'stateEnteredEventDetails': {
                'name': 'ClassificationStep',
                'input': '{"document": "test.pdf"}'
            }
        },
        {
            'id': 3,
            'type': 'TaskFailed',
            'timestamp': datetime(2024, 1, 1, 10, 0, 5),
            'previousEventId': 2,
            'taskFailedEventDetails': {
                'error': 'ValidationException',
                'cause': '{"errorType": "ValidationException", "errorMessage": "Invalid document format"}'
            }
        }
    ]
    
    steps = parse_execution_history(events)
    
    # Should have one step
    assert len(steps) == 1
    
    # Check step details
    step = steps[0]
    assert step['name'] == 'ClassificationStep'
    assert step['status'] == 'FAILED'
    assert step['error'] == 'ValidationException: Invalid document format'
    assert step['startDate'] == '2024-01-01T10:00:01'
    assert step['stopDate'] == '2024-01-01T10:00:05'

@pytest.mark.unit
def test_parse_execution_history_with_success():
    """Test that parse_execution_history correctly handles successful execution"""
    
    events = [
        {
            'id': 1,
            'type': 'ExecutionStarted',
            'timestamp': datetime(2024, 1, 1, 10, 0, 0),
            'executionStartedEventDetails': {}
        },
        {
            'id': 2,
            'type': 'TaskStateEntered',
            'timestamp': datetime(2024, 1, 1, 10, 0, 1),
            'stateEnteredEventDetails': {
                'name': 'ClassificationStep',
                'input': '{"document": "test.pdf"}'
            }
        },
        {
            'id': 3,
            'type': 'TaskStateExited',
            'timestamp': datetime(2024, 1, 1, 10, 0, 5),
            'stateExitedEventDetails': {
                'name': 'ClassificationStep',
                'output': '{"classification": "invoice"}'
            }
        }
    ]
    
    steps = parse_execution_history(events)
    
    # Should have one step
    assert len(steps) == 1
    
    # Check step details
    step = steps[0]
    assert step['name'] == 'ClassificationStep'
    assert step['status'] == 'SUCCEEDED'
    assert step['error'] is None
    assert step['output'] == '{"classification": "invoice"}'

@pytest.mark.unit
def test_find_step_name_for_failure_event():
    """Test that find_step_name_for_failure_event correctly identifies the failed step"""
    
    failure_event = {
        'id': 3,
        'type': 'TaskFailed',
        'previousEventId': 2,
        'taskFailedEventDetails': {
            'error': 'ValidationException',
            'cause': 'Invalid input'
        }
    }
    
    all_events = [
        {
            'id': 1,
            'type': 'ExecutionStarted',
            'timestamp': datetime(2024, 1, 1, 10, 0, 0)
        },
        {
            'id': 2,
            'type': 'TaskStateEntered',
            'timestamp': datetime(2024, 1, 1, 10, 0, 1),
            'stateEnteredEventDetails': {
                'name': 'ClassificationStep'
            }
        },
        failure_event
    ]
    
    event_id_to_step = {2: 'ClassificationStep'}
    
    step_name = find_step_name_for_failure_event(failure_event, all_events, event_id_to_step)
    
    assert step_name == 'ClassificationStep'

@pytest.mark.unit
def test_parse_execution_history_with_timeout():
    """Test that parse_execution_history correctly handles task timeouts"""
    
    events = [
        {
            'id': 1,
            'type': 'ExecutionStarted',
            'timestamp': datetime(2024, 1, 1, 10, 0, 0),
            'executionStartedEventDetails': {}
        },
        {
            'id': 2,
            'type': 'TaskStateEntered',
            'timestamp': datetime(2024, 1, 1, 10, 0, 1),
            'stateEnteredEventDetails': {
                'name': 'ProcessingStep',
                'input': '{"document": "test.pdf"}'
            }
        },
        {
            'id': 3,
            'type': 'TaskTimedOut',
            'timestamp': datetime(2024, 1, 1, 10, 5, 0),
            'previousEventId': 2,
            'taskTimedOutEventDetails': {
                'error': 'States.Timeout',
                'cause': 'Task timed out after 300 seconds'
            }
        }
    ]
    
    steps = parse_execution_history(events)
    
    # Should have one step
    assert len(steps) == 1
    
    # Check step details
    step = steps[0]
    assert step['name'] == 'ProcessingStep'
    assert step['status'] == 'FAILED'
    assert 'Task timed out' in step['error']
    assert step['startDate'] == '2024-01-01T10:00:01'
    assert step['stopDate'] == '2024-01-01T10:05:00'

@pytest.mark.unit
def test_parse_execution_history_multiple_steps():
    """Test parsing execution history with multiple steps including failures"""
    
    events = [
        {
            'id': 1,
            'type': 'ExecutionStarted',
            'timestamp': datetime(2024, 1, 1, 10, 0, 0),
            'executionStartedEventDetails': {}
        },
        # First step - succeeds
        {
            'id': 2,
            'type': 'TaskStateEntered',
            'timestamp': datetime(2024, 1, 1, 10, 0, 1),
            'stateEnteredEventDetails': {
                'name': 'UploadStep',
                'input': '{"document": "test.pdf"}'
            }
        },
        {
            'id': 3,
            'type': 'TaskStateExited',
            'timestamp': datetime(2024, 1, 1, 10, 0, 3),
            'stateExitedEventDetails': {
                'name': 'UploadStep',
                'output': '{"uploaded": true}'
            }
        },
        # Second step - fails
        {
            'id': 4,
            'type': 'TaskStateEntered',
            'timestamp': datetime(2024, 1, 1, 10, 0, 4),
            'stateEnteredEventDetails': {
                'name': 'ClassificationStep',
                'input': '{"document": "test.pdf"}'
            }
        },
        {
            'id': 5,
            'type': 'TaskFailed',
            'timestamp': datetime(2024, 1, 1, 10, 0, 8),
            'previousEventId': 4,
            'taskFailedEventDetails': {
                'error': 'ValidationException',
                'cause': '{"errorType": "ValidationException", "errorMessage": "Invalid document format"}'
            }
        }
    ]
    
    steps = parse_execution_history(events)
    
    # Should have two steps
    assert len(steps) == 2
    
    # Check first step (successful)
    upload_step = steps[0]
    assert upload_step['name'] == 'UploadStep'
    assert upload_step['status'] == 'SUCCEEDED'
    assert upload_step['error'] is None
    
    # Check second step (failed)
    classification_step = steps[1]
    assert classification_step['name'] == 'ClassificationStep'
    assert classification_step['status'] == 'FAILED'
    assert classification_step['error'] == 'ValidationException: Invalid document format'
