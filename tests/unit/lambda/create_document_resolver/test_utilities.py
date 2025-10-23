"""
Unit tests for utility functions and classes.

Tests helper utilities like DecimalEncoder.
"""
import json
from decimal import Decimal
import index


class TestDecimalEncoder:
    """Tests for DecimalEncoder JSON serialization."""
    
    def test_encodes_decimal_to_float(self):
        """Should convert Decimal to float in JSON."""
        data = {'value': Decimal('123.45')}
        result = json.dumps(data, cls=index.DecimalEncoder)
        assert result == '{"value": 123.45}'
    
    def test_encodes_decimal_integer(self):
        """Should convert integer Decimal to float."""
        data = {'count': Decimal('100')}
        result = json.dumps(data, cls=index.DecimalEncoder)
        assert result == '{"count": 100.0}'
    
    def test_encodes_regular_string(self):
        """Should handle regular string types normally."""
        data = {'name': 'test'}
        result = json.dumps(data, cls=index.DecimalEncoder)
        assert '"name": "test"' in result
    
    def test_encodes_regular_int(self):
        """Should handle regular int types normally."""
        data = {'count': 42}
        result = json.dumps(data, cls=index.DecimalEncoder)
        assert '"count": 42' in result
    
    def test_encodes_regular_float(self):
        """Should handle regular float types normally."""
        data = {'value': 3.14}
        result = json.dumps(data, cls=index.DecimalEncoder)
        assert '"value": 3.14' in result
    
    def test_encodes_mixed_types(self):
        """Should handle mixed types including Decimal."""
        data = {
            'string': 'test',
            'int': 42,
            'float': 3.14,
            'decimal': Decimal('99.99')
        }
        result = json.dumps(data, cls=index.DecimalEncoder)
        parsed = json.loads(result)
        assert parsed['string'] == 'test'
        assert parsed['int'] == 42
        assert parsed['float'] == 3.14
        assert parsed['decimal'] == 99.99
    
    def test_encodes_nested_decimals(self):
        """Should handle nested structures with Decimals."""
        data = {
            'outer': {
                'inner': {
                    'value': Decimal('123.45')
                }
            }
        }
        result = json.dumps(data, cls=index.DecimalEncoder)
        parsed = json.loads(result)
        assert parsed['outer']['inner']['value'] == 123.45
