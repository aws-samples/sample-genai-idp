// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import React, { useState, useEffect } from 'react';
import {
  Box,
  ColumnLayout,
  Container,
  SpaceBetween,
  Button,
  Header,
  Table,
  ExpandableSection,
  StatusIndicator,
} from '@cloudscape-design/components';
import { generateClient } from 'aws-amplify/api';
import useConfigurationVersions from '../../hooks/use-configuration-versions';
import { formatConfigVersionLink } from '../test-studio/utils/configVersionUtils';
import type { ConfigVersion } from '../test-studio/utils/configVersionUtils';
import { ConsoleLogger } from 'aws-amplify/utils';
import './DocumentPanel.css';
import DocumentViewers from '../document-viewers/DocumentViewers';
import SectionsPanel from '../sections-panel';
import PagesPanel from '../pages-panel';
import ChatPanel from '../chat-panel';
import useConfiguration from '../../hooks/use-configuration';
import usePricing from '../../hooks/use-pricing';
import useUserRole from '../../hooks/use-user-role';
import { getDocumentConfidenceAlertCount } from '../common/confidence-alerts-utils';
import { renderHitlStatus } from '../common/hitl-status-renderer';
import StepFunctionFlowViewer from '../step-function-flow/StepFunctionFlowViewer';
import TroubleshootModal from './TroubleshootModal';
import claimReviewMutation from '../../graphql/mutations/claimReview';
// Uncomment the line below to enable debugging
// import { debugDocumentStructure } from '../common/debug-utils';

interface MappedDocument {
  objectKey: string;
  objectStatus: string;
  initialEventTime?: string;
  completionTime?: string;
  duration?: string;
  configVersion?: string;
  pageCount?: number;
  evaluationStatus?: string;
  evaluationReportUri?: string;
  summaryReportUri?: string;
  ruleValidationResultUri?: string;
  sections?: Record<string, unknown>[];
  pages?: Record<string, unknown>[];
  metering?: Record<string, Record<string, unknown>> | null;
  executionArn?: string;
  hitlStatus?: string;
  hitlTriggered?: boolean;
  hitlCompleted?: boolean;
  hitlReviewOwner?: string;
  hitlReviewOwnerEmail?: string;
  hitlReviewedBy?: string;
  hitlReviewedByEmail?: string;
  mergedConfig?: Record<string, unknown>;
  [key: string]: unknown;
}

interface MeteringRowItem {
  context: string;
  serviceApi: string;
  unit: string;
  value: string;
  unitCost: string;
  cost: string;
  costValue: number;
  isTotal: boolean;
  isSubtotal: boolean;
  note?: string;
}

interface PricingUnit {
  name: string;
  price: number;
}

interface PricingItem {
  name: string;
  units: PricingUnit[];
}

interface PricingData {
  pricing: PricingItem[];
}

interface PricingLookup {
  [serviceName: string]: {
    [unitName: string]: number;
  };
}

interface ConfidenceAlertsSectionProps {
  sections: Record<string, unknown>[] | undefined;
  mergedConfig: Record<string, unknown> | undefined;
}

interface MeteringTableProps {
  meteringData: Record<string, Record<string, unknown>> | null;
  preCalculatedTotals?: { totalCost: number; costPerPage: number };
}

interface MeteringExpandableSectionProps {
  meteringData: Record<string, Record<string, unknown>> | null;
  documentItem: MappedDocument;
}

interface DocumentAttributesProps {
  item: MappedDocument;
  versions: ConfigVersion[];
  setToolsOpen?: (open: boolean) => void;
  getDocumentDetailsFromIds?: (ids: string[]) => Promise<unknown>;
}

interface DocumentPanelProps {
  item: MappedDocument;
  setToolsOpen?: (open: boolean) => void;
  getDocumentDetailsFromIds?: (ids: string[]) => Promise<unknown>;
  onDelete?: (() => void) | null;
  onReprocess?: (() => void) | null;
  onAbort?: (() => void) | null;
}

interface TroubleshootJobData {
  jobId: string;
  status: string;
  result: unknown;
  agentMessages: unknown;
  error: string | null;
  timestamp: number;
  documentKey: string;
}

const client = generateClient();
const logger = new ConsoleLogger('DocumentPanel');

// Component to display confidence alerts count only
const ConfidenceAlertsSection = ({ sections, mergedConfig }: ConfidenceAlertsSectionProps): React.JSX.Element => {
  // Uncomment the line below to enable debugging
  // debugDocumentStructure({ sections, mergedConfig });

  if (!sections || !Array.isArray(sections) || !mergedConfig) {
    return <StatusIndicator type="success">0</StatusIndicator>;
  }

  const totalAlertCount = getDocumentConfidenceAlertCount(sections, mergedConfig);

  if (totalAlertCount === 0) {
    return <StatusIndicator type="success">0</StatusIndicator>;
  }

  return <StatusIndicator type="warning">{totalAlertCount}</StatusIndicator>;
};

// Helper function to parse serviceApi key into context and service
const parseServiceApiKey = (serviceApiKey: string): { context: string; serviceApi: string } => {
  const parts = serviceApiKey.split('/');
  if (parts.length >= 3) {
    const context = parts[0];
    const serviceApi = parts.slice(1).join('/');
    return { context, serviceApi };
  }
  // Fallback for keys that don't follow the new format (less than 3 parts) - set context to ''
  return { context: '', serviceApi: serviceApiKey };
};

// Helper function to format cost cells
const formatCostCell = (rowItem: MeteringRowItem): React.JSX.Element | string => {
  if (rowItem.isTotal) {
    return <Box fontWeight="bold">{`${rowItem.note}: ${rowItem.cost}`}</Box>;
  }
  if (rowItem.isSubtotal) {
    return <Box fontWeight="bold" color="text-body-secondary">{`${rowItem.note}: ${rowItem.cost}`}</Box>;
  }
  return rowItem.cost;
};

// Component to display metering information in a table
const MeteringTable = ({ meteringData, preCalculatedTotals }: MeteringTableProps): React.JSX.Element | null => {
  // Use usePricing hook to get pricing data from the new separate pricing config
  const { pricing, loading } = usePricing();
  const [pricingData, setPricingData] = useState<PricingLookup>({});
  // We no longer use a default unit cost, showing "None" instead

  useEffect(() => {
    if (pricing && (pricing as PricingData).pricing) {
      // Convert pricing array to lookup object for easier access
      const pricingLookup: PricingLookup = {};
      (pricing as PricingData).pricing.forEach((item) => {
        if (item.name && item.units) {
          pricingLookup[item.name] = {};
          item.units.forEach((unitItem) => {
            if (unitItem.name && unitItem.price !== undefined) {
              // Ensure price is stored as a number
              pricingLookup[item.name][unitItem.name] = Number(unitItem.price);
            }
          });
        }
      });
      setPricingData(pricingLookup);
      logger.debug('Pricing data initialized:', pricingLookup);
    }
  }, [pricing]);

  if (!meteringData) {
    return null;
  }

  if (loading) {
    return <Box>Loading pricing data...</Box>;
  }

  // Transform metering data into table rows with context parsing
  const rawTableItems: MeteringRowItem[] = [];
  const contextTotals: Record<string, number> = {};
  let totalCost = 0;

  Object.entries(meteringData).forEach(([originalServiceApiKey, metrics]) => {
    const { context, serviceApi } = parseServiceApiKey(originalServiceApiKey);

    Object.entries(metrics as Record<string, unknown>).forEach(([unit, value]) => {
      const numericValue = Number(value);

      // Look up the unit price from the pricing data using the parsed serviceApi
      let unitPrice: number | null = null;
      let unitPriceDisplayValue = 'None';
      let cost = 0;
      if (pricingData[serviceApi] && pricingData[serviceApi][unit] !== undefined) {
        unitPrice = Number(pricingData[serviceApi][unit]);
        if (!Number.isNaN(unitPrice)) {
          unitPriceDisplayValue = `$${unitPrice}`;
          cost = numericValue * unitPrice;
          totalCost += cost;

          // Track context totals
          if (!contextTotals[context]) {
            contextTotals[context] = 0;
          }
          contextTotals[context] += cost;

          logger.debug(`Found price for ${serviceApi}/${unit}: ${unitPriceDisplayValue}`);
        } else {
          logger.warn(`Invalid price for ${serviceApi}/${unit}, using None`);
        }
      } else {
        logger.debug(`No price found for ${serviceApi}/${unit}, using None`);
      }

      rawTableItems.push({
        context,
        serviceApi,
        unit,
        value: String(numericValue),
        unitCost: unitPriceDisplayValue,
        cost: unitPrice !== null ? `$${cost.toFixed(4)}` : 'N/A',
        costValue: cost,
        isTotal: false,
        isSubtotal: false,
      });
    });
  });

  // Group items by context and add subtotals
  const tableItems: MeteringRowItem[] = [];
  const contextGroups: Record<string, MeteringRowItem[]> = {};

  // Group raw items by context
  rawTableItems.forEach((item) => {
    if (!contextGroups[item.context]) {
      contextGroups[item.context] = [];
    }
    contextGroups[item.context].push(item);
  });

  // Sort contexts in specific order: OCR, Classification, Extraction, Summarization
  const contextOrder = ['BDAProject', 'OCR', 'Classification', 'Extraction', 'Summarization'];
  const sortedContexts = Object.keys(contextGroups).sort((a, b) => {
    const aIndex = contextOrder.indexOf(a);
    const bIndex = contextOrder.indexOf(b);

    // If both contexts are in the predefined order, sort by their position
    if (aIndex !== -1 && bIndex !== -1) {
      return aIndex - bIndex;
    }

    // If only one context is in the predefined order, it comes first
    if (aIndex !== -1) return -1;
    if (bIndex !== -1) return 1;

    // If neither context is in the predefined order, sort alphabetically
    return a.localeCompare(b);
  });

  sortedContexts.forEach((context) => {
    // Add all items for this context
    tableItems.push(...contextGroups[context]);

    // Add subtotal row for this context
    const contextTotal = contextTotals[context] || 0;
    tableItems.push({
      context: '',
      serviceApi: '',
      unit: '',
      value: '',
      unitCost: '',
      cost: `$${contextTotal.toFixed(4)}`,
      costValue: contextTotal,
      isTotal: false,
      isSubtotal: true,
      note: `${context} Subtotal`,
    });
  });

  // Use preCalculatedTotals if provided, otherwise calculate locally
  const finalTotalCost = preCalculatedTotals ? preCalculatedTotals.totalCost : totalCost;

  // Add overall total row
  tableItems.push({
    context: '',
    serviceApi: '',
    unit: '',
    value: '',
    unitCost: '',
    cost: `$${finalTotalCost.toFixed(4)}`,
    costValue: finalTotalCost,
    isTotal: true,
    isSubtotal: false,
    note: 'Total',
  });

  return (
    <Table
      columnDefinitions={[
        {
          id: 'context',
          header: 'Context',
          cell: (rowItem: MeteringRowItem) => rowItem.context,
        },
        {
          id: 'serviceApi',
          header: 'Service/Api',
          cell: (rowItem: MeteringRowItem) => rowItem.serviceApi,
        },
        {
          id: 'unit',
          header: 'Unit',
          cell: (rowItem: MeteringRowItem) => rowItem.unit,
        },
        {
          id: 'value',
          header: 'Value',
          cell: (rowItem: MeteringRowItem) => rowItem.value,
        },
        {
          id: 'unitCost',
          header: 'Unit Cost',
          cell: (rowItem: MeteringRowItem) => rowItem.unitCost,
        },
        {
          id: 'cost',
          header: 'Estimated Cost',
          cell: formatCostCell,
        },
      ]}
      items={tableItems}
      loadingText="Loading resources"
      sortingDisabled
      wrapLines
      stripedRows
      empty={
        <Box textAlign="center" color="inherit">
          <b>No metering data</b>
          <Box padding={{ bottom: 's' }} variant="p" color="inherit">
            No metering data is available for this document.
          </Box>
        </Box>
      }
    />
  );
};

// Helper function to calculate total costs using pricing data
const calculateTotalCosts = (
  meteringData: Record<string, Record<string, unknown>> | null,
  documentItem: MappedDocument,
  pricingData: PricingLookup | null,
): { totalCost: number; costPerPage: number } => {
  if (!meteringData) return { totalCost: 0, costPerPage: 0 };

  let totalCost = 0;

  if (pricingData) {
    Object.entries(meteringData).forEach(([originalServiceApiKey, metrics]) => {
      // Parse the serviceApi key to remove context prefix
      const { serviceApi } = parseServiceApiKey(originalServiceApiKey);

      Object.entries(metrics).forEach(([unit, value]) => {
        const numericValue = Number(value);
        if (pricingData[serviceApi] && pricingData[serviceApi][unit] !== undefined) {
          const unitPrice = Number(pricingData[serviceApi][unit]);
          if (!Number.isNaN(unitPrice)) {
            totalCost += numericValue * unitPrice;
          }
        }
      });
    });
  }

  const numPages = (documentItem && documentItem.pageCount) || 1;
  const costPerPage = totalCost / numPages;

  return { totalCost, costPerPage };
};

// Expandable section containing the metering table
const MeteringExpandableSection = ({ meteringData, documentItem }: MeteringExpandableSectionProps): React.JSX.Element => {
  const [expanded, setExpanded] = useState(false);
  const { pricing } = usePricing();
  const [pricingData, setPricingData] = useState<PricingLookup | null>(null);

  // Convert pricing data to lookup format
  useEffect(() => {
    if (pricing && (pricing as PricingData).pricing) {
      const pricingLookup: PricingLookup = {};
      (pricing as PricingData).pricing.forEach((item) => {
        if (item.name && item.units) {
          pricingLookup[item.name] = {};
          item.units.forEach((unitItem) => {
            if (unitItem.name && unitItem.price !== undefined) {
              pricingLookup[item.name][unitItem.name] = Number(unitItem.price);
            }
          });
        }
      });
      setPricingData(pricingLookup);
    }
  }, [pricing]);

  // Calculate the cost per page for the header
  const { totalCost, costPerPage } = calculateTotalCosts(meteringData, documentItem, pricingData);

  return (
    <Box margin={{ top: 'l', bottom: 'm' }}>
      <ExpandableSection
        variant="container"
        headerText={`Estimated Cost (per page: $${costPerPage.toFixed(4)})`}
        expanded={expanded}
        onChange={({ detail }) => setExpanded(detail.expanded)}
      >
        <div style={{ width: '100%' }}>
          <MeteringTable meteringData={meteringData} preCalculatedTotals={{ totalCost, costPerPage }} />
        </div>
      </ExpandableSection>
    </Box>
  );
};

const DocumentAttributes = ({ item, versions }: DocumentAttributesProps): React.JSX.Element => {
  return (
    <Container>
      <ColumnLayout columns={8} variant="text-grid">
        <SpaceBetween size="xs">
          <div>
            <Box margin={{ bottom: 'xxxs' }} color="text-label">
              <strong>Document ID</strong>
            </Box>
            <div>{item.objectKey}</div>
          </div>
        </SpaceBetween>

        <SpaceBetween size="xs">
          <div>
            <Box margin={{ bottom: 'xxxs' }} color="text-label">
              <strong>Status</strong>
            </Box>
            <div>{item.objectStatus}</div>
          </div>
        </SpaceBetween>

        <SpaceBetween size="xs">
          <div>
            <Box margin={{ bottom: 'xxxs' }} color="text-label">
              <strong>Submitted</strong>
            </Box>
            <div>{item.initialEventTime}</div>
          </div>
        </SpaceBetween>

        <SpaceBetween size="xs">
          <div>
            <Box margin={{ bottom: 'xxxs' }} color="text-label">
              <strong>Completed</strong>
            </Box>
            <div>{item.completionTime}</div>
          </div>
        </SpaceBetween>

        <SpaceBetween size="xs">
          <div>
            <Box margin={{ bottom: 'xxxs' }} color="text-label">
              <strong>Duration</strong>
            </Box>
            <div>{item.duration}</div>
          </div>
        </SpaceBetween>

        <SpaceBetween size="xs">
          <div>
            <Box margin={{ bottom: 'xxxs' }} color="text-label">
              <strong>Config Version</strong>
            </Box>
            <div>{formatConfigVersionLink(item.configVersion, versions)}</div>
          </div>
        </SpaceBetween>

        <SpaceBetween size="xs">
          <div>
            <Box margin={{ bottom: 'xxxs' }} color="text-label">
              <strong>Page Count</strong>
            </Box>
            <div>{item.pageCount || 0}</div>
          </div>
        </SpaceBetween>

        <SpaceBetween size="xs">
          <div>
            <Box margin={{ bottom: 'xxxs' }} color="text-label">
              <strong>Evaluation</strong>
            </Box>
            <div>{item.evaluationStatus || 'N/A'}</div>
          </div>
        </SpaceBetween>

        <SpaceBetween size="xs">
          <div>
            <Box margin={{ bottom: 'xxxs' }} color="text-label">
              <strong>Review Status</strong>
            </Box>
            <div>{renderHitlStatus(item)}</div>
          </div>
        </SpaceBetween>

        <SpaceBetween size="xs">
          <div>
            <Box margin={{ bottom: 'xxxs' }} color="text-label">
              <strong>Review Owner</strong>
            </Box>
            <div>{item.hitlReviewOwnerEmail || item.hitlReviewOwner || '-'}</div>
          </div>
        </SpaceBetween>

        <SpaceBetween size="xs">
          <div>
            <Box margin={{ bottom: 'xxxs' }} color="text-label">
              <strong>Review Completed By</strong>
            </Box>
            <div>{item.hitlReviewedByEmail || item.hitlReviewedBy || '-'}</div>
          </div>
        </SpaceBetween>

        <SpaceBetween size="xs">
          <div>
            <Box margin={{ bottom: 'xxxs' }} color="text-label">
              <strong>Confidence Alerts</strong>
            </Box>
            <ConfidenceAlertsSection sections={item.sections} mergedConfig={item.mergedConfig} />
          </div>
        </SpaceBetween>

        <SpaceBetween size="xs">
          <div>
            <Box margin={{ bottom: 'xxxs' }} color="text-label">
              <strong>Summary</strong>
            </Box>
            <div>{item.summaryReportUri ? 'Available' : 'N/A'}</div>
          </div>
        </SpaceBetween>
      </ColumnLayout>
    </Container>
  );
};

// Statuses that can be aborted
const ABORTABLE_STATUSES = [
  'QUEUED',
  'RUNNING',
  'OCR',
  'CLASSIFYING',
  'EXTRACTING',
  'ASSESSING',
  'POSTPROCESSING',
  'HITL_IN_PROGRESS',
  'SUMMARIZING',
  'EVALUATING',
];

export const DocumentPanel = ({
  item,
  setToolsOpen,
  getDocumentDetailsFromIds,
  onDelete,
  onReprocess,
  onAbort,
}: DocumentPanelProps): React.JSX.Element => {
  const { versions } = useConfigurationVersions();
  logger.debug('DocumentPanel item', item);

  // State for Step Function flow viewer
  const [isFlowViewerVisible, setIsFlowViewerVisible] = useState(false);
  // State for Troubleshoot modal
  const [isTroubleshootModalVisible, setIsTroubleshootModalVisible] = useState(false);
  // State for tracking troubleshoot jobs per document
  const [troubleshootJobs, setTroubleshootJobs] = useState<Record<string, TroubleshootJobData>>({});
  // State for Start Review button
  const [isClaimingReview, setIsClaimingReview] = useState(false);
  // Local state for document item to enable real-time updates
  const [localItem, setLocalItem] = useState(item);

  // Update local item when prop changes
  useEffect(() => {
    setLocalItem(item);
  }, [item]);

  // Fetch active configuration for dynamic confidence threshold (used by sections panel, etc.)
  const { mergedConfig } = useConfiguration();
  // Fetch the specific config version that was used to process this document (for flow viewer)
  const { mergedConfig: documentVersionConfig } = useConfiguration(localItem?.configVersion || 'default');
  const { isReviewer } = useUserRole();

  // Check if document can be aborted
  const canAbort = ABORTABLE_STATUSES.includes(localItem?.objectStatus);

  // Check if Start Review button should be shown
  const hasReviewOwner = localItem?.hitlReviewOwner || localItem?.hitlReviewOwnerEmail;
  const hitlStatusLower = localItem?.hitlStatus?.toLowerCase().replace(/\s+/g, '') || '';
  const isHitlSkipped = hitlStatusLower === 'skipped' || hitlStatusLower === 'reviewskipped';
  const isHitlCompleted = hitlStatusLower === 'completed' || hitlStatusLower === 'reviewcompleted';
  const hasPendingHITL = localItem?.hitlTriggered && !isHitlCompleted && !isHitlSkipped;
  const showStartReview = isReviewer && hasPendingHITL && !hasReviewOwner;

  // Handle Start Review button click
  const handleStartReview = async () => {
    setIsClaimingReview(true);
    try {
      const result = await client.graphql({
        query: claimReviewMutation as unknown as string,
        variables: { objectKey: localItem.objectKey },
      });

      logger.info('Review claimed successfully:', result);

      // Update local item immediately with the response data
      const claimedData = (result as unknown as Record<string, Record<string, Record<string, unknown>>>).data.claimReview;
      setLocalItem((prev) => ({
        ...prev,
        hitlReviewOwner: claimedData.HITLReviewOwner as string,
        hitlReviewOwnerEmail: claimedData.HITLReviewOwnerEmail as string,
        hitlStatus: claimedData.HITLStatus as string,
      }));

      // Also refresh document details in the background
      if (getDocumentDetailsFromIds) {
        await getDocumentDetailsFromIds([localItem.objectKey]);
      }
    } catch (error) {
      logger.error('Failed to claim review:', error);
      alert(`Failed to start review: ${(error as Error).message || 'Unknown error'}`);
    } finally {
      setIsClaimingReview(false);
    }
  };

  // Create enhanced item with configuration
  const enhancedItem = {
    ...localItem,
    mergedConfig,
  };

  return (
    <SpaceBetween size="s">
      <Container
        header={
          <Header
            variant="h2"
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                {showStartReview && (
                  <Button
                    iconName="user-profile"
                    variant="primary"
                    onClick={handleStartReview}
                    loading={isClaimingReview}
                    disabled={isClaimingReview}
                  >
                    Start Review
                  </Button>
                )}
                <Button
                  iconName="gen-ai"
                  variant="normal"
                  onClick={() => {
                    logger.info('Opening troubleshoot modal for document:', localItem.objectKey);
                    setIsTroubleshootModalVisible(true);
                  }}
                >
                  Troubleshoot
                </Button>
                {localItem?.executionArn && (
                  <Button
                    iconName="status-positive"
                    variant={isFlowViewerVisible ? 'primary' : 'normal'}
                    onClick={() => {
                      console.log('Execution ARN:', localItem.executionArn);
                      logger.info('Opening flow viewer with execution ARN:', localItem.executionArn);
                      setIsFlowViewerVisible(true);
                    }}
                  >
                    View Processing Flow
                  </Button>
                )}
                {onAbort && canAbort && (
                  <Button iconName="status-stopped" variant="normal" onClick={onAbort}>
                    Abort
                  </Button>
                )}
                {onReprocess && (
                  <Button iconName="redo" variant="normal" onClick={onReprocess}>
                    Reprocess
                  </Button>
                )}
                {onDelete && (
                  <Button iconName="remove" variant="normal" onClick={onDelete}>
                    Delete
                  </Button>
                )}
              </SpaceBetween>
            }
          >
            Document Details
          </Header>
        }
      >
        <SpaceBetween size="l">
          <DocumentAttributes
            item={enhancedItem}
            versions={versions}
            setToolsOpen={setToolsOpen}
            getDocumentDetailsFromIds={getDocumentDetailsFromIds}
          />

          {localItem.metering && (
            <div>
              <MeteringExpandableSection meteringData={localItem.metering} documentItem={localItem} />
            </div>
          )}
        </SpaceBetween>
      </Container>
      <DocumentViewers
        objectKey={localItem.objectKey}
        evaluationReportUri={localItem.evaluationReportUri}
        summaryReportUri={localItem.summaryReportUri}
        ruleValidationResultUri={localItem.ruleValidationResultUri}
      />
      <SectionsPanel
        {...({
          sections: localItem.sections,
          pages: localItem.pages,
          documentItem: localItem,
          mergedConfig,
          onDocumentUpdate: setLocalItem,
        } as Record<string, unknown>)}
      />
      <PagesPanel {...({ pages: localItem.pages, documentItem: localItem } as Record<string, unknown>)} />
      <ChatPanel objectKey={localItem.objectKey} />

      {/* Step Function Flow Viewer - uses the document's config version, not the active stack config */}
      {localItem?.executionArn && (
        <StepFunctionFlowViewer
          executionArn={localItem.executionArn}
          visible={isFlowViewerVisible}
          onDismiss={() => setIsFlowViewerVisible(false)}
          mergedConfig={documentVersionConfig}
        />
      )}

      {/* Troubleshoot Modal */}
      <TroubleshootModal
        visible={isTroubleshootModalVisible}
        onDismiss={() => setIsTroubleshootModalVisible(false)}
        documentItem={localItem}
        existingJob={troubleshootJobs[localItem?.objectKey] as unknown as { jobId: string; status: string }}
        onJobUpdate={(jobData: TroubleshootJobData) => {
          setTroubleshootJobs((prev) => ({
            ...prev,
            [localItem.objectKey]: jobData,
          }));
        }}
      />
    </SpaceBetween>
  );
};

export default DocumentPanel;
