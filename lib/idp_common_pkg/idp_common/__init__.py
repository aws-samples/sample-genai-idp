# Use true lazy loading for all submodules
__version__ = "0.1.0"

# Cache for lazy-loaded submodules
_submodules = {}

def __getattr__(name):
    """Lazy load submodules only when accessed"""
    if name in ['bedrock', 's3', 'metrics', 'image', 'utils', 'config', 'ocr', 'classification', 'extraction', 'models']:
        if name not in _submodules:
            _submodules[name] = __import__(f"idp_common.{name}", fromlist=['*'])
        return _submodules[name]
    
    # Special handling for directly exposed functions
    if name == 'get_config':
        config = __getattr__('config')
        return config.get_config
    
    # Special handling for directly exposed classes
    if name in ['Document', 'Page', 'Section', 'Status']:
        models = __getattr__('models')
        return getattr(models, name)
    
    raise AttributeError(f"module 'idp_common' has no attribute '{name}'")

__all__ = [
    'bedrock', 's3', 'metrics', 'image', 'utils', 'config', 'ocr', 'classification', 'extraction', 'models',
    'get_config', 'Document', 'Page', 'Section', 'Status'
]