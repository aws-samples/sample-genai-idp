import React from 'react';
import { HelpPanel } from '@awsui/components-react';

const header = <h2>Configuration</h2>;
const content = (
  <>
    <p>Manage application configuration settings.</p>
    <p>Default values are set by the system during deployment. Any customized values will override the defaults.</p>
    <p>
      To restore a customized value back to its default, click the &quot;Reset to default&quot; link next to the field.
    </p>
  </>
);

const ToolsPanel = () => <HelpPanel header={header}>{content}</HelpPanel>;

export default ToolsPanel;
