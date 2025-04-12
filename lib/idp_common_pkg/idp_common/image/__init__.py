from PIL import Image
import io
import logging
from typing import Tuple, Optional, Dict, Any, Union
from ..s3 import get_binary_content
from ..utils import parse_s3_uri

logger = logging.getLogger(__name__)

def resize_image(image_data: bytes, 
                target_width: int = 951, 
                target_height: int = 1268) -> bytes:
    """
    Resize an image to target dimensions if larger than target
    
    Args:
        image_data: Raw image bytes
        target_width: Target width in pixels
        target_height: Target height in pixels
        
    Returns:
        Resized image as JPEG bytes
    """
    image = Image.open(io.BytesIO(image_data))
    current_width, current_height = image.size
    current_resolution = current_width * current_height
    target_resolution = target_width * target_height
    
    if current_resolution > target_resolution:
        logger.info(f"Downsizing image from {current_width}x{current_height}")
        image = image.resize((target_width, target_height))
    
    img_byte_array = io.BytesIO()
    image.save(img_byte_array, format="JPEG")
    return img_byte_array.getvalue()

def prepare_image(image_source: Union[str, bytes],
                 target_width: int = 951, 
                 target_height: int = 1268) -> bytes:
    """
    Prepare an image for model input from either S3 URI or raw bytes
    
    Args:
        image_source: Either an S3 URI (s3://bucket/key) or raw image bytes
        target_width: Target width in pixels
        target_height: Target height in pixels
        
    Returns:
        Processed image as JPEG bytes ready for model input
    """
    # Get the image data
    if isinstance(image_source, str) and image_source.startswith('s3://'):
        image_data = get_binary_content(image_source)
    elif isinstance(image_source, bytes):
        image_data = image_source
    else:
        raise ValueError(f"Invalid image source: {type(image_source)}. Must be S3 URI or bytes.")
        
    # Resize and process
    return resize_image(image_data, target_width, target_height)

def prepare_bedrock_image_attachment(image_data: bytes) -> Dict[str, Any]:
    """
    Format an image for Bedrock API attachment
    
    Args:
        image_data: Raw image bytes
        
    Returns:
        Formatted image attachment for Bedrock API
    """
    return {
        "image": {
            "format": 'jpeg',
            "source": {"bytes": image_data}
        }
    }