// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/* eslint-disable react/prop-types */
/* eslint-disable prettier/prettier */
/* eslint-disable prefer-destructuring */
import React, { useState, useEffect, useRef, memo } from 'react';
import {
  Modal,
  Box,
  SpaceBetween,
  FormField,
  Input,
  Checkbox,
  Container,
  Header,
  Spinner,
  Button,
} from '@awsui/components-react';
import { Logger } from 'aws-amplify';
import generateS3PresignedUrl from '../common/generate-s3-presigned-url';
import useAppContext from '../../contexts/app';
import { getFieldConfidenceInfo } from '../common/confidence-alerts-utils';

const logger = new Logger('VisualEditorModal');

// Memoized component to render a bounding box on an image
const BoundingBox = memo(({ box, page, currentPage, imageRef, zoomLevel = 1, panOffset = { x: 0, y: 0 } }) => {
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });

  useEffect(() => {
    if (imageRef.current && page === currentPage) {
      const updateDimensions = () => {
        const img = imageRef.current;
        const rect = img.getBoundingClientRect();
        const containerRect = img.parentElement.getBoundingClientRect();
        
        // Get the actual displayed dimensions and position after all transforms
        const transformedWidth = rect.width;
        const transformedHeight = rect.height;
        const transformedOffsetX = rect.left - containerRect.left;
        const transformedOffsetY = rect.top - containerRect.top;
        
        setDimensions({
          transformedWidth,
          transformedHeight,
          transformedOffsetX,
          transformedOffsetY,
        });
        
        logger.debug('VisualEditorModal - BoundingBox dimensions updated:', {
          imageWidth: img.width,
          imageHeight: img.height,
          naturalWidth: img.naturalWidth,
          naturalHeight: img.naturalHeight,
          offsetX: rect.left - containerRect.left,
          offsetY: rect.top - containerRect.top,
          imageRect: rect,
          containerRect
        });
      };

      // Update dimensions when image loads
      if (imageRef.current.complete && imageRef.current.naturalWidth > 0) {
        updateDimensions();
      } else {
        imageRef.current.addEventListener('load', updateDimensions);
      }

      return () => {
        if (imageRef.current) {
          imageRef.current.removeEventListener('load', updateDimensions);
        }
      };
    }
    return undefined;
  }, [imageRef, page, currentPage]);

  // Update dimensions when zoom or pan changes
  useEffect(() => {
    if (imageRef.current && page === currentPage) {
      const updateDimensions = () => {
        const img = imageRef.current;
        const rect = img.getBoundingClientRect();
        const containerRect = img.parentElement.getBoundingClientRect();
        
        // Get the actual displayed dimensions and position after all transforms
        const transformedWidth = rect.width;
        const transformedHeight = rect.height;
        const transformedOffsetX = rect.left - containerRect.left;
        const transformedOffsetY = rect.top - containerRect.top;
        
        setDimensions({
          transformedWidth,
          transformedHeight,
          transformedOffsetX,
          transformedOffsetY,
        });
      };
      
      // Small delay to allow transforms to complete
      const timeoutId = setTimeout(updateDimensions, 50);
      
      return () => clearTimeout(timeoutId);
    }
    return undefined;
  }, [zoomLevel, panOffset, imageRef, page, currentPage]);

  if (page !== currentPage || !box || !dimensions.transformedWidth) {
    return null;
  }

  // Calculate position based on image dimensions with proper zoom and pan handling
  if (!box.boundingBox) {
    return null;
  }

  const bbox = box.boundingBox;
  
  // Calculate position and size directly on the transformed image
  const finalLeft = bbox.left * dimensions.transformedWidth + dimensions.transformedOffsetX;
  const finalTop = bbox.top * dimensions.transformedHeight + dimensions.transformedOffsetY;
  const finalWidth = bbox.width * dimensions.transformedWidth;
  const finalHeight = bbox.height * dimensions.transformedHeight;
  
  // Position the bounding box directly without additional transforms
  const style = {
    position: 'absolute',
    left: `${finalLeft}px`,
    top: `${finalTop}px`,
    width: `${finalWidth}px`,
    height: `${finalHeight}px`,
    border: '2px solid red',
    pointerEvents: 'none',
    zIndex: 10,
    transition: 'all 0.1s ease-out'
  };
  
  logger.debug('VisualEditorModal - BoundingBox style calculated:', {
    bbox,
    dimensions,
    finalLeft,
    finalTop,
    finalWidth,
    finalHeight,
    style
  });

  return <div style={style} />;
});

// Memoized component to render a form field based on its type
const FormFieldRenderer = memo(({
  fieldKey,
  value,
  onChange,
  isReadOnly,
  confidence,
  geometry,
  onFieldFocus,
  onFieldDoubleClick,
  path = [],
  explainabilityInfo = null,
}) => {
  // Determine field type
  let fieldType = typeof value;
  if (Array.isArray(value)) {
    fieldType = 'array';
  } else if (value === null || value === undefined) {
    fieldType = 'null';
  }

  // Get confidence information from explainability data (for all fields)
  // Filter out structural keys from the path for explainability lookup
  // We need to remove top-level keys like 'inference_result', 'explainability_info', etc.
  const structuralKeys = ['inference_result', 'inferenceResult', 'explainability_info'];
  let filteredPath = path.filter(
    (pathSegment) => !structuralKeys.includes(pathSegment) && typeof pathSegment !== 'undefined',
  );
  
  // Remove the field name itself from the path if it's the last element
  // The path should point to the parent container, not include the field name
  if (filteredPath.length > 0 && filteredPath[filteredPath.length - 1] === fieldKey) {
    filteredPath = filteredPath.slice(0, -1);
  }
  
  const confidenceInfo = getFieldConfidenceInfo(fieldKey, explainabilityInfo, filteredPath);

  // Determine color and style for confidence display
  let confidenceColor;
  let confidenceStyle;
  if (confidenceInfo.hasConfidenceInfo) {
    if (confidenceInfo.displayMode === 'with-threshold') {
      confidenceColor = confidenceInfo.isAboveThreshold ? 'text-status-success' : 'text-status-error';
      confidenceStyle = undefined;
    } else {
      confidenceColor = undefined;
      confidenceStyle = { color: confidenceInfo.textColor };
    }
  }

  // Create label with confidence score if available (legacy support)
  const label = confidence !== undefined ? `${fieldKey} (${(confidence * 100).toFixed(1)}%)` : fieldKey;

  // Handle field focus - pass geometry info if available
  const handleFocus = () => {
    if (geometry && onFieldFocus) {
      onFieldFocus(geometry);
    }
  };

  // Handle field click - optimized version
  const handleClick = (event) => {
    const clickStart = performance.now();
    logger.debug('🖱️ FIELD CLICK START:', { fieldKey, timestamp: clickStart });
    
    if (event) {
      event.stopPropagation();
    }
    
    let actualGeometry = geometry;
    
    // Try to extract geometry from explainabilityInfo if not provided
    if (!actualGeometry && explainabilityInfo && Array.isArray(explainabilityInfo) && explainabilityInfo[0]) {
      const [firstExplainabilityItem] = explainabilityInfo;
      
      // Try direct field lookup first
      let fieldInfo = firstExplainabilityItem[fieldKey];
      
      // If not found directly, try to navigate the full path
      if (!fieldInfo) {
        const fullPathParts = [...path, fieldKey];
        let pathFieldInfo = firstExplainabilityItem;
        
        fullPathParts.forEach((pathPart) => {
          if (pathFieldInfo && typeof pathFieldInfo === 'object') {
            if (Array.isArray(pathFieldInfo) && !Number.isNaN(parseInt(pathPart, 10))) {
              const arrayIndex = parseInt(pathPart, 10);
              if (arrayIndex >= 0 && arrayIndex < pathFieldInfo.length) {
                pathFieldInfo = pathFieldInfo[arrayIndex];
              } else {
                pathFieldInfo = null;
              }
            } else if (pathFieldInfo[pathPart]) {
              pathFieldInfo = pathFieldInfo[pathPart];
            } else {
              pathFieldInfo = null;
            }
          } else {
            pathFieldInfo = null;
          }
        });
        
        fieldInfo = pathFieldInfo;
      }
      
      if (fieldInfo && fieldInfo.geometry && Array.isArray(fieldInfo.geometry) && fieldInfo.geometry[0]) {
        actualGeometry = fieldInfo.geometry[0];
      }
    }
    
    if (actualGeometry && onFieldFocus) {
      const focusStart = performance.now();
      logger.debug('🎯 FIELD FOCUS START:', { fieldKey, timestamp: focusStart });
      onFieldFocus(actualGeometry);
      const focusEnd = performance.now();
      logger.debug('✅ FIELD FOCUS END:', { fieldKey, duration: `${(focusEnd - focusStart).toFixed(2)}ms` });
    }
    
    const clickEnd = performance.now();
    logger.debug('🏁 FIELD CLICK END:', { fieldKey, totalDuration: `${(clickEnd - clickStart).toFixed(2)}ms` });
  };

  // Handle field double-click
  const handleDoubleClick = (event) => {
    if (event) {
      event.stopPropagation();
    }
    logger.debug('=== FIELD DOUBLE-CLICKED ===');
    logger.debug('Field Key:', fieldKey);
    logger.debug('Geometry Passed:', geometry);
    
    let actualGeometry = geometry;
    
    // Try to extract geometry from explainabilityInfo if not provided
    if (!actualGeometry && explainabilityInfo && Array.isArray(explainabilityInfo) && explainabilityInfo[0]) {
      const [firstExplainabilityItem] = explainabilityInfo;
      const fieldInfo = firstExplainabilityItem[fieldKey];
      
      if (fieldInfo && fieldInfo.geometry && Array.isArray(fieldInfo.geometry) && fieldInfo.geometry[0]) {
        actualGeometry = fieldInfo.geometry[0];
      }
    }
    
    if (actualGeometry && onFieldDoubleClick) {
      logger.debug('Calling onFieldDoubleClick with geometry:', actualGeometry);
      onFieldDoubleClick(actualGeometry);
    } else {
      logger.debug('No geometry found for field double-click:', fieldKey);
    }
    logger.debug('=== END FIELD DOUBLE-CLICK ===');
  };

  // Render based on field type
  switch (fieldType) {
    case 'string':
      return (
        <div
          onClick={handleClick}
          onDoubleClick={handleDoubleClick}
          onKeyDown={(e) => e.key === 'Enter' && handleClick(e)}
          role="button"
          tabIndex={0}
          style={{ cursor: geometry ? 'pointer' : 'default' }}
        >
          <FormField label={
            <Box>
              {fieldKey}:
              {confidenceInfo.hasConfidenceInfo && (
                <Box
                  fontSize="body-s"
                  padding={{ top: 'xxxs' }}
                  color={confidenceColor}
                  style={confidenceStyle}
                >
                  {confidenceInfo.displayMode === 'with-threshold' 
                    ? `Confidence: ${(confidenceInfo.confidence * 100).toFixed(1)}% / Threshold: ${(confidenceInfo.confidenceThreshold * 100).toFixed(1)}%`
                    : `Confidence: ${(confidenceInfo.confidence * 100).toFixed(1)}%`
                  }
                </Box>
              )}
            </Box>
          }>
            <Input
              value={value || ''}
              disabled={isReadOnly}
              onChange={({ detail }) => {
                const startTime = performance.now();
                logger.debug('🔥 KEYSTROKE START:', {
                  fieldKey, newValue: detail.value, isReadOnly, timestamp: startTime
                });
                
                if (!isReadOnly) {
                  logger.debug('🔄 Calling onChange...', { fieldKey });
                  const changeStartTime = performance.now();
                  onChange(detail.value);
                  const changeEndTime = performance.now();
                  logger.debug('✅ onChange completed:', { fieldKey, duration: `${(changeEndTime - changeStartTime).toFixed(2)}ms` });
                }
                
                const endTime = performance.now();
                logger.debug('🏁 KEYSTROKE END:', { fieldKey, totalDuration: `${(endTime - startTime).toFixed(2)}ms` });
              }}
              onFocus={handleFocus}
            />
          </FormField>
        </div>
      );

    case 'number':
      return (
        <div
          onClick={handleClick}
          onDoubleClick={handleDoubleClick}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              handleClick(e);
            }
          }}
          role="button"
          tabIndex={0}
          style={{ cursor: geometry ? 'pointer' : 'default' }}
        >
          <FormField label={
            <Box>
              {fieldKey}:
              {confidenceInfo.hasConfidenceInfo && (
                <Box
                  fontSize="body-s"
                  padding={{ top: 'xxxs' }}
                  color={confidenceColor}
                  style={confidenceStyle}
                >
                  {confidenceInfo.displayMode === 'with-threshold' 
                    ? `Confidence: ${(confidenceInfo.confidence * 100).toFixed(1)}% / Threshold: ${(confidenceInfo.confidenceThreshold * 100).toFixed(1)}%`
                    : `Confidence: ${(confidenceInfo.confidence * 100).toFixed(1)}%`
                  }
                </Box>
              )}
            </Box>
          }>
            <Input
              type="number"
              value={String(value)}
              disabled={isReadOnly}
              onChange={({ detail }) => {
                if (!isReadOnly) {
                  const numValue = Number(detail.value);
                  onChange(Number.isNaN(numValue) ? 0 : numValue);
                }
              }}
              onFocus={handleFocus}
            />
          </FormField>
        </div>
      );

    case 'boolean':
      return (
        <div
          onClick={handleClick}
          onDoubleClick={handleDoubleClick}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              handleClick(e);
            }
          }}
          role="button"
          tabIndex={0}
          style={{ cursor: geometry ? 'pointer' : 'default' }}
        >
          <FormField label={
            <Box>
              {fieldKey}:
              {confidenceInfo.hasConfidenceInfo && (
                <Box
                  fontSize="body-s"
                  padding={{ top: 'xxxs' }}
                  color={confidenceColor}
                  style={confidenceStyle}
                >
                  {confidenceInfo.displayMode === 'with-threshold' 
                    ? `Confidence: ${(confidenceInfo.confidence * 100).toFixed(1)}% / Threshold: ${(confidenceInfo.confidenceThreshold * 100).toFixed(1)}%`
                    : `Confidence: ${(confidenceInfo.confidence * 100).toFixed(1)}%`
                  }
                </Box>
              )}
            </Box>
          }>
            <Checkbox
              checked={Boolean(value)}
              disabled={isReadOnly}
              onChange={({ detail }) => !isReadOnly && onChange(detail.checked)}
              onFocus={handleFocus}
            >
              {String(value)}
            </Checkbox>
          </FormField>
        </div>
      );

    case 'object':
      if (value === null) {
        return (
          <FormField label={label}>
            <Input value="null" disabled={isReadOnly} onFocus={handleFocus} />
          </FormField>
        );
      }

      return (
        <Box padding="xs">
          <Box fontSize="body-m" fontWeight="bold" padding="xxxs" onFocus={handleFocus}>
            {label}
          </Box>
          <Box padding={{ left: 'l' }}>
            <SpaceBetween size="xs">
              {Object.entries(value).map(([key, val]) => {
                // Get confidence and geometry for this field from explainability_info
                let fieldConfidence;
                let fieldGeometry;
                
                // Try to get from explainability_info if available
                if (explainabilityInfo && Array.isArray(explainabilityInfo)) {
                  // Handle nested structure like explainabilityInfo[0].NAME_DETAILS.LAST_NAME
                  const currentPath = [...path, key];
                  const [firstExplainabilityItem] = explainabilityInfo;
                  // eslint-disable-next-line prefer-destructuring
                  let fieldInfo = firstExplainabilityItem;
                  
                  // Navigate through the path to find the field info
                  let pathFieldInfo = fieldInfo;
                  currentPath.forEach((pathPart) => {
                    if (pathFieldInfo && typeof pathFieldInfo === 'object' && pathFieldInfo[pathPart]) {
                      pathFieldInfo = pathFieldInfo[pathPart];
                    } else {
                      pathFieldInfo = null;
                    }
                  });
                  fieldInfo = pathFieldInfo;
                  
                  if (fieldInfo) {
                    fieldConfidence = fieldInfo.confidence;
                    
                    // Extract geometry - handle both direct geometry and geometry arrays
                    if (fieldInfo.geometry && Array.isArray(fieldInfo.geometry) && fieldInfo.geometry.length > 0) {
                      const geomData = fieldInfo.geometry[0];
                      if (geomData.boundingBox && geomData.page !== undefined) {
                        fieldGeometry = {
                          boundingBox: geomData.boundingBox,
                          page: geomData.page,
                          vertices: geomData.vertices
                        };
                      }
                    }
                  }
                }
                                
                return (
                  <FormFieldRenderer
                    key={`obj-${fieldKey}-${path.join('.')}-${key}`}
                    fieldKey={key}
                    value={val}
                    onChange={(newVal) => {
                      if (!isReadOnly) {
                        const newObj = { ...value };
                        newObj[key] = newVal;
                        onChange(newObj);
                      }
                    }}
                    isReadOnly={isReadOnly}
                    confidence={fieldConfidence}
                    geometry={fieldGeometry}
                    onFieldFocus={onFieldFocus}
                    onFieldDoubleClick={onFieldDoubleClick}
                    path={[...path, key]}
                    explainabilityInfo={explainabilityInfo}
                  />
                );
              })}
            </SpaceBetween>
          </Box>
        </Box>
      );

    case 'array':
      return (
        <Box padding="xs">
          <Box fontSize="body-m" fontWeight="bold" padding="xxxs" onFocus={handleFocus}>
            {label} ({value.length} items)
          </Box>
          <Box padding={{ left: 'l' }}>
            <SpaceBetween size="xs">
              {value.map((item, index) => {
                // Create a stable unique key for each array item
                const itemKey = `arr-${fieldKey}-${path.join('.')}-${index}`;

                // Extract confidence and geometry for array items
                let itemConfidence;
                let itemGeometry;
                
                // Try to get from explainability_info if available
                if (explainabilityInfo && Array.isArray(explainabilityInfo)) {
                  const [firstExplainabilityItem] = explainabilityInfo;
                  
                  // Handle nested structure - navigate to the array field first
                  let arrayFieldInfo = firstExplainabilityItem;
                  path.forEach((pathPart) => {
                    if (arrayFieldInfo && typeof arrayFieldInfo === 'object' && arrayFieldInfo[pathPart]) {
                      arrayFieldInfo = arrayFieldInfo[pathPart];
                    } else {
                      arrayFieldInfo = null;
                    }
                  });
                  
                  // For arrays, the explainability info structure can be:
                  // 1. An array where each element has confidence/geometry (e.g., ENDORSEMENTS, RESTRICTIONS)
                  // 2. An object with nested structure
                  if (arrayFieldInfo && Array.isArray(arrayFieldInfo) && arrayFieldInfo[index]) {
                    const itemInfo = arrayFieldInfo[index];
                    if (itemInfo) {
                      itemConfidence = itemInfo.confidence;
                      
                      // Extract geometry
                      if (itemInfo.geometry && Array.isArray(itemInfo.geometry) && itemInfo.geometry.length > 0) {
                        const geomData = itemInfo.geometry[0];
                        if (geomData.boundingBox && geomData.page !== undefined) {
                          itemGeometry = {
                            boundingBox: geomData.boundingBox,
                            page: geomData.page,
                            vertices: geomData.vertices
                          };
                        }
                      }
                    }
                  }
                }

                return (
                  <FormFieldRenderer
                    key={itemKey}
                    fieldKey={`[${index}]`}
                    value={item}
                    onChange={(newVal) => {
                      if (!isReadOnly) {
                        const newArray = [...value];
                        newArray[index] = newVal;
                        onChange(newArray);
                      }
                    }}
                    isReadOnly={isReadOnly}
                    confidence={itemConfidence}
                    geometry={itemGeometry}
                    onFieldFocus={onFieldFocus}
                    onFieldDoubleClick={onFieldDoubleClick}
                    path={[...path, index]}
                    explainabilityInfo={explainabilityInfo}
                  />
                );
              })}
            </SpaceBetween>
          </Box>
        </Box>
      );

    default:
      return (
        <div
          onClick={handleClick}
          onDoubleClick={handleDoubleClick}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              handleClick(e);
            }
          }}
          role="button"
          tabIndex={0}
          style={{ cursor: geometry ? 'pointer' : 'default' }}
        >
          <FormField label={
            <Box>
              {fieldKey}:
              {confidenceInfo.hasConfidenceInfo && (
                <Box
                  fontSize="body-s"
                  padding={{ top: 'xxxs' }}
                  color={confidenceColor}
                  style={confidenceStyle}
                >
                  {confidenceInfo.displayMode === 'with-threshold' 
                    ? `Confidence: ${(confidenceInfo.confidence * 100).toFixed(1)}% / Threshold: ${(confidenceInfo.confidenceThreshold * 100).toFixed(1)}%`
                    : `Confidence: ${(confidenceInfo.confidence * 100).toFixed(1)}%`
                  }
                </Box>
              )}
            </Box>
          }>
            <Input
              value={String(value)}
              disabled={isReadOnly}
              onChange={({ detail }) => !isReadOnly && onChange(detail.value)}
              onFocus={handleFocus}
            />
          </FormField>
        </div>
      );
  }
});

const VisualEditorModal = ({ visible, onDismiss, jsonData, onChange, isReadOnly, sectionData }) => {
  const { currentCredentials } = useAppContext();
  const [pageImages, setPageImages] = useState({});
  const [loadingImages, setLoadingImages] = useState(true);
  const [currentPage, setCurrentPage] = useState(null);
  const [activeFieldGeometry, setActiveFieldGeometry] = useState(null);
  const [zoomLevel, setZoomLevel] = useState(1);
  const [panOffset, setPanOffset] = useState({ x: 0, y: 0 });
  const [localJsonData, setLocalJsonData] = useState(jsonData);
  const imageRef = useRef(null);
  const imageContainerRef = useRef(null);
  const debounceTimerRef = useRef(null);

  // Sync local data with props
  useEffect(() => {
    setLocalJsonData(jsonData);
  }, [jsonData]);

  // Debounced parent onChange function with non-blocking execution
  const debouncedParentOnChange = (jsonString) => {
    // Clear existing timer
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
    }

    // Set new timer - call parent after 1 second of no typing
    debounceTimerRef.current = setTimeout(() => {
      if (onChange) {
        const parentCallStart = performance.now();
        logger.debug('🚀 DEBOUNCED PARENT onChange - Calling parent onChange...');
        
        // Use requestIdleCallback to ensure parent onChange doesn't block UI
        // If not available, fall back to setTimeout with 0 delay
        const executeParentChange = () => {
          try {
            onChange(jsonString);
            const parentCallEnd = performance.now();
            logger.debug('🏁 DEBOUNCED PARENT onChange - Parent onChange completed:', {
              duration: `${(parentCallEnd - parentCallStart).toFixed(2)}ms`
            });
          } catch (error) {
            logger.error('Error in parent onChange:', error);
          }
        };
        
        if (window.requestIdleCallback) {
          // Use requestIdleCallback to run during browser idle time
          window.requestIdleCallback(executeParentChange, { timeout: 5000 });
        } else {
          // Fallback: use setTimeout to yield control back to browser
          setTimeout(executeParentChange, 0);
        }
      }
    }, 1000); // 1 second debounce
  };

  // Cleanup debounce timer on unmount
  useEffect(() => {
    return () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
    };
  }, []);

  // Extract inference results and page IDs from local data for immediate UI updates
  const inferenceResult = localJsonData?.inference_result || localJsonData?.inferenceResult || localJsonData;
  const pageIds = sectionData?.PageIds || [];



  // Load page images - only when modal opens or when core data changes
  useEffect(() => {
    if (!visible) {
      // Reset state when modal closes
      setPageImages({});
      setCurrentPage(null);
      setActiveFieldGeometry(null);
      return;
    }

    const loadImages = async () => {
      if (!pageIds || pageIds.length === 0) {
        setLoadingImages(false);
        return;
      }

      setLoadingImages(true);

      try {
        const documentPages = sectionData?.documentItem?.pages || [];
        logger.debug('VisualEditorModal - Loading images for pageIds:', pageIds);

        const images = {};

        await Promise.all(
          pageIds.map(async (pageId) => {
            // Find the page in the document's pages array by matching the Id
            const page = documentPages.find((p) => p.Id === pageId);

            if (page?.ImageUri) {
              try {
                logger.debug(`VisualEditorModal - generating presigned URL for page ${pageId}`);
                const url = await generateS3PresignedUrl(page.ImageUri, currentCredentials);
                images[pageId] = url;
              } catch (err) {
                logger.error(`Error generating presigned URL for page ${pageId}:`, err);
              }
            }
          }),
        );

        logger.debug('VisualEditorModal - Successfully loaded images for', Object.keys(images).length, 'pages');

        setPageImages(images);

        // Set the first page as current if not already set
        if (!currentPage && pageIds.length > 0) {
          setCurrentPage(pageIds[0]);
        }
      } catch (err) {
        logger.error('Error loading page images:', err);
      } finally {
        setLoadingImages(false);
      }
    };

    loadImages();
    // Only reload images when modal opens or when pageIds/sectionData changes, not when switching pages
  }, [visible, pageIds, sectionData?.documentItem?.pages, currentCredentials]);

  // Zoom controls
  const handleZoomIn = () => {
    setZoomLevel(prev => Math.min(prev * 1.25, 4));
  };

  const handleZoomOut = () => {
    setZoomLevel(prev => Math.max(prev / 1.25, 0.25));
  };

  // Pan controls
  const panStep = 50;
  
  const handlePanLeft = () => {
    setPanOffset(prev => ({ ...prev, x: prev.x + panStep }));
  };

  const handlePanRight = () => {
    setPanOffset(prev => ({ ...prev, x: prev.x - panStep }));
  };

  const handlePanUp = () => {
    setPanOffset(prev => ({ ...prev, y: prev.y + panStep }));
  };

  const handlePanDown = () => {
    setPanOffset(prev => ({ ...prev, y: prev.y - panStep }));
  };

  const handleResetView = () => {
    setZoomLevel(1);
    setPanOffset({ x: 0, y: 0 });
  };

  // Handle mouse wheel for zoom
  const handleWheel = (e) => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      const delta = e.deltaY < 0 ? 1.1 : 0.9;
      setZoomLevel(prev => Math.min(Math.max(prev * delta, 0.25), 4));
    }
  };

  // Handle field focus - update active field geometry and switch to the correct page
  // This function is intentionally kept lightweight and independent of debounced operations
  const handleFieldFocus = (geometry) => {
    const focusStart = performance.now();
    logger.debug('VisualEditorModal - handleFieldFocus START:', { timestamp: focusStart });
    
    // Use setTimeout to make this completely asynchronous and non-blocking
    setTimeout(() => {
      if (geometry) {
        setActiveFieldGeometry(geometry);

        // If geometry has a page field, switch to that page
        if (geometry.page !== undefined && pageIds.length > 0) {
          const pageIndex = geometry.page - 1;
          if (pageIndex >= 0 && pageIndex < pageIds.length) {
            const targetPageId = pageIds[pageIndex];
            setCurrentPage(targetPageId);
          }
        }
      } else {
        setActiveFieldGeometry(null);
      }
      
      const focusEnd = performance.now();
      logger.debug('VisualEditorModal - handleFieldFocus END:', { duration: `${(focusEnd - focusStart).toFixed(2)}ms` });
    }, 0);
  };

  // Handle field double-click - zoom to 200% and center on field
  const handleFieldDoubleClick = (geometry) => {
    logger.debug('VisualEditorModal - handleFieldDoubleClick called with geometry:', geometry);
    
    if (geometry && imageRef.current && imageContainerRef.current) {
      // First switch to the correct page if needed
      if (geometry.page !== undefined && pageIds.length > 0) {
        const pageIndex = geometry.page - 1;
        if (pageIndex >= 0 && pageIndex < pageIds.length) {
          const targetPageId = pageIds[pageIndex];
          if (targetPageId !== currentPage) {
            setCurrentPage(targetPageId);
          }
        }
      }

      // Set zoom to 200%
      const targetZoom = 2.0;
      setZoomLevel(targetZoom);
      
      // Calculate pan offset to center the field
      setTimeout(() => {
        if (imageRef.current && imageContainerRef.current) {
          const img = imageRef.current;
          const container = imageContainerRef.current;
          
          // Get image and container dimensions
          const imgRect = img.getBoundingClientRect();
          const containerRect = container.getBoundingClientRect();
          
          const imageWidth = img.width || img.naturalWidth;
          const imageHeight = img.height || img.naturalHeight;
          const offsetX = imgRect.left - containerRect.left;
          const offsetY = imgRect.top - containerRect.top;
          
          // Get bounding box coordinates
          const bbox = geometry.boundingBox;
          
          if (bbox) {
            const { left, top, width, height } = bbox;
            
            // Calculate field center in image coordinates
            const fieldCenterX = (left + width / 2) * imageWidth + offsetX;
            const fieldCenterY = (top + height / 2) * imageHeight + offsetY;
            
            // Calculate viewport center
            const viewportCenterX = containerRect.width / 2;
            const viewportCenterY = containerRect.height / 2;
            
            // Calculate image center
            const imageCenterX = offsetX + imageWidth / 2;
            const imageCenterY = offsetY + imageHeight / 2;
            
            // Calculate relative position of field center from image center
            const relativeX = fieldCenterX - imageCenterX;
            const relativeY = fieldCenterY - imageCenterY;
            
            // At 200% zoom, calculate where the field center will be
            const scaledRelativeX = relativeX * targetZoom;
            const scaledRelativeY = relativeY * targetZoom;
            
            // Calculate required pan offset to center the field in viewport
            const requiredPanX = viewportCenterX - (imageCenterX + scaledRelativeX);
            const requiredPanY = viewportCenterY - (imageCenterY + scaledRelativeY);
            
            logger.debug('VisualEditorModal - Auto-centering calculation:', {
              fieldCenterX, fieldCenterY,
              viewportCenterX, viewportCenterY,
              imageCenterX, imageCenterY,
              relativeX, relativeY,
              scaledRelativeX, scaledRelativeY,
              requiredPanX, requiredPanY
            });
            
            setPanOffset({ x: requiredPanX, y: requiredPanY });
          }
        }
      }, 100); // Small delay to allow zoom to take effect
      
      // Also set the active geometry for bounding box display
      setActiveFieldGeometry(geometry);
    }
  };

  // Create carousel items from page images
  const carouselItems = pageIds.map((pageId) => ({
    id: pageId,
    content: (
      <div 
        ref={pageId === currentPage ? imageContainerRef : null}
        style={{ 
          position: 'relative', 
          width: '100%', 
          height: '100%', 
          display: 'flex', 
          justifyContent: 'center',
          overflow: 'hidden',
          cursor: zoomLevel > 1 ? 'grab' : 'default'
        }}
        onWheel={handleWheel}
      >
        {pageImages[pageId] ? (
          <>
            <img
              ref={pageId === currentPage ? imageRef : null}
              src={pageImages[pageId]}
              alt={`Page ${pageId}`}
              style={{ 
                maxWidth: 'none',
                maxHeight: 'none',
                width: 'auto',
                height: 'auto',
                transform: `scale(${zoomLevel}) translate(${panOffset.x / zoomLevel}px, ${panOffset.y / zoomLevel}px)`,
                transformOrigin: 'center center',
                transition: 'transform 0.1s ease-out'
              }}
              onError={(e) => {
                logger.error(`Error loading image for page ${pageId}:`, e);
                // Fallback image for error state
                const fallbackImage =
                  'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAwIiBoZWlnaHQ9IjIwMCIgeG1sbnM9Imh0dHA6' +
                  'Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMjAwIiBoZWlnaHQ9IjIwMCIgZmlsbD0iI2Yw' +
                  'ZjBmMCIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBmb250LWZhbWlseT0iQXJpYWwiIGZvbnQtc2l6ZT0iMjAi' +
                  'IHRleHQtYW5jaG9yPSJtaWRkbGUiIGZpbGw9IiM5OTkiPkltYWdlIGxvYWQgZXJyb3I8L3RleHQ+PC9zdmc+';
                e.target.src = fallbackImage;
              }}
            />
            {activeFieldGeometry && (
              <BoundingBox
                box={activeFieldGeometry}
                page={currentPage} 
                currentPage={currentPage}
                imageRef={imageRef}
                zoomLevel={zoomLevel}
                panOffset={panOffset}
              />
            )}
          </>
        ) : (
          <Box padding="xl" textAlign="center">
            <Spinner />
            <div>Loading image...</div>
          </Box>
        )}
      </div>
    ),
  }));

  return (
    <Modal
      onDismiss={onDismiss}
      visible={visible}
      header="Visual Document Editor"
      size="max"
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button 
              variant="link" 
              onClick={() => {
                const dismissStart = performance.now();
                logger.debug('🚪 CANCEL BUTTON - onDismiss starting...', { timestamp: dismissStart });
                onDismiss();
                const dismissEnd = performance.now();
                logger.debug('✅ CANCEL BUTTON - onDismiss completed:', { duration: `${(dismissEnd - dismissStart).toFixed(2)}ms` });
              }}
            >
              Cancel
            </Button>
            <Button 
              variant="primary" 
              onClick={() => {
                const dismissStart = performance.now();
                logger.debug('🚪 DONE BUTTON - onDismiss starting...', { timestamp: dismissStart });
                onDismiss();
                const dismissEnd = performance.now();
                logger.debug('✅ DONE BUTTON - onDismiss completed:', { duration: `${(dismissEnd - dismissStart).toFixed(2)}ms` });
              }}
            >
              Done
            </Button>
          </SpaceBetween>
        </Box>
      }
    >
      <div
        style={{
          display: 'flex',
          flexDirection: 'row',
          gap: '20px',
          height: 'calc(100vh - 200px)',
          maxHeight: '1000px',
          minHeight: '1000px',
          width: '100%',
        }}
      >
        {/* Left side - Page images carousel - Fixed height, non-scrollable */}
        <div
          style={{
            width: '50%',
            minWidth: '50%',
            maxWidth: '50%',
            height: '100%',
            display: 'flex',
            flexDirection: 'column',
            flex: '0 0 50%',
          }}
        >
          <Container
            header={<Header variant="h3">Document Pages ({pageIds.length})</Header>}
            style={{
              height: '100%',
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
              flex: 1,
            }}
          >
            {(() => {
              if (loadingImages) {
                return (
                  <Box padding="xl" textAlign="center">
                    <Spinner />
                    <div>Loading page images...</div>
                  </Box>
                );
              }
              if (carouselItems.length > 0) {
                return (
                  <Box style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>


                    {/* Display current page */}
                    {carouselItems.find((item) => item.id === currentPage)?.content}

                    {/* Simple navigation */}
                    <Box
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        position: 'absolute',
                        width: '100%',
                        top: '50%',
                        transform: 'translateY(-50%)',
                        pointerEvents: 'none',
                      }}
                    >
                      <Button
                        iconName="angle-left"
                        variant="icon"
                        onClick={() => {
                          const currentIndex = pageIds.indexOf(currentPage);
                          if (currentIndex > 0) {
                            setCurrentPage(pageIds[currentIndex - 1]);
                            setActiveFieldGeometry(null);
                          }
                        }}
                        disabled={pageIds.indexOf(currentPage) === 0}
                        style={{ pointerEvents: 'auto' }}
                      />
                      <Button
                        iconName="angle-right"
                        variant="icon"
                        onClick={() => {
                          const currentIndex = pageIds.indexOf(currentPage);
                          if (currentIndex < pageIds.length - 1) {
                            setCurrentPage(pageIds[currentIndex + 1]);
                            setActiveFieldGeometry(null);
                          }
                        }}
                        disabled={pageIds.indexOf(currentPage) === pageIds.length - 1}
                        style={{ pointerEvents: 'auto' }}
                      />
                    </Box>

                    {/* Page indicator and Controls */}
                    <Box
                      style={{
                        position: 'absolute',
                        bottom: '10px',
                        width: '100%',
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        gap: '8px'
                      }}
                    >
                      {/* Page indicator */}
                      <Box
                        style={{
                          backgroundColor: 'rgba(255, 255, 255, 0.8)',
                          padding: '4px 8px',
                          borderRadius: '4px',
                        }}
                      >
                        Page {pageIds.indexOf(currentPage) + 1} of {pageIds.length}
                      </Box>
                      
                      {/* Zoom and Pan Controls */}
                      <Box
                        style={{
                          backgroundColor: 'rgba(255, 255, 255, 0.9)',
                          padding: '4px 8px',
                          borderRadius: '4px',
                          boxShadow: '0 1px 4px rgba(0, 0, 0, 0.1)',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '6px',
                          fontSize: '12px'
                        }}
                      >
                        <span style={{ fontWeight: 'bold' }}>Zoom:</span>
                        <span
                          onClick={handleZoomOut}
                          onKeyDown={(e) => e.key === 'Enter' && handleZoomOut()}
                          role="button"
                          tabIndex={0}
                          style={{
                            cursor: zoomLevel <= 0.25 ? 'not-allowed' : 'pointer',
                            opacity: zoomLevel <= 0.25 ? 0.5 : 1,
                            fontSize: '14px',
                            fontWeight: 'bold',
                            userSelect: 'none',
                            padding: '2px 4px'
                          }}
                          title="Zoom Out"
                        >
                          −
                        </span>
                        <span style={{ fontSize: '12px', minWidth: '30px', textAlign: 'center' }}>
                          {Math.round(zoomLevel * 100)}%
                        </span>
                        <span
                          onClick={handleZoomIn}
                          onKeyDown={(e) => e.key === 'Enter' && handleZoomIn()}
                          role="button"
                          tabIndex={0}
                          style={{
                            cursor: zoomLevel >= 4 ? 'not-allowed' : 'pointer',
                            opacity: zoomLevel >= 4 ? 0.5 : 1,
                            fontSize: '14px',
                            fontWeight: 'bold',
                            userSelect: 'none',
                            padding: '2px 4px'
                          }}
                          title="Zoom In"
                        >
                          +
                        </span>
                        <span style={{ fontWeight: 'bold', marginLeft: '4px' }}>Pan:</span>
                        <span
                          onClick={handlePanLeft}
                          onKeyDown={(e) => e.key === 'Enter' && handlePanLeft()}
                          role="button"
                          tabIndex={0}
                          style={{
                            cursor: zoomLevel <= 1 ? 'not-allowed' : 'pointer',
                            opacity: zoomLevel <= 1 ? 0.5 : 1,
                            fontSize: '14px',
                            userSelect: 'none',
                            padding: '2px 3px'
                          }}
                          title="Pan Left"
                        >
                          ←
                        </span>
                        <span
                          onClick={handlePanRight}
                          onKeyDown={(e) => e.key === 'Enter' && handlePanRight()}
                          role="button"
                          tabIndex={0}
                          style={{
                            cursor: zoomLevel <= 1 ? 'not-allowed' : 'pointer',
                            opacity: zoomLevel <= 1 ? 0.5 : 1,
                            fontSize: '14px',
                            userSelect: 'none',
                            padding: '2px 3px'
                          }}
                          title="Pan Right"
                        >
                          →
                        </span>
                        <span
                          onClick={handlePanUp}
                          onKeyDown={(e) => e.key === 'Enter' && handlePanUp()}
                          role="button"
                          tabIndex={0}
                          style={{
                            cursor: zoomLevel <= 1 ? 'not-allowed' : 'pointer',
                            opacity: zoomLevel <= 1 ? 0.5 : 1,
                            fontSize: '14px',
                            userSelect: 'none',
                            padding: '2px 3px'
                          }}
                          title="Pan Up"
                        >
                          ↑
                        </span>
                        <span
                          onClick={handlePanDown}
                          onKeyDown={(e) => e.key === 'Enter' && handlePanDown()}
                          role="button"
                          tabIndex={0}
                          style={{
                            cursor: zoomLevel <= 1 ? 'not-allowed' : 'pointer',
                            opacity: zoomLevel <= 1 ? 0.5 : 1,
                            fontSize: '14px',
                            userSelect: 'none',
                            padding: '2px 3px'
                          }}
                          title="Pan Down"
                        >
                          ↓
                        </span>
                        <span
                          onClick={handleResetView}
                          onKeyDown={(e) => e.key === 'Enter' && handleResetView()}
                          role="button"
                          tabIndex={0}
                          style={{
                            cursor: 'pointer',
                            fontSize: '12px',
                            userSelect: 'none',
                            padding: '2px 3px',
                            marginLeft: '2px'
                          }}
                          title="Reset View"
                        >
                          ⟲
                        </span>
                      </Box>
                    </Box>
                  </Box>
                );
              }
              return (
                <Box padding="xl" textAlign="center">
                  No page images available
                </Box>
              );
            })()}
          </Container>
        </div>

        {/* Right side - Form fields - Independently scrollable */}
        <div
          style={{
            width: '50%',
            minWidth: '50%',
            maxWidth: '50%',
            height: '100%',
            display: 'flex',
            flexDirection: 'column',
            flex: '0 0 50%',
            overflow: 'hidden',
          }}
        >
          <Container
            header={<Header variant="h3">Document Data</Header>}
            style={{
              height: '100%',
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
              flex: 1,
            }}
          >
            <div
              style={{
                flex: 1,
                overflowY: 'auto',
                overflowX: 'hidden',
                padding: '16px',
                boxSizing: 'border-box',
                maxHeight: '800px',
                minHeight: '600px',
              }}
            >
              <Box style={{ minHeight: 'fit-content' }}>
                {inferenceResult ? (
                  <FormFieldRenderer
                    fieldKey="Document Data"
                    value={inferenceResult}
                    onChange={(newValue) => {
                      if (!isReadOnly) {
                        // Update local state immediately for responsive UI
                        const updatedData = { ...localJsonData };
                        if (updatedData.inference_result) {
                          updatedData.inference_result = newValue;
                        } else if (updatedData.inferenceResult) {
                          updatedData.inferenceResult = newValue;
                        } else {
                          // If there's no inference_result field, update the entire object
                          Object.keys(updatedData).forEach((key) => {
                            delete updatedData[key];
                          });
                          Object.keys(newValue).forEach((key) => {
                            updatedData[key] = newValue[key];
                          });
                        }

                        // Update local state immediately for responsive UI
                        setLocalJsonData(updatedData);
                        logger.debug('💨 LOCAL UPDATE - Updated local state immediately');

                        // Debounce expensive parent call
                        if (onChange) {
                          const jsonStart = performance.now();
                          logger.debug('🔄 DEBOUNCED - JSON stringify starting...');
                          
                          try {
                            const jsonString = JSON.stringify(updatedData, null, 2);
                            const jsonEnd = performance.now();
                            logger.debug('✅ DEBOUNCED - JSON stringify completed:', { 
                              duration: `${(jsonEnd - jsonStart).toFixed(2)}ms`,
                              jsonLength: jsonString.length 
                            });
                            
                            // Call debounced parent onChange
                            debouncedParentOnChange(jsonString);
                          } catch (error) {
                            logger.error('Error stringifying JSON:', error);
                          }
                        }
                      }
                    }}
                    isReadOnly={isReadOnly}
                    onFieldFocus={handleFieldFocus}
                    onFieldDoubleClick={handleFieldDoubleClick}
                    path={[]}
                    explainabilityInfo={jsonData?.explainability_info}
                  />
                ) : (
                  <Box padding="xl" textAlign="center">
                    No data available
                  </Box>
                )}
              </Box>
            </div>
          </Container>
        </div>
      </div>
    </Modal>
  );
};

export default VisualEditorModal;
