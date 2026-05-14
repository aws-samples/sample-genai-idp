/**
 * IDPMonitor — Monitoring Components Barrel Export
 *
 * Re-exports all public monitoring UI components for use via path alias:
 *   import { MonitoringPage } from '@idp-monitor/components/monitoring'
 */

// Page-level components
export { MonitoringPage } from './MonitoringPage';
export { MonitoringActivationPage } from './MonitoringActivationPage';
export { MonitoringFilters } from './MonitoringFilters';
export { MonitoringLayout } from './MonitoringLayout';

// Widgets
export { SummaryWidget } from './widgets/SummaryWidget';
export { KPICardsWidget } from './widgets/KPICardsWidget';
export { VolumeChartWidget } from './widgets/VolumeChartWidget';
export { DocTypeChartWidget } from './widgets/DocTypeChartWidget';
export { CostWidget } from './widgets/CostWidget';
export { LatencyChartWidget } from './widgets/LatencyChartWidget';
export { ThrottleWidget } from './widgets/ThrottleWidget';
export { FailuresTableWidget } from './widgets/FailuresTableWidget';
export { ConfigPanelWidget } from './widgets/ConfigPanelWidget';
