# Company Select Component

## Overview

The Company Select component is a landing page that appears immediately after user authentication. It requires users to select a company before accessing any documents, ensuring GDPR compliance and proper data isolation.

## Features

- **Company Lookup**: Search for companies using UK Companies House 8-digit company numbers
- **Health Check Integration**: Automatically detects if Data Collection Stack is available
- **Background Research**: Optionally triggers deep company research (filing history, officers, etc.) if Data Collection Stack is deployed
- **Graceful Degradation**: Works even if Data Collection Stack is not deployed (shows appropriate messaging)
- **Company Context**: Stores selected company in session for use throughout the application

## User Flow

1. **User logs in** → Redirected to `/company-select`
2. **Health check runs** → Determines if background research is available
3. **User enters company number** → 8-digit UK Companies House number
4. **Click "Search"** → Calls Data Collection API `/company/{number}`
5. **Company details displayed** → Name, status, address, incorporation date
6. **User confirms company** → Clicks "Confirm and research company background"
7. **Background research triggered** (if available) → Step Functions workflow starts
8. **Redirect to documents** → User proceeds to `/documents`

## Integration with Data Collection Stack

### API Endpoints Used

1. **Health Check**: `GET /health`
   - Checks if Data Collection Stack is available
   - Cached for 5 minutes to reduce API calls
   - Returns service availability status

2. **Company Lookup**: `GET /company/{company_number}`
   - Fetches basic company information
   - Returns: name, number, status, address, incorporation date
   - Used to display company details for user confirmation

3. **Background Research**: `POST /research/company`
   - Triggers Step Functions workflow (if available)
   - Runs in background (user doesn't wait)
   - Sends notification when complete

### Configuration

Set the Data Collection API endpoint in `.env`:

```bash
REACT_APP_DATA_COLLECTION_API=https://your-api-id.execute-api.eu-central-1.amazonaws.com/dev
```

## Files

- `CompanySelect.jsx` - Main component
- `index.js` - Component export
- `../../services/dataCollection.js` - API service layer

## Dependencies

- `@awsui/components-react` - AWS UI components
- `react-router-dom` - Routing
- `aws-amplify` - Logging and auth

## State Management

Company selection is currently stored in `localStorage` as a temporary solution:

```json
{
  "company_number": "12345678",
  "company_name": "ACME LTD",
  "selected_at": "2025-10-26T10:30:00Z",
  "user_id": "user-123"
}
```

**TODO**: Replace with API call to store in DynamoDB (Core Stack `UserCompanies` table).

## GDPR Compliance

This component enforces GDPR compliance by:
- **Mandatory company selection** before document access
- **Clear data boundaries** (company context required for all operations)
- **User confirmation** before proceeding
- **Audit trail** (timestamps and user IDs logged)

## Testing

To test without Data Collection Stack deployed:
1. Set `REACT_APP_DATA_COLLECTION_API` to an invalid URL
2. Health check will fail gracefully
3. UI will show "Basic search available" message
4. Company lookup will fail (need to mock or use fallback)

To test with Data Collection Stack:
1. Deploy Data Collection Stack to dev environment
2. Set `REACT_APP_DATA_COLLECTION_API` to your API Gateway URL
3. Test full flow including background research

## Future Enhancements

- [ ] Store company selection in DynamoDB (via API)
- [ ] Support multiple companies per user
- [ ] Company switching UI
- [ ] Progress tracking for background research
- [ ] Recent companies list
- [ ] Favorites/pinned companies
- [ ] Company search by name (not just number)
