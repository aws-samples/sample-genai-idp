#!/bin/bash
# Script to replace all alert() calls with addNotification() in CapacityPlanningLayout.jsx

FILE="src/ui/src/components/capacity-planning/CapacityPlanningLayout.jsx"

# Make backup
cp "$FILE" "$FILE.bak"

# Replace CSV error alerts
sed -i.tmp "s|alert('Error: CSV file must have at least a header row and one data row.');|addNotification('error', 'CSV file must have at least a header row and one data row.', 'CSV Import Error');|g" "$FILE"

# Replace OCR column missing alert (multiline - handle manually in code)
# This one is too complex for sed, mark for manual review

# Replace CSV import success alert
sed -i.tmp "s|alert(\`Imported \${importedConfigs.length} document configurations\`);|addNotification('success', \`Imported \${importedConfigs.length} document configuration\${importedConfigs.length > 1 ? 's' : ''}\`, 'Import Successful');|g" "$FILE"

# Replace CSV parse error
sed -i.tmp "s|alert('Error parsing CSV file. Please check format.');|addNotification('error', 'Error parsing CSV file. Please check the format and try again.', 'CSV Parse Error');|g" "$FILE"

# Replace schedule CSV error
sed -i.tmp "s|alert(\`Imported \${importedSlots.length} schedule entries\`);|addNotification('success', \`Imported \${importedSlots.length} schedule entr\${importedSlots.length === 1 ? 'y' : 'ies'}\`, 'Import Successful');|g" "$FILE"

# Replace schedule parse error
sed -i.tmp "s|alert('Error parsing CSV file. Please check format.\\\\nExpected format: Hour,Document Type,Docs Per Hour');|addNotification('error', 'Error parsing CSV file. Expected format: Hour, Document Type, Docs Per Hour', 'CSV Parse Error');|g" "$FILE"

# Replace quota sufficient alert
sed -i.tmp "s|alert('All quotas are currently sufficient for your capacity requirements.');|addNotification('success', 'All quotas are currently sufficient for your capacity requirements.', 'Quotas Sufficient');|g" "$FILE"

# Clean up temp files
rm -f "$FILE.tmp"

echo "✅ Replaced alert() calls with addNotification() in $FILE"
echo "⚠️  Backup created at $FILE.bak"
echo ""
echo "Note: Complex multiline alerts need manual review. Search for remaining alert() calls."
