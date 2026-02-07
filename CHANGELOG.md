Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# Changelog

## [Unreleased]

### Added

- **Custom Date Range Selector for Document List and Test Executions** - [GitHub Issue #177](https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws/issues/177)
  - Added "Custom range..." option to the time period dropdown in both Document List and Test Studio → Test Results
  - Users can now select absolute start/end dates to query historical documents beyond the previous 30-day limit
  - **Scalable Server-Side Architecture**: Custom date ranges use a new `listDocumentsByDateRange` Lambda resolver that iterates shards server-side and batch-fetches documents, avoiding the client-side fan-out scalability issue
  - **Existing Behavior Preserved**: Relative period presets (2h through 30d) continue using the proven client-side shard mechanism — zero changes to existing code paths
  - **365-Day Maximum**: Date range capped at 365 days in the UI to prevent unbounded queries

### Fixed

- **Schema Builder Few-Shot Examples Input Focus Loss** - [GitHub Issue #174](https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws/issues/174)
  - Fixed cursor jumping out of input fields after each keystroke when editing few-shot examples in the Schema Builder


- **Code Intelligence Agent - DeepWiki MCP Transport Migration**
  - Fixed "client initialization failed" error when using Code Intelligence Agent in Agent Companion Chat
  - **Root Cause**: DeepWiki deprecated their SSE transport endpoint (`/sse`) and now returns HTTP 410 Gone
  - **Solution**: Migrated from SSE (`sse_client`) to Streamable HTTP (`streamablehttp_client`) transport using the new `/mcp` endpoint
  - See DeepWiki documentation: https://docs.devin.ai/work-with-devin/deepwiki-mcp

## [0.4.14]

### Added

- **Enhanced BDA to IDP Sync for Pattern-1**
  - Separate "Sync from BDA" and "Sync to BDA" buttons in the UI for explicit directional control instead of bidirectional-only sync
  - Parallel blueprint processing for improved sync performance on configurations with many document classes
  - Orphaned blueprint cleanup automatically detects and removes BDA blueprints no longer defined in IDP configuration
  - Warning notifications for skipped properties due to BDA limitations (nested arrays/objects), with guidance to flatten schemas using top-level `$defs`
  - AWS standard blueprint filtering prevents unintended modifications to AWS-managed blueprints

- **Human-in-the-Loop (HITL) Review Workflow Improvements**
  - **Review Ownership Model**: Reviewers must now claim documents using "Start Review" before editing, preventing concurrent edits
  - **Review In Progress Status**: New status displayed when a reviewer has claimed a document
  - **Filtered Document List for Reviewers**: Reviewers now see only documents pending review or their own in-progress reviews
  - **Admin Skip All Reviews**: Admins can skip all remaining section reviews without triggering document reprocessing
  - **Release Review**: Reviewers can release claimed documents back to pending status; Admins can release any review
  - **Review Completed By Field**: New column showing who completed or skipped the review (renamed from "Reviewed By")

- **Pattern-1 Edit Mode with Data-Only Editing and Reprocessing**
  - Added Edit Mode capability for Pattern-1 (BDA) stacks, enabling users to edit extraction data without modifying section structure
  - **Data-Only Editing**: Click "Edit Mode" then use "Edit Data" buttons on each section to open the Visual Editor for modifying predictions and ground truth
  - **Reprocessing Without BDA**: "Save and Reprocess" triggers evaluation and summarization steps without re-invoking Bedrock Data Automation (BDA)
  - **Section Structure Protection**: Section structure (IDs, classes, page assignments) remains read-only as managed by BDA blueprints
  - **Skip Logic Implementation**: State machine automatically detects existing pages/sections data and bypasses BDA invocation for reprocessing scenarios
  - **Use Cases**: Correct extraction errors, add baseline data for evaluation comparison, re-run evaluation after data corrections, update document summaries

### Changed

- **HITL Decoupled from Step Functions**: HITL review operations now update document status directly in DynamoDB without triggering workflow reprocessing, improving reliability and reducing unintended side effects

- **Renamed TestSet from RVL-CDIP-N-MP to DocSplit-Poly-Seq**
  - Updated Test Studio test set name to better reflect its purpose as a document splitting and classification benchmark
  - The underlying HuggingFace dataset source (`jordyvl/rvl_cdip_n_mp`) remains unchanged

- **Review Status Labels**: Renamed status values for consistency:
  - "Pending Review" → "Review Pending"
  - "Reviewed By" column → "Review Completed By"

### Fixed

- **HITL Decimal Serialization Error**: Fixed "Object of type Decimal is not JSON serializable" error when performing HITL operations (Start Review, Release Review, Skip All Reviews) by properly converting DynamoDB Decimal types

- **HITL Operations Clearing Estimated Cost**: Fixed issue where Start Review and Release Review operations were inadvertently clearing the Metering/Estimated Cost data by re-serializing the entire document; operations now update only HITL-specific fields

- **Pattern-1 Page/Section Number Alignment with Pattern-2 and Ground Truth**
  - Fixed page and section numbering mismatch between Pattern-1 (BDA) and Pattern-2 that caused evaluation failures when using shared test sets
  - **Root Cause**: BDA outputs 0-based indices while Pattern-2 and ground truth test sets use 1-based page IDs
  - **Solution**: Pattern-1 postprocessing now transforms S3 paths and Document model IDs to 1-based (`pages/1/`, `sections/1/`, `page_ids: ["1", "2"]`) while preserving 0-based `page_indices` arrays in result.json for internal consistency
  - **Key Distinction**: `page_indices` (array indices) remain 0-based, `page_id`/`section_id` (identifiers) are now 1-based
  - Both patterns now align correctly for evaluation with shared test sets and ground truth data

- **TIFF Image Format Support for Bedrock-Compatible Processing**
  - Fixed classification failure when processing TIFF image files ("Unsupported image format: TIFF")
  - OCR step now converts non-Bedrock-compatible formats (TIFF, BMP) to JPEG during page image extraction
  - Multi-page TIFF files handled like PDFs - each page becomes a separate document page

- **Discovery Feature Overwriting Existing Classes During Class Discovery**
  - Fixed issue where using Discovery to discover a new document type would delete all existing classes from the configuration
  - **Root Cause**: Custom config `classes` array was replacing Default `classes` array during runtime merge, causing loss of existing classes
  - **Solution**: Discovery now reads both Default and Custom classes, merges them with the newly discovered class, and saves the complete merged list to Custom config
  - Ensures discovered classes are additive to existing configuration rather than replacing it

### Templates
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.4.14.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main_0.4.14.yaml`
   - eu-central-1: `https://s3.eu-central-1.amazonaws.com/aws-ml-blog-eu-central-1/artifacts/genai-idp/idp-main_0.4.14.yaml`

## [0.4.13]

### Added

- **Rule Validation for Automated Compliance Assessment**
  - Added Rule Validation module enabling automated validation of extracted document data against configurable business rules and compliance criteria
  - **Key Capabilities**: Validate documents against any domain-specific compliance requirements (healthcare, financial, legal, insurance, manufacturing), customizable pass/fail criteria adaptable to industry needs, concurrent processing with intelligent chunking for large documents
  - **Dual Output Formats**: JSON for programmatic integration and Markdown for human review
  - **Integration**: Integrated into Pattern-2 workflow with AWS Step Functions parallel processing
  - **Example Use Cases**: Healthcare prior authorization validation, loan application compliance checking, contract clause verification, claims validation, quality control
  - **Configuration**: Fully configurable via `rule_validation` settings including custom recommendation options, model selection, and processing limits
  - **Documentation**: Complete guide in `docs/rule-validation.md` 

- **Visual Document Editor Enhancements**
  - **Improved Navigation Controls**: Mouse wheel zoom (no modifier key required) and click-and-drag panning for intuitive document image exploration
  - **Inline Field Editing with S3 Save**: Edit prediction values directly in the visual editor with change tracking, edit history, and direct S3 persistence
  - **Evaluation Baseline Editing**: Edit baseline (expected) values directly in the editor when evaluation data is available, with dedicated save/discard controls and independent change tracking from predictions
  - **Save & Reprocess Workflow**: After saving edits to predictions or baselines, trigger reprocessing to re-run summarization and evaluation with updated data; document automatically transitions through SUMMARIZING → EVALUATING → COMPLETE statuses
  - **Tabbed Interface**: New tabs for Visual Editor (form-based), JSON Editor (raw JSON with section filtering), and Revision History (audit trail with timestamps and field-level diffs)
  - **Smart Filtering**: Filter to show only low-confidence fields or evaluation mismatches; collapsible tree navigation with Expand/Collapse All controls
  - **Evaluation Comparison Mode**: Side-by-side predicted vs expected values with match indicators (✓/⚠), evaluation scores, and LLM-generated comparison reasons
  - **Section Navigation**: Previous/Next buttons to navigate between document sections without closing the editor

- **Section-Level DynamoDB Updates for Parallel Processing Optimization**
  - Added lightweight `updateDocumentStatus` mutation for status-only updates (~500 bytes vs ~100KB full document)
  - Added atomic `updateDocumentSection` mutation for individual section updates using `SET Sections[index] = :value`
  - **Scalability**: Eliminates DynamoDB throttling for very large documents by avoiding full-document read-modify-write cycles
  - **Real-time Updates**: Both new mutations now trigger `onUpdateDocument` subscription for UI synchronization
  - **Pattern-2/3 Integration**: Extraction and assessment functions now use section-level updates instead of full document rewrites


### Fixed

- **Visual Editor Confidence Alerts Filter Not Showing Null Fields** - Fixed issue where the "Confidence Alerts Only" filter in the Document Details visual editor was not displaying fields with `null` values, even when they had low confidence scores in `explainability_info`. The filter now properly detects and shows all low-confidence fields regardless of their value type.

- **Evaluation Failure for Schemas with Empty Nested Objects** - Fixed evaluation failing with "field_definitions must contain at least one field" error when document schemas contain nested objects with empty properties (e.g., `AccidentInformation: {type: object, properties: {}}`). Empty object properties are now automatically filtered during schema processing.

- **Evaluation Report Section Ordering** - Fixed document sections in evaluation markdown reports iterating in alphabetical order (1, 10, 11, 2, 3) instead of numerical order (1, 2, 3, 10, 11) by implementing natural sorting for section IDs

- **Confidence Alerts Mismatch for JSON Schema `$ref` Properties**
  - Fixed issue where confidence alerts in UI showed incorrect counts (all with confidence=0) that didn't match the actual extraction confidence scores in explainability_info JSON
  - **Root Cause**: Properties using JSON Schema `$ref` references were being incorrectly classified as "simple" types instead of "group" (object) types, causing false positive alerts

- **Configuration Import Float Type Error for DynamoDB**
  - Fixed "Float types are not supported. Use Decimal types instead" error when importing configuration files via CLI (`idp-cli config-upload`) or Web UI

### Templates
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.4.13.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main_0.4.13.yaml`
   - eu-central-1: `https://s3.eu-central-1.amazonaws.com/aws-ml-blog-eu-central-1/artifacts/genai-idp/idp-main_0.4.13.yaml`

## [0.4.12]

### Added

- **IDP SDK - Python SDK for Programmatic Document Processing**
  - New `idp_sdk` Python package (`lib/idp_sdk/`) providing a native Python interface for IDP operations
  - **IDPClient Class**: Wraps `idp-cli` commands with Pythonic methods for seamless integration into Python applications
  - **Key Methods**: `run_inference()`, `rerun_inference()`, `download_results()`, `status()`, `deploy()`, `delete()`, `delete_documents()`, `validate_manifest()`, `generate_manifest()`, `config_create()`, `config_validate()`, `config_download()`, `config_upload()`
  - **Pydantic Response Models**: Type-safe response objects (`BatchResult`, `ManifestResult`, `ValidationResult`, `ConfigCreateResult`, `ConfigValidationResult`) with proper Pydantic v2 compatibility
  - **Lambda Integration Example**: Complete SAM template and handler demonstrating SDK usage in AWS Lambda functions
  - **Documentation**: SDK reference guide (`docs/idp-sdk.md`) with CLI command mapping, usage examples, and Lambda patterns
  - **Easy Installation**: `pip install -e lib/idp_sdk` or `make setup` installs SDK with all dependencies
  - **Use Cases**: CI/CD pipelines, Lambda functions, automated workflows, custom integrations, and programmatic batch processing

- **Relocated idp-cli to lib/idp_cli_pkg/**
  - Moved `idp_cli/` directory to `lib/idp_cli_pkg/` to co-locate with other library packages
  - Updated all documentation and Makefile targets for new location

- **Modular System Defaults Architecture for Simplified Configuration**
  - Introduced pattern-specific system default files (`lib/idp_common_pkg/idp_common/config/system_defaults/pattern-{1,2,3}.yaml`) that provide default settings for OCR, classification, extraction, assessment, evaluation, summarization, discovery, and agents
  - User configurations now only need to specify `notes`, `classes`, and any intentional overrides - all other settings inherit from system defaults
  - Simplified all config_library configurations to minimal footprint (most now just 10-30 lines instead of hundreds)
  - Updated all README files in config_library and docs/configuration.md with inheritance documentation
  - **Benefits**: Simpler configs, automatic maintenance when defaults evolve, clearer visibility into customizations

- **Increased Extraction max_tokens Default** - Increased default `max_tokens` for extraction from 10,000 to 65,535 (Nova 2 Lite model maximum) to reduce LLM output truncation on long documents

- **IDP CLI Configuration Management Commands** - [GitHub Issue #87](https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws/issues/87)
  - `idp-cli config-create` - Generate IDP configuration template from system defaults with selectable feature sets
  - `idp-cli config-validate` - Validate configuration file against system defaults and JSON schema
  - `idp-cli config-download` - Download current configuration from a deployed stack
  - `idp-cli config-upload` - Upload a local configuration file to a deployed stack's DynamoDB ConfigurationTable

- **IDP CLI Auto-Monitor for In-Progress Stack Operations**
  - Enhanced `idp-cli deploy` and `idp-cli delete` commands to automatically detect in-progress CloudFormation operations
  - **Smart Detection**: When running deploy/delete on a stack that's already creating, updating, deleting, or rolling back, the CLI automatically switches to monitoring mode instead of failing
  - **Seamless UX**: If you forget to use `--wait` on the first run, simply run the same command again to monitor progress
  - **Interactive Cancel for Delete**: When running `idp-cli delete` on a stack with CREATE or UPDATE in progress, offers option to cancel the current operation and proceed with deletion

- **New Make Targets and Documentation**
  - Added `make setup` target to install `idp-cli` and `idp_common` packages in development mode
  - Added `make ui-start` target to start UI dev server with optional `STACK_NAME` parameter for auto-generating `.env` from stack outputs
  - Documented all make targets in CONTRIBUTING.md including setup, lint, test, ui-start, commit, and DSR security scanning

- **IDP CLI New Commands for Operations and Testing**
  - Added `idp-cli load-test` command for throughput testing with configurable document rates (1-10,000/min) and dynamic schedule support via CSV files
  - Added `idp-cli stop-workflows` command for batch workflow termination with interactive confirmation and dry-run mode
  - Added `idp-cli delete-documents` command for removing documents and all associated data from the IDP system
  - Added `idp-cli remove-deleted-stack-resources` command for discovering and removing orphaned resources (CloudFront distributions, response header policies, CloudWatch log groups, AppSync APIs, IAM policies, S3 buckets, DynamoDB tables) left behind after IDP stacks are deleted, with multi-region stack discovery, interactive confirmation with "yes/skip all of type" options, and configurable `--check-stack-regions` option
  - Comprehensive unit tests added for all new CLI modules


### Changed

- **Scripts Directory Reorganization**
  - Consolidated development environment setup scripts into `scripts/setup/` subdirectory
  - Moved CI/CD scripts (`codebuild_deployment.py`, `integration_test_deployment.py`, `validate_buildspec.py`, `typecheck_pr_changes.py`, `validate_service_role_permissions.py`) into `scripts/sdlc/` subdirectory
  - Updated all references in `.gitlab-ci.yml`, `Makefile`, and documentation

### Fixed

- **Fixed Document Details Page Not Loading After Browser Refresh for Document IDs Containing Forward Slashes**
  - Fixed issue where navigating to a document with a `/` in the Document ID (e.g., `folder/filename.pdf`) and then refreshing the browser would result in a blank page
  - **Root Cause**: When the browser refreshes a URL containing `%2F` (encoded slash), it automatically decodes it to `/`. React Router's `:objectKey` parameter only captures a single path segment, so `folder/filename.pdf` was being split into multiple segments, causing a route mismatch
  - **Solution**: Changed the route from `path=":objectKey"` to `path="*"` (wildcard route) to capture the full remaining path including any embedded slashes, and updated `DocumentDetails` component to extract the document key from `params['*']`

- **Improved UX for Document List and Document Details Action Buttons**
  - Added hover tooltips to all Document List toolbar buttons (Refresh, Download, Release Review, Abort, Reprocess, Delete) for better discoverability
  - Converted Abort, Reprocess, Delete, and Release Review buttons to icon-only display for a cleaner, more compact toolbar
  - Added `unlocked` icon to Release Review button to visually represent releasing a human review lock

- **Fixed Evaluation Failure for Documents with Truncated LLM Extraction Output**
  - Fixed evaluation service crash when extraction output contained unparsed `raw_output` instead of structured fields
  - **Root Cause**: When LLM extraction output is truncated (model hits max_tokens limit), the extraction service stores `{"raw_output": "..."}` which caused Pydantic validation errors during evaluation
  - **Solution**: 
    - Added `repair_truncated_json()` utility function that attempts to repair truncated JSON using multiple strategies (closing brackets, finding last complete element, extracting complete fields)
    - Integrated JSON repair into extraction service - most truncated output is now automatically repaired
    - Added detection of `raw_output` case in evaluation service with clear error messaging: "Extraction parsing failed... LLM output could not be parsed as valid JSON. This typically indicates truncated output (model hit max_tokens limit). Consider increasing max_tokens in extraction config."
    - Added metadata fields (`output_truncated`, `output_repaired`, `repair_method`) to track truncation/repair status
    - Enhanced evaluation service type coercion to provide appropriate defaults for required fields when LLM returns null values (prevents Pydantic validation errors like "Field required")

- **Fixed AgentRequestHandler Missing Lambda Invoke Permission for Error Analyzer Agent**
  - Fixed AccessDeniedException when clicking the Troubleshoot button in the Web UI

- **Fixed sectionSplitting=disabled Incorrectly Classifying Documents Based on Blank Pages - [GitHub Issue #167](https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws/issues/167)**
  - Fixed bug where documents with blank pages could be incorrectly classified as `"unclassifiable_blank_page"` when using `sectionSplitting: disabled`
  - **Root Cause**: Page classification results arrive in completion order (not page order) from ThreadPoolExecutor, so blank/simple pages that finish processing first would end up at index 0 and incorrectly determine the document classification
  - **Solution**: Implemented majority voting strategy that:
    - Uses config-defined classes to determine voting eligibility (only pages matching valid document types from configuration can vote)
    - Automatically excludes any classification not in the config (blank pages, errors, LLM hallucinations)
    - Uses majority voting - most common valid classification wins
    - Uses first page's classification as tie-breaker for determinism
    - Falls back to first page's classification when all pages are unclassifiable
  - **Benefits**: Config-driven approach automatically adapts to any defined document classes without hardcoding exclusion lists
  - Updated documentation in `docs/classification.md` explaining the voting behavior

- **Test Results Config Export Not Properly Merging or Formatting**
  - Fixed issue where config export was downloading raw JSON with separate Default/Custom entries instead of merged config

### Removed

- **Obsolete Scripts Migrated to IDP CLI**
  - Removed `simulate_load.py` and `simulate_dynamic_load.py` (replaced by `idp-cli load-test`)
  - Removed `stop_workflows.sh` (replaced by `idp-cli stop-workflows`)
  - Removed `cleanup_orphaned_resources.py` (replaced by `idp-cli remove-deleted-stack-resources`)
  - Removed `lookup_file_status.sh` (replaced by `idp-cli status --document-id`)
  - Removed unused utilities: `add_lambda_layers.py`, `test_layer_build.py`, `test_pip_extras.py`, `compare_json_files.py`, `benchmark_utils/`

### Templates
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.4.12.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main_0.4.12.yaml`
   - eu-central-1: `https://s3.eu-central-1.amazonaws.com/aws-ml-blog-eu-central-1/artifacts/genai-idp/idp-main_0.4.12.yaml`


## [0.4.11]

### Added

- **Built-in Human-in-the-Loop (HITL) Review System**
  - Replaced Amazon SageMaker A2I (Augmented AI) with a built-in HITL review system integrated directly into the Web UI
  - **Persona-Based Access Control**: 
    - **Admin**: Full access to all documents, can skip reviews, release review locks, and manage users
    - **Reviewer**: Access limited to documents pending HITL review, can claim and complete section reviews
  - **Review Workflow Features**:
    - Start Review button to claim document ownership and prevent concurrent edits
    - Section-level review with inline JSON editing and visual document viewer
    - Mark Section Review Complete to approve individual sections
    - Skip All Reviews (Admin only) to bypass pending reviews and continue workflow
    - Release Review to unlock document for other reviewers
  - **Real-time Status Updates**: Review Status, Review Status, Review Owner, and Reviewed By fields update in real-time across all user sessions via GraphQL subscriptions
  - See [Human-in-the-Loop Review Documentation](./docs/human-review.md) for detailed workflow information
  - **Note**: These are Phase 1 of HITL process updates. In upcoming phases, we are working to deliver futher improvements to human review capabilities with the ability to update document classification, extraction, and resubmit for incremental processing as part of a holistic approach to huiman reviews.
- **User Management**
  - New User Management page for Admin users to create and manage additional Admin & Reviewer accounts
  - Cognito user groups (Admin, Reviewer) for role-based access control
  - Automatic user synchronization with Cognito

- **DocSplit-Poly-Seq Test Set Auto-Deployment**
  - Automatically deploys 500 multi-page packet PDFs from HuggingFace dataset (https://huggingface.co/datasets/jordyvl/rvl_cdip_n_mp) during stack deployment
  - **13 Document Types**: invoice, email, form, letter, memo, resume, budget, news article, scientific publication, specification, questionnaire, handwritten, and language (non-English) documents
  - **Multi-Document Packets**: Each of 500 packets contains 2-10 distinct subdocuments of different types for comprehensive splitting and classification testing
  - **Packet Statistics**: 7,330 total pages across 2,027 document sections with average of 14.7 pages and 4.1 sections per packet
  - **Ground Truth Included**: Page-level classification and document boundary information for each packet. Extraction ground truth is not included.
  - **Evaluation Capabilities**: Enables testing of page-level classification accuracy, document splitting accuracy, and split order preservation. Does NOT enable testing of extraction accuracy since there is no extraction ground truth for this data set
  - Test set available in Test Studio UI alongside RealKIE-FCC-Verified and OmniAI-OCR-Benchmark datasets
  - Corresponding configs available in Configuration Library
  - Ideal for evaluating document splitting and classification accuracy in complex multi-document scenarios


### Changed

- **HITL Configuration**
  - HITL is now disabled by default in the configuration
  - Users must explicitly enable HITL in the Configuration page (Assessment & HITL Configuration section) to trigger human review workflows
  - `hitl_enabled` setting controls whether documents with low confidence trigger HITL review

### Removed

- **Amazon SageMaker A2I Resources**
  - Removed SageMaker A2I Flow Definition, Human Task UI, and Workteam resources
  - Removed A2I-related Lambda functions (`create_a2i_resources`, `get-workforce-url`)
  - Removed `EnableHITL` and `PrivateWorkteamArn` CloudFormation parameters


### Changed

- **Lambda Layers Architecture for Improved Build Efficiency**
  - Replaced bundled `idp_common` package dependencies in individual Lambda functions with three shared Lambda Layers
  - **Three Specialized Layers**:
    - `base` layer: Core functionality with docs_service and image extras
    - `reporting` layer: Reporting and analytics dependencies
    - `agents` layer: Agent-related dependencies
  - **Key Benefits**:
    - Reduced SAM build times by eliminating redundant dependency installation across 50+ Lambda functions
    - Layer content-based hashing ensures layers are only rebuilt when actual contents change
    - Automatic removal of Lambda runtime packages (boto3, botocore, etc.) reduces layer sizes by ~100MB
    - Layer zips cached locally and in S3, skipping uploads when content hasn't changed
  - **Build System Integration**: publish.py automatically builds, hashes, and uploads layers before SAM builds

- **Enhanced publish.py Performance and Logging**
  - **Consistent Logging Helpers**: Added 8 standardized logging methods (`log_phase`, `log_task`, `log_detail`, `log_success`, `log_cached`, `log_warning`, `log_error`) for uniform output formatting with colored icons and thread prefixes
  - **Timed S3 Uploads**: Added `upload_to_s3_with_timer()` helper with spinner animation, elapsed time display, and optimized `TransferConfig` for multi-threaded multipart uploads
  - **AWS CLI Config Library Sync**: Replaced boto3 ThreadPoolExecutor-based config library upload (~60 lines) with `aws s3 sync` command for built-in concurrency, delta sync (skip unchanged files), and simpler code
  - **Timing Breakdown Summary**: End-of-build summary shows top 4 time-consuming steps and percentages for build optimization insights
  - **Phase Headers**: Major build phases now display with clear `═══` separator lines and emojis for visual clarity

- **AppSync Resolvers Extracted to Nested Stack for Improved Template Modularity**
  - Refactored main CloudFormation template by extracting 130 AppSync resources into new nested stack architecture
  - **Extracted Components**:
    - Created `nested/appsync/template.yaml` containing GraphQLSchema, AppSyncServiceRole, Lambda resolver functions, LogGroups, DataSources, and Resolvers
    - Moved related Lambda functions from `src/lambda/` to `nested/appsync/src/lambda/` with colocated template definitions
    - Relocated GraphQL schema from `src/api/` to `nested/appsync/src/api/`
  - **Main Template Optimization**: Reduced resource count by keeping only core infrastructure (GraphQLApi, GraphQLApiLogGroup, AppSyncCwlRole, WAF resources, background worker functions)
  - **Build System Integration**: Updated `publish.py` to build nested stack in parallel with patterns
  - **Impact**: Main template now more manageable and faster to navigate, nested stack enables modular development of AppSync resources, parallel builds reduce overall build time

- **Consolidated Nested Stack Directory Structure**
  - Moved `options/bda-lending-project` and `options/bedrockkb` into `nested/` directory for simplified project organization
  - All CloudFormation nested stacks now located in single `nested/` directory alongside `appsync`, `bda-lending-project`, and `bedrockkb`
  - Updated build system to build only two categories concurrently (nested + patterns) instead of three (nested + patterns + options)
  - **Breaking Change**: Directory paths changed - `options/` → `nested/`. Existing work-in-progress branches will have merge conflicts in directory structure.


### Fixed

- **Fixed page_indices Reset Bug in Multi-Section Documents**
  - Fixed issue where all sections in document packets had page_indices starting from 0 instead of their actual position in the original document by pre-calculating indices during classification with access to global minimum page ID and storing in section.attributes for extraction step to use

- **Metering Table Added Requests**
  - Added requests count to bedrock metering data to track API request metrics
  
- **IDP CLI Stack Parameter Preservation During Updates**
  - Fixed bug where `idp-cli deploy` command was resetting ALL stack parameters to their default values during updates, even when users only intended to change specific parameters


### Upgrade Notes

- **⚠️ IMPORTANT: Upgrading from v0.4.11 or earlier**
  - **Complete all pending HITL workflows before upgrading**: Any documents waiting in SageMaker A2I human review loops will be orphaned as A2I resources are deleted during the upgrade
  - **Re-enable HITL after upgrade**: If you previously had `EnableHITL=true` CloudFormation parameter, you must now enable HITL through the Configuration page in the Web UI (Assessment & HITL Configuration → Enable HITL)
  - **User migration**: Existing Cognito users will need to be assigned to Admin or Reviewer groups for HITL access 

### Templates
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.4.11.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main_0.4.11.yaml`
   - eu-central-1: `https://s3.eu-central-1.amazonaws.com/aws-ml-blog-eu-central-1/artifacts/genai-idp/idp-main_0.4.11.yaml`



## [0.4.10]

### Added

- **Enhanced Evaluation Reports with Granular Field Comparison Details (sticker-eval v0.1.4)**
  - Integrated sticker-eval v0.1.4's fine-grain field comparison feature providing detailed nested object match information alongside aggregate scores
  - **Nested Field Details**: For complex attributes (objects, arrays), reports now show individual field-by-field comparisons in addition to aggregate rollup scores
  - **Interactive Report Controls**: 
    - 🔍 "Show Only Unmatched" button to filter and display only problematic fields for focused debugging
    - ➕➖ Expand/Collapse All buttons to control nested detail visibility across the entire report
    - Expandable `<details>` sections for each attribute with nested comparisons
  - **Visual Enhancements**: Aggregate scores clearly marked with blue styling and "(aggregate)" annotation, color-coded rows (green for matched, red for unmatched), HTML tables with field paths and comparison results
  - **JSON Report Structure**: Full `field_comparison_details` array preserved in JSON output for programmatic analysis and consumption by analytics tools
  - **Benefits**: Quickly identify which specific nested fields cause aggregate score drops, compact problem view focusing on unmatched rows, complete diagnostic context with both high-level and granular perspectives

- **BDA / IDP Sync Feature for Pattern-1 Blueprint Synchronization**
  - Added bidirectional synchronization between BDA (Bedrock Data Automation) blueprints and IDP custom document classes
  - **Key Capabilities**: Automatic blueprint creation from IDP classes, automatic IDP class creation from BDA blueprints, intelligent change detection using DeepDiff, automatic cleanup of orphaned blueprints
  - **Sync Process**: Discovery configurations automatically trigger blueprint updates in BDA projects via `sync_bda_idp_resolver` Lambda function
  - **Schema Transformation**: Converts between IDP JSON Schema (draft 2020-12) and BDA blueprint format (draft-07) while preserving semantic meaning
  - **Important Limitations**: AWS managed blueprints excluded from sync, nested objects within objects not supported by BDA, nested arrays within object definitions not supported
  - **Best Practices**: Use flattened schema structures, place arrays only at top-level, validate schema structure before sync, monitor sync results for partial failures
  - **Use Cases**: Maintain consistency between IDP configuration and BDA blueprints, automatically propagate configuration changes, streamline document class management across both systems

- **Separate Pricing Configuration and Management UI**
  - Pricing configuration separated from general IDP configuration into dedicated system
  - New `config_library/pricing.yaml` file with centralized pricing for all AWS services (Textract, Bedrock, BDA, Lambda, SageMaker)
  - New "Pricing" page in Web UI for managing service pricing with:
    - Edit pricing for individual APIs and units (e.g., `bedrock/us.amazon.nova-lite-v1:0` → `inputTokens`, `outputTokens`)
    - Import/Export pricing configurations (JSON/YAML)
  - Used for cost estimation and reporting across all document processing workflows

- **Enhanced Document Pages Editor for Pattern-2 and Pattern-3**
  - Replaced confusing "View/Edit Data" button with intuitive "View Page Text" and "Edit Pages" workflow mirroring the Document Sections panel pattern
  - New modal editor with split-pane layout displaying plain text (left) and live markdown preview (right) - no more raw JSON visible to users
  - Added ability to reset page classifications to force reclassification and edit page text content with immediate S3 saves to prevent data loss
  - Implemented "Save & Process Changes" workflow for selective reprocessing - class resets trigger section removal and reclassification, text modifications trigger re-extraction while preserving sections
  - Resolves #164 

### Templates
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.4.10.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main_0.4.10.yaml`
   - eu-central-1: `https://s3.eu-central-1.amazonaws.com/aws-ml-blog-eu-central-1/artifacts/genai-idp/idp-main_0.4.10.yaml`

## [0.4.9]

### Added

- **OmniAI OCR Benchmark Dataset Auto-Deployment for Test Studio**
  - Automatically deploys 293 document images from OmniAI OCR Benchmark HuggingFace dataset (https://huggingface.co/datasets/getomni-ai/ocr-benchmark) during stack deployment
  - **9 Document Formats**: BANK_CHECK (52), COMMERCIAL_LEASE_AGREEMENT (52), CREDIT_CARD_STATEMENT (11), DELIVERY_NOTE (8), EQUIPMENT_INSPECTION (11), GLOSSARY (31), PETITION_FORM (51), REAL_ESTATE (59), SHIFT_SCHEDULE (18)
  - Pre-selected images filtered for formats with >5 samples per schema for quality benchmarking
  - Complex nested JSON schemas with objects and arrays matching original HuggingFace dataset structure
  - Test set available in Test Studio UI alongside existing RealKIE-FCC-Verified dataset
  - Corresponding config: `config_library/pattern-2/ocr-benchmark/config.yaml` with all 9 document classes
  - Ideal for testing classification across diverse document types and extraction on complex nested schemas
  
- **GovCloud Configuration Library for Pattern-1 and Pattern-2** - [GitHub Issue #162](https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws/issues/162)
  - Added `lending-package-sample-govcloud` configurations for both Pattern-1 and Pattern-2 with GovCloud-compatible model IDs
  - **Model ID Mappings for GovCloud**:
    - `us.amazon.nova-pro-v1:0` → `amazon.nova-pro-v1:0`
    - `us.amazon.nova-lite-v1:0` → `amazon.nova-lite-v1:0`
    - All other models (Claude, Nova Premier) → `anthropic.claude-3-7-sonnet-20250219-v1:0`
  - Enhanced `generate_govcloud_template.py` to automatically set GovCloud configurations as default when generating GovCloud templates
  - **Automatic Integration**: GovCloud templates now default to `lending-package-sample-govcloud` configuration ensuring proper model IDs without manual configuration

- **Abort Workflow Feature for Stopping In-Progress Document Processing**
  - Added ability to abort document processing workflows directly from the Web UI
  - New "Abort" button available for documents with in-progress status, with confirmation modal to prevent accidental aborts
  - GraphQL mutation `abortWorkflow` enables programmatic workflow cancellation
  - Documents aborted mid-processing are marked with ABORTED status for clear tracking and reporting

- **Global Cross-Region Inference Profile Model Support**
  - Added support for Bedrock global inference profile models enabling cross-region model access
  - **Supported Global Models**:
    - Amazon Nova 2 Lite (`global.amazon.nova-2-lite-v1:0`)
    - Claude Haiku 4.5 (`global.anthropic.claude-haiku-4-5-20251001-v1:0`)
    - Claude Sonnet 4.5 (`global.anthropic.claude-sonnet-4-5-20250929-v1:0`)
    - Claude Sonnet 4.5 - Long Context (`global.anthropic.claude-sonnet-4-5-20250929-v1:0:1m`)
    - Claude Opus 4.5 (`global.anthropic.claude-opus-4-5-20251101-v1:0`)
  - All global models support prompt caching functionality
  - Enables seamless cross-region model invocation without specifying regional endpoints

- **Amazon Bedrock Service Tier Support for Cost and Performance Optimization**
  - Added support for Amazon Bedrock service tiers through model ID suffixes enabling performance and cost optimization
  - **Three Service Tiers Available**:
    - **Priority**: Fastest response times (~25% better latency) with premium pricing - ideal for customer-facing workflows
    - **Standard**: Consistent performance at regular pricing - default choice for most workloads
    - **Flex**: Variable latency with discounted pricing - optimized for batch processing and non-urgent tasks
  - **Model ID Suffix Format**: Append `:flex` or `:priority` to model IDs (e.g., `us.amazon.nova-2-lite-v1:0:flex`)
  - **Supported Models**: Nova 2 Lite models available with all three tier options across US, EU, and Global regions

### Changed

- **Test Studio UI Enhancements for Improved Table Layouts and User Experience**
  - Added resizable columns and CollectionPreferences with wrap lines for all tables in TestComparison and TestResults
  - Combined accuracy and split classification metrics into collapsible "Average Accuracy and Split Metrics" section with expandable "Additional Metrics" for comprehensive review
  - Added color-coded cost comparisons with visual indicators for improved readability

- **Updated Sample Configurations to Use Amazon Nova 2 Lite as Default Model, and remove Textract TABLES, SIGNATURE features**
  - Changed default model to `us.amazon.nova-2-lite-v1:0` for classification, extraction, summarization, and evaluation across all sample configurations in the configuration library
  - Remove Textract TABLES and SIGNATURES options from default config
  - Provides improved cost-efficiency while maintaining strong performance for document processing workflows

- **Improved Publish Script User Experience**
  - Added spinner progress indicators for SAM build and SAM package operations showing real-time elapsed time
  - Added timing metrics summary showing build/package/total duration for main template builds
  - Output now provides visual feedback during long-running operations instead of appearing silent
  - Enabled parallel SAM builds (`sam build --parallel`) for significantly faster build times (~73s vs 4+ minutes)
  - Pre-built wheel approach for idp_common package eliminates race conditions during parallel Lambda builds

- **RealKIE-FCC-Verified Dataset Schema Alignment with HuggingFace**
  - Updated `config_library/pattern-2/realkie-fcc-verified/config.yaml` to match the HuggingFace json_schema exactly
  - Changed `LineItemDays` from array type with enum values to simple string type (matching raw HuggingFace data format)
  - Updated field descriptions to match HuggingFace schema (e.g., "The agency the invoice is addressed to")

### Templates
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.4.9.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main_0.4.9.yaml`
   - eu-central-1: `https://s3.eu-central-1.amazonaws.com/aws-ml-blog-eu-central-1/artifacts/genai-idp/idp-main_0.4.9.yaml`


## [0.4.8]

### Added

- **Section Data Download Feature for Document Results Export**
  - Added compact "Download" dropdown button in Document Sections panel for exporting section processing results
  - **Two Download Options**: 
    - "Download Data" - Downloads prediction results from OutputBucket (always available)
    - "Download Baseline" - Downloads baseline/ground truth data from EvaluationBaselineBucket (only shown when baseline exists)

- **Configuration Library Import Feature for Enhanced Configuration Management**
  - Added Configuration Library browser enabling users to import pre-configured document processing workflows directly from the solution's configuration library
  - **Dual Import Options**: Users can now choose between importing from local files (existing) or from the Configuration Library (new)
  - **Pattern-Aware Filtering**: Automatically displays only configurations compatible with the currently deployed pattern (Pattern 1, 2, or 3)
  - **README Preview**: When available, displays markdown-formatted README documentation before importing to help users understand configuration purpose and features

- **Test Studio Interactive Charts and Document Analysis Enhancements**
  - **Interactive Score Distribution Charts**: Replaced CloudScape chart with native Recharts implementation featuring dual chart support (Bar Chart and Line Chart options with dropdown selector), native interactivity with built-in click events that open document details modal, and optimized layout with improved margins, labels, and space utilization
  - **Lowest Scoring Documents Analysis**: Enhanced TestResults with table showing documents with lowest weighted overall scores, TestComparison with cross-test comparison of problematic documents, user-configurable count dropdown (5, 10, 20, or 50 documents), side-by-side T1 vs T2 comparison format for easy analysis, and clickable document links for direct navigation to document viewer
  - **UI/UX Improvements**: Compact table styling with reduced spacing and improved readability, left-aligned content for better text alignment of document IDs, consistent design matching existing CloudScape design system, and responsive layout where charts adapt to container width

- **RealKIE-FCC-Verified Dataset Auto-Deployment for Test Studio**
  - Automatically deploys 75 FCC invoice documents from HuggingFace public dataset during stack deployment - zero manual steps required
  - Test set immediately available in Test Studio UI with complete ground truth for benchmarking extraction accuracy
  - Version controlled via CloudFormation property - skips re-download on stack updates unless version changes

### Fixed

- **Bedrock OCR Image Resizing Regression - Partial Dimension Configuration Support**
  - Fixed critical regression where configuring only `target_width` (without `target_height`) disabled all image resizing, causing Bedrock OCR to fail with "length limit exceeded" errors
  - **Root Cause**: OCR service used `and` condition requiring both dimensions, rejecting partial configs and sending full-resolution images that exceeded model input limits
  - **Solution**: Implemented aspect-ratio-preserving single-dimension resizing that calculates missing dimension from actual image aspect ratio

- **Test Studio Bug Fixes**
  - Fixed TestSets manual upload issues

- **Agentic Extraction Prompt Caching** - [GitHub PR #156](https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws/pull/156)
  - Removed additional cachepoints to prevent prompt caching conflicts in agentic extraction

- **GovCloud S3 Vectors Service Principal Deployment Failure** - [GitHub Issue #159](https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws/issues/159)
  - Fixed CloudFormation deployment failure in GovCloud regions caused by S3 Vectors service not being available
  - **Root Cause**: KMS key policy referenced `indexing.s3vectors.${AWS::URLSuffix}` service principal which doesn't exist in GovCloud (us-gov-west-1, us-gov-east-1)

### Templates
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.4.8.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main_0.4.8.yaml`
   - eu-central-1: `https://s3.eu-central-1.amazonaws.com/aws-ml-blog-eu-central-1/artifacts/genai-idp/idp-main_0.4.8.yaml`

## [0.4.7]

### Added

- **MCP Integration Cross-Region Support for QuickSuite Integration**
  - Added cross-region support for QuickSuite integration enabling MCP connectivity across multiple AWS regions: us-east-1, us-west-2, eu-west-1, ap-southeast-2

### Fixed

- **Stack deployment failure due to MCP Integration IAM Permissions - [GitHub Issue #154](https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws/issues/154)**
  - Fixed missing permissions in AgentCoreGatewayManagerFunctionRole by creating the AgentCoreGateway execution role explicitly in the CloudFormation template instead of dynamically in the Lambda function

- **Post-Processing Lambda Hook Compression Handling - [GitHub Issue #155](https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws/issues/155)**
  - Added intermediate decompression lambda to handle document decompression before invoking custom post-processing lambdas
  - **Root Cause**: After introducing document compression, the post-processing lambda hook was receiving compressed documents in the EventBridge payload, forcing external lambdas to import `idp_common` package and handle decompression manually
  - **Solution**: New `PostProcessingDecompressor` lambda function intercepts EventBridge events, decompresses documents using `Document.load_document()`, and invokes custom post-processors with decompressed payload
  - **Benefits**: Maintains backward compatibility, eliminates external dependencies (no `idp_common` import needed), keeps compression/decompression logic encapsulated within IDP stack, minimal performance impact (<1s latency)

- **Enhanced Bedrock Error Handling for Agent Companion Chat**
  - Implemented robust error handling system for Bedrock API errors in Agent Companion Chat feature with automatic retry and graceful degradation
  - **Automatic Retry with Exponential Backoff**: Configured boto3 with adaptive retry mode (3 attempts) and exponential back-off to prevent service overload
  - **User-Friendly Error Messages**: Created `BedrockErrorMessageHandler` to convert technical errors into clear, actionable messages for service unavailable (503), throttling (429), access denied (403), validation errors (400), timeouts (408), and quota exceeded scenarios
  - **Sub-Agent Error Handling**: When sub-agents (Analytics, Error Analyzer, Code Intelligence) encounter Bedrock errors, the orchestrator continues gracefully without crashing, only displaying the first error to avoid duplicates while allowing other sub-agents to complete

- **GovCloud Template Generation - Missing AppSync and MCP Resource Removal**
  - Fixed CloudFormation deployment error "Unresolved resource dependencies [DeleteDocumentResolverFunction]" when deploying GovCloud templates
  - **Test Studio Resources Added (36 resources)**: Added all Test Studio Lambda functions, AppSync resolvers, data sources, and supporting infrastructure to removal list (DeleteTestsResolver, TestRunnerResolver, TestResultsResolver, TestSetResolver, and all related functions, queues, and policies)
  - **MCP/AgentCore Gateway Resources Added (7 resources)**: Added MCP integration resources that depend on Cognito UserPool to removal list (AgentCoreAnalyticsLambdaFunction, AgentCoreGatewayManagerFunction, AgentCoreGatewayExecutionRole, AgentCoreGateway, ExternalAppClient)
  - **MCP Outputs Removed (8 outputs)**: Removed MCP-related outputs that reference deleted resources (MCPServerEndpoint, MCPClientId, MCPClientSecret, MCPUserPool, MCPTokenURL, MCPAuthorizationURL, DynamoDBAgentTableName, DynamoDBAgentTableConsoleURL)
  - **EnableMCP Default Changed**: Set `EnableMCP` parameter default to 'false' for GovCloud since MCP integration requires Cognito authentication infrastructure
  - **Impact**: GovCloud templates now deploy successfully without dependency errors, maintaining core document processing functionality in headless mode


### Templates
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.4.7.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main_0.4.7.yaml`
   - eu-central-1: `https://s3.eu-central-1.amazonaws.com/aws-ml-blog-eu-central-1/artifacts/genai-idp/idp-main_0.4.7.yaml`


## [0.4.6]

### Added

- **New State-Of-The-Art LLM Model Support**
  - Added support for Amazon Nova 2 Lite model (`us.amazon.nova-2-lite-v1:0`, `eu.amazon.nova-2-lite-v1:0`)
  - Added support for Claude Opus 4.5 model (`us.anthropic.claude-opus-4-5-20251101-v1:0`, `eu.anthropic.claude-opus-4-5-20251101-v1:0`)
  - Added support for Qwen 3 VL model (`qwen.qwen3-vl-235b-a22b`)
  - Available for configuration across all document processing steps

- **Test Studio for Comprehensive Test Management and Analysis**
  - Added unified web interface for managing test sets, running tests, and analyzing results directly from the UI
  - **Test Sets Tab**: Create and manage reusable test collections with three creation methods:
    - Pattern-based creation with file patterns to match existing data sets (Input Bucket and Test Set Bucket)
    - Zip upload with automatic extraction of `input/` and `baseline/` folder structure
  - **Test Executions Tab**: Unified interface combining test execution and results management:
    - Real-time status monitoring
    - Multi-select comparison for side-by-side test analysis
    - Integrated export and delete operations
  - **Key Features**: File structure validation, progress-aware status updates, cached metrics for improved performance, dual bucket support for flexible test organization
  - **Documentation**: Guide in `docs/test-studio.md` with architecture details and workflow examples

- **MCP Integration for External Application Access**
  - Added MCP (Model Context Protocol) integration enabling external applications (like Amazon Quick Suite) to access IDP analytics through AWS Bedrock AgentCore Gateway with secure OAuth 2.0 authentication
  - Implemented Analytics Agent with `search_genaiidp` tool for natural language queries of processed document data (statistics, trends, confidence scores, processing status)
  - Controlled by `EnableMCP` parameter (default: true); provides MCPServerEndpoint and authentication outputs for external application integration; documentation in `docs/mcp-integration.md`

- **Configurable Section Splitting Strategies for Enhanced Document Segmentation Control**
  - Added new `sectionSplitting` configuration option to control how classified pages are grouped into document sections
  - **Three Strategies Available**:
    - `disabled`: Entire document treated as single section with first detected class (simplest case)
    - `page`: One section per page preventing automatic joining of same-type documents (deterministic, solves Issue #146)
    - `llm_determined`: Uses LLM boundary detection with "Start"/"Continue" indicators (default, maintains existing behavior)
  - **Key Benefits**: Deterministic splitting for long documents with multiple same-type forms (e.g., multiple W-2s, multiple invoices), eliminates LLM boundary detection failures for critical government form processing, provides flexibility across simple to complex document scenarios
  - Resolves #146

### Changed

- **Improved Temperature and Top_P Parameter Logic for Deterministic Output**
  - Changed inference parameter selection logic to allow `temperature=0.0` for deterministic output (recommended by Anthropic and other model providers)
  - **New Logic**: Uses `top_p` only when it has a positive value (> 0); otherwise uses `temperature` including `temperature=0.0`
  - **Previous Logic**: Used `top_p` whenever `temperature=0.0`, preventing proper deterministic configuration
  - **Key Benefits**: Enables proper deterministic output with `temperature=0.0`, more intuitive parameter behavior, aligns with model provider best practices (Anthropic recommends `temperature=0` for consistent outputs)
  - **Affected Components**: Bedrock client (`lib/idp_common_pkg/idp_common/bedrock/client.py`), Agentic extraction service (`lib/idp_common_pkg/idp_common/extraction/agentic_idp.py`)
  - **Configuration Guidance**: Set `top_p: 0` to use `temperature` parameter; set `top_p` to positive value to override temperature
  - Set temperature to 0.0 in discovery config for deterministic discovery output (was previously set to 1.0)
  - Set top_p to 0.0 in all repo config files to force use of temperature setting by default.

- **Removed page image limit entirely across all IDP services**
  - removed image limits from multimodal inference steps (classification, extraction, assessment) following Amazon Bedrock API removal of image count restrictions. The system now processes all document pages without artificial truncation, with info logging to track image counts for monitoring purposes.
  - Resolves #147

- **Knowledge Base Vector Store Default Changed to S3 Vectors**
  - Changed default `KnowledgeBaseVectorStore` from `OPENSEARCH_SERVERLESS` to `S3_VECTORS` for cost-optimized deployments
  - S3 Vectors provides 40-60% lower storage costs with sub-second latency suitable for most use cases
  - OpenSearch Serverless remains available for applications requiring sub-millisecond query performance
  - No action required for existing deployments - only affects new stack deployments

### Fixed

- **UI: Document Schema Editor Regex Fields Not Persisting** - Fixed issue where Document Name Regex and Page Content Regex fields were not being saved in configuration or restored after page refresh. Fixes #151
- **Document Schema Builder Enum Support** - Fixed enum value handling in schema builder to properly support enumeration constraints for attribute definitions
- **Agentic Extraction Parameter Passing** - Fixed temperature and top_p parameters now correctly passed to agentic extraction service, enabling proper model behavior control
- **Document Schema Builder UI Labels** - Enhanced field labels and formats in document schema builder for improved clarity and user experience
- **Retry Mechanism Improvements** - Enhanced retry logic for more reliable error handling and recovery across document processing workflows
- **Type Safety Enhancements** - Improved type annotations and fixed undefined items handling to prevent runtime errors

### Templates
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.4.6.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main_0.4.6.yaml`
   - eu-central-1: `https://s3.eu-central-1.amazonaws.com/aws-ml-blog-eu-central-1/artifacts/genai-idp/idp-main_0.4.6.yaml`


## [0.4.5]

### Added

- **Document Split Classification Metrics for Evaluating Page-Level Classification and Document Segmentation**
  - Added `DocSplitClassificationMetrics` class for comprehensive evaluation of document splitting and classification accuracy
  - **Three Accuracy Types**: Page-level classification accuracy, split accuracy without order consideration, and split accuracy with exact page order matching
  - **Visual Reporting**: Generates markdown reports with color-coded indicators (🟢 Excellent, 🟡 Good, 🟠 Fair, 🔴 Poor), progress bars, and detailed section analysis tables
  - **Automatic Integration**: Integrates with evaluation service when ground truth and predicted sections are available
  - **Documentation**: Guide in `lib/idp_common_pkg/idp_common/evaluation/README.md` with usage examples, metric explanations, and best practices

- **Caching improvements to Agentic Extraction Service**
  - Optimized prompt caching by caching document context (text/images) on first LLM call, reducing token costs and quota consumption

- **Enhanced Bedrock Retry Logic for Agentic Extraction**
  - New `bedrock_utils.py` module with exponential backoff and comprehensive error handling
  - Improves agentic extraction reliability for transient failures and rate limiting

- **Review Agent Model Configuration**
  - Added `review_agent_model` parameter to enable separate model for reviewing extraction work
  - Defaults to main extraction model if not specified
  - Configurable through Web UI extraction settings


### Fixed

- **Evaluation Output URI Fields Lost Across All Patterns - causing (a) missing Page Text Confidence content in UI, (2) failed Assessment step when reprocessing document after editing classes (No module named 'fitz')**
  - Fixed bug where `text_confidence_uri` was being set to null in evaluation output for all three patterns
  - Root cause: AppSync service `_appsync_to_document()` method incorrectly mapped page URIs, and evaluation functions overwrote correct documents with corrupted AppSync responses

- **UI: Metering Data Not Displayed During Document Processing**
  - Fixed UI subscription query missing `Metering` field, preventing real-time cost display
  - Users can now see estimated costs accumulate in real-time without manual page refresh

- **UI: Estimated Cost Panel Arrow Misalignment**
  - Fixed expand/contract arrow displaying above "Estimated Cost" heading

- **Agentic Extraction Reliability Improvements**
  - Updated Pydantic model serialization to use `model_dump(mode="json")` for proper JSON handling
  - Resolved linting issues and improved code quality across extraction modules

### Templates
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.4.5.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main_0.4.5.yaml`
   - eu-central-1: `https://s3.eu-central-1.amazonaws.com/aws-ml-blog-eu-central-1/artifacts/genai-idp/idp-main_0.4.5.yaml`


## [0.4.4]

### Added

- **IDP CLI --from-code Flag for Local Development Deployment**
  - Added `--from-code` flag to `idp-cli deploy` command enabling deployment directly from local source code
  - Automatically builds project using `publish.py` script with streaming output for real-time build progress
- **IDP CLI --no-rollback Flag for Stack Deployment Troubleshooting**
  - Added `--no-rollback` flag to `idp-cli deploy` command to disable automatic rollback on CloudFormation stack creation failure
  - When enabled, failed stacks remain in `CREATE_FAILED` state instead of rolling back, allowing inspection of failed resources for troubleshooting

- **Add support for prompt caching for Claude Haiku 4.5**

- **Add support for prompt caching for for EU region models**

### Fixed

- **Analytics Agent Schema Provider - Fixed Nested Attribute Column Display**
  - Fixed `schema_provider.py` to correctly display leaf-level nested columns instead of showing group-level attributes

- **IDP Agent Companion Chat UX improvements**
  - Improved speed of rendering chat response by buffering the agent tool responses.
  - Displaying agent tool queries and results in a modal with formatted results.


### Templates
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.4.4.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main_0.4.4.yaml`
   - eu-central-1: `https://s3.eu-central-1.amazonaws.com/aws-ml-blog-eu-central-1/artifacts/genai-idp/idp-main_0.4.4.yaml`

## [0.4.3]

### Fixed

- Fix #134 - Doc class dropdown shows no options when editing sections
- Fix #133 - Cast topK to int to defend against transient ValidationException exceptions
- Fix #132 - TRACKING_TABLE environment variable needed in EvaluationFunction
- Fix #131 - HITL functions broken post docker migration
- Fix #130 - Enable EU models for Agent Configuration and KB Configuration
- Add ServiceUnavailableException to retryable exceptions in statemachine to better defend against processing failure due to quota overload
- Evaluation Configuration Robustness
  - Improved JSON Schema error messages with actionable diagnostics when configuration issues occur
  - Added automatic type coercion for numeric constraints (e.g., `maxItems: "7"` → `maxItems: 7`) to handle common YAML parsing quirks gracefully
- UI: Document Schema Editor Input Field Fixes
  - Fixed Examples, Default Value, Const, and Enum Values fields not allowing first character deletion or comma input
  - Fixed Enum field remaining disabled after clearing Const value
  - Fixed "Clear all enum values" button not working
  - Fixed empty Evaluation Method picklist for Array[String] and other simple array types

### Templates
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.4.3.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main_0.4.3.yaml`
   - eu-central-1: `https://s3.eu-central-1.amazonaws.com/aws-ml-blog-eu-central-1/artifacts/genai-idp/idp-main_0.4.3.yaml`

## [0.4.2]

### Added

- **Stickler-Based Evaluation System for Enhanced Comparison Capabilities**
  - Migrated evaluation service from custom comparison logic to [AWS Labs Stickler library](https://github.com/awslabs/stickler/tree/main) for structured object evaluation
  - **Field Importance Weights**: New capability to assign business criticality weights to fields (e.g., shipment ID weight=3.0 vs notes weight=0.5)
  - **Enhanced Configuration**: Added `x-aws-idp-evaluation-*` extensions for evaluation configuration
  - **Backward compatible**: Maintained API compatibility - all existing code works unchanged
  - **Enhanced Comparators**: Leverages Stickler's optimized comparison algorithms (Exact, Levenshtein, Numeric, Fuzzy, Semantic) with LLM evaluation preserved through custom wrapper
  - **Better List Matching**: Hungarian algorithm via Stickler for optimal list comparisons regardless of order

- **UI: Evaluation Configuration in Document Schema UI**
  - Added evaluation weight, threshold (with conditional display), and document-level match threshold fields for complete Stickler configuration control
  - Added LEVENSHTEIN and HUNGARIAN evaluation methods with auto-populated threshold defaults based on selected method
  
- **IDP CLI Force Delete All Resources Option**
  - Added `--force-delete-all` flag to `idp-cli delete` command for comprehensive stack cleanup
  - **Post-CloudFormation Cleanup**: Analyzes resources after CloudFormation deletion completes to identify retained resources (DELETE_SKIPPED status)
  - **Use Cases**: Complete test environment cleanup, CI/CD pipelines requiring full teardown, cost optimization by removing all retained resources

### Changed

- **Containerized Pattern-1 and Pattern-3 Deployment Pipelines**
  - Migrated Pattern-1 and Pattern-3 Lambda functions to Docker image deployments (following Pattern-2 approach from v0.3.20)
  - Builds and pushes all Lambda images via CodeBuild with automated ECR cleanup
  - Increases Lambda package size limit from 250 MB (zip) to 10 GB (Docker image) to accommodate larger dependencies

- **Agent Companion Chat - Chat History Feature**
  - Added chat history feature from Agent Analysis back into Agent Companion Chat
  - Users can now load and view previous chat sessions with full conversation context
  - Chat history dropdown displays recent sessions with timestamps and message counts

### Fixed

- **Agent Companion Chat - Session Persistence and input control**
  - Agent Companion Chat in-session memory now persists even when user changes pages
  - Prompt input is disabled during active streaming responses to prevent concurrent requests
  - Fixed issue where charts in loaded chat history were not displaying

- **GovCloud Template Generation errors**
  - Fixed CloudFormation deployment error `Fn::GetAtt references undefined resource GraphQLApi` when deploying GovCloud templates

- **Example Notebook error fixed**
  - Example notebooks updated to work with new v0.4.0+ JSON schema


### Templates
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.4.2.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main_0.4.2.yaml`
   - eu-central-1: `https://s3.eu-central-1.amazonaws.com/aws-ml-blog-eu-central-1/artifacts/genai-idp/idp-main_0.4.2.yaml`

## [0.4.1]

### Changed

- **Configuration Library Updates with JSON Schema Support**
  - Updated configuration library with JSON schema format for lending package, bank statement, and RVL-CDIP package samples
  - Enhanced configuration files to align with JSON Schema Draft 2020-12 format introduced in v0.4.0
  - Updated notebooks and documentation to reflect JSON schema configuration structure

### Fixed

- **UI Few Shot Examples Display** - Fixed issue where few shot examples were not displaying correctly from configuration in the Web UI
- **Re-enabled Regex Functionality** - Restored document name and page content regex functionality for Pattern-2 classification that was temporarily missing
- **Pattern-2 ECR Enhanced Scanning Support** - Added required IAM permissions (inspector2:ListCoverage, inspector2:ListFindings) to Pattern2DockerBuildRole to support AWS accounts with Amazon Inspector Enhanced Scanning enabled. Also added KMS permissions (kms:Decrypt, kms:CreateGrant) for customer-managed encryption keys. This resolves AccessDenied errors and CodeBuild timeouts when deploying Pattern-2 in accounts with enhanced scanning enabled.
- **Reporting Database Data Loss After Evaluation Refactoring - Fixes #121**
  - Fixed bug where metering data and document_section data stopped being written to the reporting database after evaluation was migrated from EventBridge to Step Functions workflow
- **IDP CLI Deploy Command Parameter Preservation Bug**
  - Fixed bug where `idp-cli deploy` command was resetting ALL stack parameters to their default values during updates, even when users only intended to change specific parameters
- **Pattern-2 Deployment Intermittent Lambda (HITLStatusUpdateFunction) ECR Access Failure**
  - Fixed intermittent "Lambda does not have permission to access the ECR image" (403) errors during Pattern-2 deployment
  - **Root Cause**: Race condition where Lambda functions were created before ECR images were fully available and scannable
  - **Solution**: Enhanced CodeBuild custom resource to verify ECR image availability before completing, including:
    - Verification that all required Lambda images exist in ECR repository
    - Check that image scanning is complete (repository has `ScanOnPush: true`)
  - **New Parameter**: Added `EnablePattern2ECRImageScanning` parameter (current default: false) to allow users to enable/disable ECR vulnerability scanning if experiencing deployment issues
    - Recommended: Set enabled (true) for production to maintain security posture
    - Optional: Disable (false) only as temporary workaround for deployment reliability
- **Resolved failing Docker build issue related to Python pymupdf package version update**
  - Pinned pymupdf version to prevent attempted (failing) deployment of newly published version (which is missing ARM64 wheels)

### Templates
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.4.1.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main_0.4.1.yaml`
   - eu-central-1: `https://s3.eu-central-1.amazonaws.com/aws-ml-blog-eu-central-1/artifacts/genai-idp/idp-main_0.4.1.yaml`

## [0.4.0]

> **⚠️ IMPORTANT NOTICE - SIGNIFICANT CONFIGURATION CHANGES**
>
> This release introduces **significant changes to the accelerator configuration** for defining document classes and attributes. The configuration format has been migrated to JSON Schema standards, which provides enhanced flexibility and validation capabilities.
>
> While automatic migration is provided for backward compatibility, **customers MUST fully test this update in a non-production environment** before upgrading production systems. We strongly recommend:
>
> 1. Deploy the update to a test/development environment first
> 2. Verify all document processing workflows function as expected
> 3. Test with representative samples of your production documents
> 4. Review the migration guide at [docs/json-schema-migration.md](./docs/json-schema-migration.md)
> 5. Only proceed with production upgrade after thorough validation
>
> **Do not upgrade production systems without completing validation testing.**

### Added

- **Agent Companion Chat Experience**
  - Added comprehensive interactive AI assistant interface providing real-time conversational support for the IDP Accelerator
  - **Session-Based Architecture**: Transformed from job-based (single request/response) to session-based (multi-turn conversations) with unified agentic chat experience
  - **Persistent Chat Memory**: DynamoDB-backed conversation history with automatic loading of last 20 turns, turn-based message grouping, and intelligent context management with sliding window optimization
  - **Real-Time Streaming**: AppSync GraphQL subscriptions enable incremental response streaming with proper async task cleanup and thinking tag removal for clean display
  - **Code Intelligence Agent**: New specialized agent for code-related assistance with DeepWiki MCP server integration, security guardrails to prevent sensitive data exposure, and user-controlled opt-in toggle (default: enabled)
  - **Rich Chat Interface**: Modern UI with CloudScape Design System featuring real-time message streaming, multi-agent support (Analytics, Code Intelligence, Error Analyzer, General), Markdown rendering with syntax highlighting, structured data visualization (charts via Chart.js, sortable tables), expandable tool usage sections, sample prompts, and auto-scroll behavior
  - **Privacy & Security**: Explicit user consent for Code Intelligence third-party services, session isolation with unique session IDs, error boundary protection, input validation

- **JSON Schema Format for Class Definitions** - [docs/json-schema-migration.md](./docs/json-schema-migration.md)
  - Document class definitions now use industry-standard JSON Schema Draft 2020-12 format for improved flexibility and tooling integration
  - **Standards-Based Validation**: Leverage standard JSON Schema validators and tooling ecosystem for better configuration validation
  - **Enhanced Extensibility**: Custom IDP properties use standard JSON Schema extension pattern (`x-aws-idp-*` prefix) for clean separation of concerns
  - **Modern Data Contract**: Define document structures using widely-adopted JSON Schema format with robust type system (`string`, `number`, `boolean`, `object`, `array`)
  - **Nested Structure Support**: Natural representation of complex documents with nested objects and arrays using JSON Schema's native `properties` and `items` keywords
  - **Automatic Migration**: Existing legacy configurations automatically migrate to JSON Schema format on first load - completely transparent to users
  - **Backward Compatible**: Legacy format remains supported through automatic migration - no manual configuration updates required
  - **Comprehensive Documentation**: New migration guide with format comparison, field mapping table, and best practices

- **IDP CLI Single Document Status Support with Programmatic Output**
  - Enhanced `status` command to support checking individual document status via new `--document-id` option as alternative to `--batch-id`
  - Added programmatic output capabilities with exit codes (0=success, 1=failure, 2=processing) for scripting and automation
  - JSON format output (`--format json`) provides structured data for parsing in CI/CD pipelines and scripts
  - Live monitoring support with `--wait` flag works for both batch and single document status checks
  - Mutual exclusion validation ensures only one of `--batch-id` or `--document-id` is specified
- **Error Analyzer CloudWatch Tool Enhancements**
  - Enhanced CloudWatch log filtering with request ID-based filtering for more targeted error analysis
  - Improved XRay tool tracing and logging capabilities for better diagnostic accuracy
  - Enhanced error context correlation between CloudWatch logs and X-Ray traces
  - Consolidated and renamed tools
  - Provided tools access to agent
  - Updated system prompt

- **Error Analyzer CloudWatch Tool Enhancements**
  - Enhanced CloudWatch log filtering with request ID-based filtering for more targeted error analysis
  - Improved XRay tool tracing and logging capabilities for better diagnostic accuracy
  - Enhanced error context correlation between CloudWatch logs and X-Ray traces
  - Consolidated and renamed tools
  - Provided tools access to agent
  - Updated system prompt


### Fixed

- **UI Robustness for Orphaned List Entries** - [#102](https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws/issues/102)
  - Fixed UI error banner "failed to get document details - please try again later" appearing when orphaned list entries exist (list# items without corresponding doc# items in DynamoDB tracking table)
  - **Root Cause**: When a document had a list entry but no corresponding document record, the error would trigger UI banner and prevent display of all documents in the same time shard
  - **Solution**: Enhanced error handling to gracefully handle missing documents - now only shows error banner if ALL documents fail to load, not just one
  - **Enhanced Debugging**: Added detailed console logging with full PK/SK information for both list entries and expected document entries to facilitate cleanup of orphaned records
  - **User Impact**: All valid documents now display correctly even when orphaned list entries exist; debugging information available in browser console for identifying problematic entries

### Templates
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.4.0.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main_0.4.0.yaml`
   - eu-central-1: `https://s3.eu-central-1.amazonaws.com/aws-ml-blog-eu-central-1/artifacts/genai-idp/idp-main_0.4.0.yaml`

## [0.3.21]

### Added

- **Claude Sonnet 4.5 Haiku Model Support**
  - Added support for Claude Haiku 4.5
  - Available for configuration across all document processing steps

- **X-Ray Integration for Error Analyzer Agent**
  - Integrated AWS X-Ray tracing tools to enhance diagnostic capabilities of the error analyzer agent
  - X-Ray context enables better distinction between infrastructure issues and application logic failures
  - Added trace ID persistence in DynamoDB alongside document status for complete traceability
  - Enhanced CloudWatch error log filtering for more targeted error analysis
  - Simplified CloudWatch results structure for improved readability and analysis
  - Updated error analyzer recommendations to leverage X-Ray insights for more accurate root cause identification

- **EU Region Support with Automatic Model Mapping**
  - Added support for deploying the solution in EU regions (eu-central-1, eu-west-1, etc.)
  - Automatic model endpoint mapping between US and EU regions for seamless deployment
  - Comprehensive model mapping table covering Amazon Nova and Anthropic Claude models
  - Intelligent fallback mappings when direct EU equivalents are unavailable
  - Quick Launch button for eu-central-1 region in README and deployment documentation
  - IDP CLI now supports eu-central-1 deployment with automatic template URL selection
  - Complete technical documentation in `docs/eu-region-model-support.md` with best practices and troubleshooting

### Changed

- **Migrated Evaluation from EventBridge Trigger to Step Functions Workflow**
  - Moved evaluation processing from external EventBridge-triggered Lambda to integrated Step Functions workflow step
  - **Race Condition Eliminated**: Evaluation now runs inside state machine before WorkflowTracker marks documents COMPLETE, preventing premature completion status when evaluation is still running
  - **Config-Driven Control**: Evaluation now controlled by `evaluation.enabled` configuration setting instead of CloudFormation stack parameter, enabling runtime control without stack redeployment
  - **Enhanced Status Tracking**: Added EVALUATING status to document processing pipeline for better visibility of evaluation progress
  - **UI Improvements**: Added support for displaying EVALUATING status in processing flow viewer and "NOT ENABLED" badge when evaluation is disabled in configuration
  - **Consistent Pattern**: Aligns evaluation with summarization and assessment patterns for unified feature control approach


- **Migrated UI Build System from Create React App to Vite**
  - Upgraded to Vite 7 for faster build times
  - Updated to React 18, AWS Amplify v6, react-router-dom v6, and Cloudscape Design System
  - Reduced dependencies and node_modules size
  - Implemented strategic code splitting for improved performance
  - Environment variables now use `VITE_` prefix instead of `REACT_APP_` for local development

### Fixed

- **IDP CLI Code Cleanup and Portability Improvements** - [#91](https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws/issues/91), [#92](https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws/issues/92)
  - Removed dead code from previous refactors in batch_processor.py (51 lines)
  - Replaced hardcoded absolute paths with dynamic path resolution in rerun_processor.py for cross-platform compatibility

### Templates
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.3.21.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main_0.3.21.yaml`
   - eu-central-1: `https://s3.eu-central-1.amazonaws.com/aws-ml-blog-eu-central-1/artifacts/genai-idp/idp-main_0.3.21.yaml`

## [0.3.20]

### Added

- **Agentic extraction preview with Strands agents (experimental)** introducing intelligent, self-correcting document extraction with improved schema compliance and accuracy improvements over traditional methods.
  - Leverages the Strands Agent framework with iterative validation loops and automatic error correction to deliver schema compliance
  - Provides structured output through Pydantic models with built-in validators, automatic retry handling, and superior handling of complex nested structures and date standardization
  - Includes sample notebooks and configuration assets demonstrating agentic extraction for Pattern-2 lending documents
  - Programmatic access available via `structured_output` function in `lib/idp_common_pkg/idp_common/extraction/agentic_idp.py`
  - Currently this is an experimental feature. Future extensibility includes UI-based validation customization, code generation, and Model Context Protocol (MCP) integration for external data enrichment during extraction

- **IDP CLI - Command Line Interface for Batch Document Processing**
  - Added CLI tool (`idp_cli/`) for programmatic batch document processing and stack management
  - **Key Features**: Deploy/update/delete CloudFormation stacks, process and reprocess documents from local directories or S3 URIs, live progress monitoring with rich terminal UI, download processing results locally, validate manifests before processing, generate manifests from directories with automatic baseline matching
  - **Selective Reprocessing**: New `rerun-inference` command to reprocess documents from specific pipeline steps (classification or extraction) while leveraging existing OCR data for cost/time optimization
  - **Evaluation Framework**: Workflow for accuracy testing including initial processing, manual validation, baseline creation, and automated evaluation with detailed metrics
  - **Analytics Integration**: Query aggregated results via Athena SQL or use Agent Analytics in Web UI for visual analysis
  - **Use Cases**: Rapid configuration iteration, large-scale batch processing, CI/CD integration, automated accuracy testing, automated environment cleanup, prompt engineering experiments
  - **Documentation**: README with Quick Start, Commands Reference, Evaluation Workflow, and troubleshooting guides

- **Extraction Results Integration in Summarization Service**
  - Integrates extraction results from the extraction service into summarization module for context-aware summaries
  - **Features**: Fully backward compatible (works with or without extraction results), automatic section handling, error resilient with graceful continuation, comprehensive logging
  - **Configuration**: Enable by adding `{EXTRACTION_RESULTS}` placeholder to `task_prompt` in config.yaml
  - **Benefits**: Context-aware summaries referencing extracted values, improved accuracy and quality, better extraction-summary alignment

### Changed

- **Containerized Pattern-2 deployment pipeline** that builds and pushes all Lambda images via CodeBuild using the new Dockerfile, plus automated ECR cleanup and tests.
  - Lambda docker image deployments have a 10 GB image size limit compared to the 250 MB zip limit of regular deployment. This however doesn't allow for viewing the code in the AWS console.
    The change was introduced to accommodate the increased package size of introducing Strands into the package dependencies.

### Fixed
- **Discovery function times out when processing large documents.**
  - increase lambda discovery processor timeout to 900s
- **Corrected baseline directory structure documentation in evaluation.md**
  - Fixed incorrect baseline structure showing flat `.json` files instead of proper directory hierarchy
  - Updated to correct structure: `<document-name>/sections/1/result.json`
  - Reorganized document for better logical flow and user experience
- **GovCloud Template Generation - Removed GraphQLApi References** - #82
  - Fixed invalid GovCloud template generation where ProcessChanges AppSync resources were not being removed, causing "Fn::GetAtt references undefined resource GraphQLApi" errors
  - Updated `scripts/generate_govcloud_template.py` to remove all ProcessChanges-related resources and extend AppSync parameter cleanup to all pattern stacks
  - Fixed InvalidClientTokenId validation error by ensuring CloudFormation client uses the correct region when validating templates (commercial vs GovCloud)
- **Enhanced Processing Flow Visualization for Disabled Steps**
  - Fixed UX issue where disabled processing steps (when `summarization.enabled: false` or `assessment.enabled: false` in configuration) appeared visually identical to active steps in the "View Processing Flow" display
  - **Key Benefit**: Users can now immediately see which steps are actually processing data vs. steps that execute but skip processing based on configuration settings, preventing confusion about whether summarization or assessment ran
  - Limitation: the new visual indicators are driven from the current config, which may have been altered since the document was processed. We will address this in a later release. See Issue #86.

### Known Issues
- **GovCloud Deployments fail, due to lack of ARM support for CodeBuild. Fix targeted for next release.**

### Templates
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.3.20.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main_0.3.20.yaml`

## [0.3.19]

### Added

- **Error Analyzer (Troubleshooting Tool) for AI-Powered Failure Diagnosis**
  - Introduced intelligent AI-powered troubleshooting agent that automatically diagnoses document processing failures using Claude Sonnet 4 with the Strands agent framework
  - **Key Capabilities**: Natural language query interface, intelligent routing between document-specific and system-wide analysis, multi-source data correlation (CloudWatch Logs, DynamoDB, Step Functions), root cause identification with actionable recommendations, evidence-based analysis with collapsible log details
  - **Web UI Integration**: Accessible via "Troubleshoot" button on failed documents with real-time job status, progress tracking, automatic job resumption, and formatted results (Root Cause, Recommendations, Evidence sections)
  - **Tool Ecosystem**: 8 specialized tools including analyze_errors (main router), analyze_document_failure, analyze_recent_system_errors, CloudWatch log search tools, DynamoDB integration tools, and Lambda context retrieval - additional tools will be added as the feature evolves.
  - **Configuration**: Configurable via Web UI including model selection (Claude Sonnet 4 recommended), system prompt customization, max_log_events (default: 5), and time_range_hours_default (default: 24)
  - **Documentation**: Comprehensive guide in `docs/error-analyzer.md` with architecture diagrams, usage examples, best practices, troubleshooting guide.

- **Claude Sonnet 4.5 Model Support**
  - Added support for Claude Sonnet 4.5 and Claude Sonnet 4.5 - Long Context models
  - Available for configuration across all document processing steps

### Fixed

- **Problem with setting correctly formatted WAF IPv4 CIDR range** - #73

- **Duplicate Step Functions Executions on Document Reprocess - [GitHub Issue #66](https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws/issues/66)**
  - Eliminated duplicate workflow executions when reprocessing large documents (>40MB, 500+ pages)
  - **Root Cause**: S3 `copy_object` operations were triggering multiple "Object Created" events for large files, causing `queue_sender` to create duplicate document entries and workflow executions
  - **Solution**: Refactored `reprocess_document_resolver` to directly create fresh Document objects and queue to SQS, completely bypassing S3 event notifications
  - **Benefits**: Eliminates unnecessary S3 copy operations (cost savings)

### Templates
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.3.19.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main_0.3.19.yaml`

## [0.3.18]

### Added

- **Lambda Function Execution Cost Metering for Complete Cost Visibility**
  - Added Lambda execution cost tracking to all core processing functions across all three processing patterns
  - **Dual Metrics**: Tracks both invocation counts ($0.20 per 1M requests) and GB-seconds duration ($16.67 per 1M GB-seconds) aligned with official AWS Lambda pricing
  - **Context-Specific Tracking**: Separate cost attribution for each processing step enabling granular cost analysis per document processing context
  - **Automatic Integration**: Lambda costs automatically integrate with existing cost reporting infrastructure and appear alongside AWS service costs (Textract, Bedrock, SageMaker)
  - **Configuration Integration**: Added Lambda pricing entries to all 7 configuration files in `config_library/` using official US East pricing

### Fixed

- Defect in v0.3.17 causing workflow tracker failure to (1) update status of failed workflows, and (2) update reporting database for all workflows #72

### Templates
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.3.18.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main_0.3.18.yaml`

## [0.3.17]

### Added

- **Edit Sections Feature for Modifying Class/Type and Reprocessing Extraction**
  - Added Edit Sections interface for Pattern-2 and Pattern-3 workflows with reprocessing optimization
  - **Key Features**: Section management (create, update, delete), classification updates, page reassignment with overlap detection, real-time validation
  - **Selective Reprocessing**: Only modified sections are reprocessed while preserving existing data for unmodified sections
  - **Processing Pipeline**: All functions (OCR/Classification/Extraction/Assessment) automatically skip redundant operations based on data presence
  - **Pattern Compatibility**: Full functionality for Pattern-2/Pattern-3, informative modal for Pattern-1 explaining BDA not yet supported

- **Analytics Agent Schema Optimization for Improved Performance**
  - **Embedded Database Overview**: Complete table listing and guidance embedded directly in system prompt (no tool call needed)
  - **On-Demand Detailed Schemas**: `get_table_info(['specific_tables'])` loads detailed column information only for tables actually needed by the query
  - **Significant Performance Gains**: Eliminates redundant tool calls on every query while maintaining token efficiency
  - **Enhanced SQL Guidance**: Comprehensive Athena/Trino function reference with explicit PostgreSQL operator warnings to prevent common query failures like `~` regex operator mistakes
  - **Faster Time-to-Query**: Agent has immediate access to table overview and can proceed directly to detailed schema loading for relevant tables

### Changed

- Add UI code lint/validation to publish.py script

### Fixed

- Fix missing data in Glue tables when using a document class that contains a dash (-).
- Added optional Bedrock Guardrails support to (a) Agent Analytics and (b) Chat with Document
- Fixed regressions on Permission Boundary support for all roles, and added autimated tests to prevent recurrance - fixes #70

### Templates
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.3.17.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main_0.3.17.yaml`

## [0.3.16]

### Added

- **S3 Vectors Support for Cost-Optimized Knowledge Base Storage**
  - Added S3 Vectors as alternative vector store option to OpenSearch Serverless for Bedrock Knowledge Base with lower storage costs
  - Custom resource Lambda implementation for S3 vector bucket and index management (using boto3 s3vectors client) with proper IAM permissions and resource cleanup
  - Unified Knowledge Base interface supporting both vector store types with automatic resource provisioning based on user selection

- **Page Limit Configuration for Classification Control**
  - Added `maxPagesForClassification` configuration option to control how many pages are used during document classification
  - **Default Behavior**: `"ALL"` - uses all pages for classification (existing behavior)
  - **Limited Page Classification**: Set to numeric value (e.g., `"1"`, `"2"`, `"3"`) to classify only the first N pages
  - **Important**: When using numeric limit, the classification result from the first N pages is applied to ALL pages in the document, effectively forcing the entire document to be assigned a single class with one section
  - **Use Cases**: Performance optimization for large documents, cost reduction for documents with consistent classification patterns, simplified processing for homogeneous document types

- **CloudFormation Service Role for Delegated Deployment Access**
  - Added example CloudFormation service role template that enables non-administrator users to deploy and maintain IDP stacks without requiring ongoing administrator permissions
  - Administrators can provision the service role once with elevated privileges, then delegate deployment capabilities to developer/DevOps teams
  - Includes comprehensive documentation and cross-referenced deployment guides explaining the security model and setup process

### Fixed

- Fixed issue where CloudFront policy statements were still appearing in generated GovCloud templates despite CloudFront resources being removed
- Fix duplicate Glue tables are created when using a document class that contains a dash (-). Resolved by replacing dash in section types with underscore character when creating the table, to align with the table name generated later by the Glue crawler - resolves #57.
- Fix occasional UI error 'Failed to get document details - please try again later' - resolves #58
- Fixed UI zipfile creation to exclude .aws-sam directories and .env files from deployment package
- Added security recommendation to set LogLevel parameter to WARN or ERROR (not INFO) for production deployments to prevent logging of sensitive information including PII data, document contents, and S3 presigned URLs
- Hardened several aspects of the new Discovery feature

### Templates
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.3.16.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main_0.3.16.yaml`

## [0.3.15]

### Added

- **Intelligent Document Discovery Module for Automated Configuration Generation**
  - Added Discovery module that automatically analyzes document samples to identify structure, field types, and organizational patterns
  - **Pattern-Neutral Design**: Works across all processing patterns (1, 2, 3) with unified discovery process and pattern-specific implementations
  - **Dual Discovery Methods**: Discovery without ground truth (exploratory analysis) and with ground truth (optimization using labeled data)
  - **Automated Blueprint Creation**: Pattern 1 includes zero-touch BDA blueprint generation with intelligent change detection and version management
  - **Web UI Integration**: Real-time discovery job monitoring, interactive results review, and seamless configuration integration
  - **Advanced Features**: Multi-model support (Nova, Claude), customizable prompts, configurable parameters, ground truth processing, schema conversion, and lifecycle management
  - **Key Benefits**: Rapid new document type onboarding, reduced time-to-production, configuration optimization, and automated workflow bootstrapping
  - **Use Cases**: New document exploration, configuration improvement, rapid prototyping, and document understanding
  - **Documentation**: Guide in `docs/discovery.md` with architecture details, best practices, and troubleshooting

- **Optional Pattern-2 Regex-Based Classification for Enhanced Performance**
  - Added support for optional regex patterns in document class definitions for performance optimization
  - **Document Name Regex**: Match against document ID/name to classify all pages without LLM processing when all pages should be the same class
  - **Document Page Content Regex**: Match against page text content during multi-modal page-level classification for fast page classification
  - **Key Benefits**: Significant performance improvements and cost savings by bypassing LLM calls for pattern-matched documents, deterministic classification results for known document patterns, seamless fallback to existing LLM classification when regex patterns don't match
  - **Configuration**: Optional `document_name_regex` and `document_page_content_regex` fields in class definitions with automatic regex compilation and validation
  - **Logging**: Comprehensive info-level logging when regex patterns match for observability and debugging
  - **CloudFormation Integration**: Updated Pattern-2 schema to support regex configuration through the Web UI
  - **Demonstration**: New `step2_classification_with_regex.ipynb` notebook showcasing regex configuration and performance comparisons
  - **Documentation**: Enhanced classification module README and main documentation with regex usage examples and best practices
- **Windows WSL Development Environment Setup Guide**
  - Added WSL-based development environment setup guide for Windows developers in `docs/setup-development-env-WSL.md`
  - **Key Features**: Automated setup script (`wsl_setup.sh`) for quick installation of Git, Python, Node.js, AWS CLI, and SAM CLI
  - **Integrated Workflow**: Development setup combining Windows tools (VS Code, browsers) with native Linux environment
  - **Target Use Cases**: Windows developers needing Linux compatibility without Docker Desktop or VM overhead

### Fixed

- **Throttling Error Detection and Retry Logic for Assessment Functions** - [GitHub Issue #45](https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws/issues/45)
  - **Assessment Function**: Enhanced throttling detection to check for throttling errors returned in `document.errors` field in addition to thrown exceptions, raising `ThrottlingException` to trigger Step Functions retry when throttling is detected
  - **Granular Assessment Task Caching**: Fixed caching logic to properly cache successful assessment tasks when there are ANY failed tasks (both exception-based and result-based failures), enabling efficient retry optimization by only reprocessing failed tasks while preserving successful results
  - **Impact**: Improved resilience for throttling scenarios, reduced redundant processing during retries, and better Step Functions retry behavior

- **Security Vulnerability Mitigation - Package Updates**

- **GovCloud Compatibility - Hardcoded Service Domain References**
  - Fixed hardcoded `amazonaws.com` references in CloudFormation templates that prevented GovCloud deployment
  - Updated all service principals and endpoints to use dynamic `${AWS::URLSuffix}` expressions for automatic region-based resolution
  - **Templates Updated**: `template.yaml` (main template), `patterns/pattern-3/sagemaker_classifier_endpoint.yaml`
  - **Services Fixed**: EventBridge, Cognito, SageMaker, ECR, CloudFront, CodeBuild, AppSync, Lambda, DynamoDB, CloudWatch Logs, Glue
  - Resolves GitHub Issue #50 - templates now deploy correctly in both standard AWS and GovCloud regions

- **Bug Fixes and Code Improvements**
  - Fixed HITL processing errors in both Pattern-1 (DynamoDB validation with empty strings) and Pattern-2 (string indices error in A2I output processing)
  - Fixed Step Function UI issues including auto-refresh button auto-disable and fetch failures for failed executions with datetime serialization errors
  - Cleaned up unused Step Function subscription infrastructure and removed duplicate code in Pattern-2 HITL function
  - Expanded UI Visual Editor bounding box size with padding for better visibility and user interaction
  - Fixed bug in list of models supporting cache points - previously claude 4 sonnet and opus had been excluded.
  - Validations added at the assessment step for checking valid json response. The validation fails after extraction/assessment is complete if json parsing issues are encountered.

### Templates
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.3.15.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main_0.3.15.yaml`

## [0.3.14]

### Added

- Support for 1m token context for Claude Sonnet 4
- Video demo of "Chat with Document" in [./docs/web-ui.md](./docs/web-ui.md)
- **Human-in-the-Loop (HITL) Support Extended to Pattern-2**
  - Added HITL review capabilities for Pattern-2 (Textract + Bedrock processing) using Amazon SageMaker Augmented AI (A2I)
  - Enables human validation and correction when extraction confidence falls below configurable threshold
  - Includes same features as Pattern-1 HITL: automatic triggering, review portal integration, and seamless result updates
  - Documentation and video demo in [./docs/human-review.md](./docs/human-review.md)

### Removed

- Windows development environment guide and setup script removed as it proved insufficiently robust

### Fixed

- Fix 1-click Launch URL output from the GovCloud template generation script
- Add Agent Analytics to architecture diagram
- Fix various UX and error reporting issues with the new Python publish script
- Simplify UDOP model path construction and avoid invalid default for regions other than us-east-1 and us-west-2
- Permission regression from previous release affecting "Chat with Document"

### Templates
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.3.14.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main_0.3.14.yaml`

## [0.3.13]

### Added

- **External MCP Agent Integration for Custom Tool Extension**
  - Added External MCP (Model Context Protocol) Agent support that enables integration with custom MCP servers to extend IDP capabilities
  - **Cross-Account Integration**: Host MCP servers in separate AWS accounts or external infrastructure with secure OAuth authentication using AWS Cognito
  - **Dynamic Tool Discovery**: Automatically discovers and integrates available tools from MCP servers through the IDP web interface
  - **Secure Authentication Flow**: Uses AWS Cognito User Pools for OAuth bearer token authentication with proper token validation
  - **Configuration Management**: JSON array configuration in AWS Secrets Manager supporting multiple MCP server connections with optional custom agent names and descriptions
  - **Real-time Integration**: Tools become immediately available through the IDP web interface after configuration

- **AWS GovCloud Support with Automated Template Generation**
  - Added GovCloud compatibility through `scripts/generate_govcloud_template.py` script
  - **ARN Partition Compatibility**: All templates updated to use `arn:${AWS::Partition}:` for both commercial and GovCloud regions
  - **Headless Operation**: Automatically removes UI-related resources (CloudFront, AppSync, Cognito, WAF) for GovCloud deployment
  - **Core Functionality Preserved**: All 3 processing patterns and complete 6-step pipeline (OCR, Classification, Extraction, Assessment, Summarization, Evaluation) remain fully functional
  - **Automated Workflow**: Single script orchestrates build + GovCloud template generation + S3 upload with deployment URLs
  - **Enterprise Ready**: Enables headless document processing for government and enterprise environments requiring GovCloud compliance
  - **Documentation**: New `docs/govcloud-deployment.md` with deployment guide, architecture differences, and access methods

- **Pattern-2 and Pattern-3 Assessment now generate geometry (bounding boxes) for visualization in UI 'Visual Editor' (parity with Pattern-1)**
  - Added comprehensive spatial localization capabilities to both regular and granular assessment services
  - **Automatic Processing**: When LLM provides bbox coordinates, automatically converts to UI-compatible (Visual Edit) geometry format without any configuration
  - **Universal Support**: Works with all attribute types - simple attributes, nested group attributes (e.g., CompanyAddress.State), and list attributes
  - **Enhanced Prompts**: Updated assessment task prompts with spatial-localization-guidelines requesting bbox coordinates in normalized 0-1000 scale
  - **Demo Notebooks**: Assessment notebooks now showcase automatic bounding box processing

- **New Python-Based Publishing System**
  - Replaced `publish.sh` bash script with new `publish.py` Python script
  - Rich console interface with progress bars, spinners, and colored output using Rich library
  - Multi-threaded artifact building and uploading for significantly improved performance
  - Native support for Linux, macOS, and Windows environments

- **Windows Development Environment Setup Guide and Helper Script**
  - New `scripts/dev_setup.bat` (570 lines) for complete Windows development environment configuration

- **OCR Service Default Image Sizing for Resource Optimization**
  - Implemented automatic default image size limits (951×1268) when no image sizing configuration is provided
  - **Key Benefits**: Reduction in vision model token consumption, prevents OutOfMemory errors during concurrent processing, improves processing speed and reduces bandwidth usage

### Changed

- **Reverted to python3.12 runtime to resolve build package dependency problems**

### Fixed

- **Improved Visual Edit bounding box position when using image zoom or pan**

### Templates
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.3.13.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main_0.3.13.yaml`

## [0.3.12]

### Added

- **Custom Prompt Generator Lambda Support for Patterns 2 & 3**
  - Added `custom_prompt_lambda_arn` configuration field to enable injection of custom business logic into extraction processing
  - **Key Features**: Lambda interface with all template placeholders (DOCUMENT_TEXT, DOCUMENT_CLASS, ATTRIBUTE_NAMES_AND_DESCRIPTIONS, DOCUMENT_IMAGE), URI-based image handling for JSON serialization, comprehensive error handling with fail-fast behavior, scoped IAM permissions requiring GENAIIDP-\* function naming
  - **Use Cases**: Document type-specific processing rules, integration with external systems for customer configurations, conditional processing based on document content, regulatory compliance and industry-specific requirements
  - **Demo Resources**: Interactive notebook demonstration (`step3_extraction_with_custom_lambda.ipynb`), SAM deployment template for demo Lambda function, comprehensive documentation and examples in `notebooks/examples/demo-lambda/`
  - **Benefits**: Custom business logic without core code changes, backward compatible (existing deployments unchanged), robust JSON serialization handling all object types, complete observability with detailed logging

- **Refactored Document Classification Service for Enhanced Boundary Detection**
  - Consolidated `multimodalPageLevelClassification` and the experimental `multimodalPageBoundaryClassification` (from v0.3.11) into a single enhanced `multimodalPageLevelClassification` method
  - Implemented BIO-like sequence segmentation with document boundary indicators: "start" (new document) and "continue" (same document)
  - Automatically segments multi-document packets, even when they contain multiple documents of the same type
  - Added comprehensive classification guide with method comparisons and best practices
  - **Benefits**: Simplified codebase with single multimodal classification method, improved handling of complex document packets, maintains backward compatibility
  - **No Breaking Changes**: Existing configurations work unchanged, no configuration updates required

- **Enhanced A2I Template and Workflow Management**
  - Enhanced A2I template with improved user interface and clearer instructions for reviewers
  - Added comprehensive instructions for reviewers in A2I template to guide the review process
  - Implemented capture of failed review tasks with proper error handling and logging
  - Added workflow orchestration control to stop processing when reviewer rejects A2I task
  - Removed automatic A2I task creation when Pattern-1 Bedrock Data Automation (BDA) fails to classify document to appropriate Blueprint

- **Dynamic Cost Calculation for Metering Data**
  - Added automated unit cost and estimated cost calculation to metering table with new `unit_cost` and `estimated_cost` columns
  - Dynamic pricing configuration loading from configuration
  - Enhanced cost analysis capabilities with comprehensive Athena queries for cost tracking, trend analysis, and efficiency metrics
  - Automatic cost calculation as `estimated_cost = value × unit_cost` for all metering records
- **Configuration-Based Summarization Control**
  - Summarization can now be enabled/disabled via configuration file `summarization.enabled` property instead of CloudFormation stack parameter
  - **Key Benefits**: Runtime control without stack redeployment, zero LLM costs when disabled, simplified state machine architecture, backward compatible defaults
  - **Implementation**: Always calls SummarizationStep but service skips processing when `enabled: false`
  - **Cost Optimization**: When disabled, no LLM API calls or S3 operations are performed
  - **Configuration Example**: Set `summarization.enabled: false` to disable, `enabled: true` to enable (default)

- **Configuration-Based Assessment Control**
  - Assessment can now be enabled/disabled via configuration file `assessment.enabled` property instead of CloudFormation stack parameter
  - **Key Benefits**: Runtime control without stack redeployment, zero LLM costs when disabled, simplified state machine architecture, backward compatible defaults
  - **Implementation**: Always calls AssessmentStep but service skips processing when `enabled: false`
  - **Cost Optimization**: When disabled, no LLM API calls or S3 operations are performed
  - **Configuration Example**: Set `assessment.enabled: false` to disable, `enabled: true` to enable (default)

- **New guides for setting up development environments**
  - EC2-based Linux development environment
  - MacOS development environment

### Removed

- **CloudFormation Parameters**: Removed `IsSummarizationEnabled` and `IsAssessmentEnabled` parameters from all pattern templates
- **Related Conditions**: Removed parameter conditions and state machine definition substitutions for both features
- **Conditional Logic**: Eliminated complex conditional logic from state machine definitions for summarization and assessment steps

### ⚠️ Breaking Changes

- **Configuration Migration Required**: When updating a stack that previously had `IsSummarizationEnabled` or `IsAssessmentEnabled` set to `false`, these features will now default to `enabled: true` after the update. To maintain the disabled behavior:
  1. Update your configuration file to set `summarization.enabled: false` and/or `assessment.enabled: false` as needed
  2. Save the configuration changes immediately after the stack update
  3. This ensures continued cost optimization by preventing unexpected LLM API calls
- **Action Required**: Review your current CloudFormation parameter settings before updating and update your configuration accordingly to preserve existing behavior

### Changed

- **Updated Python Lambda Runtime to 3.13**

### Fixed

- **Fixed B615 "Unsafe Hugging Face Hub download without revision pinning" security finding in Pattern-3 fine-tuning module** - Added revision pinning with to prevent supply chain attacks and ensure reproducible deployments
- **Fixed CloudWatch Log Group Missing Retention regression**
- **Security: Cross-Site Scripting (XSS) Vulnerability in FileViewer Component** - Fixed high-risk XSS vulnerability in `src/ui/src/components/document-viewer/FileViewer.jsx` where `innerHTML` was used with user-controlled data
- **Add permissions boundary support to new Lambda function roles introduced in previous releases**
- **Fixed OutOfMemory Errors in Pattern-2 OCR Lambda for Large High-Resolution Documents**
  - **Root Cause**: Processing large PDFs with high-resolution images (7469×9623 pixels) caused memory spikes when 20 concurrent workers each held ~101MB images simultaneously, exceeding the 4GB Lambda memory limit
  - **Optimal Solution**: Refactored image extraction to render directly at target dimensions using PyMuPDF matrix transformations, completely eliminating oversized image creation

### Templates
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.3.12.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main_0.3.12.yaml`

## [0.3.11]

### Added

- **Chat with Document** now available at the bottom of the each Document Detail page.
- **Anthropic Claude Opus 4.1** model available in configuration for all document processing steps
- **Browser tab icon** now features a blue background with a white "IDP"
- **Experimental new classification method** - multimodalPageBoundaryClassification - for detecting section boundaries during page level classification.

### Templates
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.3.11.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main_0.3.11.yaml`

## [0.3.10]

### Added

- **Agent Analysis Feature for Natural Language Document Analytics**
  - Added integrated AI-powered analytics agent that enables natural language querying of processed document data
  - **Key Capabilities**: Convert natural language questions to SQL queries, generate interactive visualizations and tables, explore database schema automatically
  - **Secure Architecture**: All Python code execution happens in isolated AWS Bedrock AgentCore sandboxes, not in Lambda functions
  - **Multi-Tool Agent System**: Database discovery tool for schema exploration, Athena query tool for SQL execution, secure code sandbox for data transfer, Python visualization tool for charts and tables
  - **Example Use Cases**: Query document processing volumes and trends, analyze confidence scores and extraction accuracy, explore document classifications and content patterns, generate custom charts and data tables
  - **Sample W2 Test Data**: Includes 20 synthetic W2 tax documents for testing analytics capabilities
  - **Configurable Models**: Supports multiple AI models including Claude 3.7 Sonnet (default), Claude 3.5 Sonnet, Nova Pro/Lite, and Haiku
  - **Web UI Integration**: Accessible through "Document Analytics" section with real-time progress display and query history

- **Automatic Glue Table Creation for Document Sections**
  - Added automatic creation of AWS Glue tables for each document section type (classification) during processing
  - Tables are created dynamically when new section types are encountered, eliminating manual table creation
  - Consistent lowercase naming convention for tables ensures compatibility with case-sensitive S3 paths
  - Tables are configured with partition projection for efficient date-based queries without manual partition management
  - Automatic schema evolution - tables update when new fields are detected in extraction results

### Templates
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.3.10.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main_0.3.10.yaml`

## [0.3.9]

### Added

- **Optional Permissions Boundary Support for Enterprise Deployments**
  - Added `PermissionsBoundaryArn` parameter to all CloudFormation templates for organizations with Service Control Policies (SCPs) requiring permissions boundaries
  - Comprehensive support for both explicit IAM roles and implicit roles created by AWS SAM functions and statemachines`
  - Conditional implementation ensures backward compatibility - when no permissions boundary is provided, roles deploy normally

### Added

- IDP Configuration and Prompting Best Practices documentation [doc](./docs/idp-configuration-best-practices.md)

### Changed

- Updated lending_package.pdf sample with more realistic driver's license image

### Fixed

- Issue #27 - removed idp_common bedrock client region default to us-west-2 - PR #28

## [0.3.8]

### Added

- **Lending Package Configuration Support for Pattern-2**
  - Added new `lending-package-sample` configuration to Pattern-2, providing comprehensive support for lending and financial document processing workflows
  - New default configuration for Pattern-2 stack deployments, optimized for loan applications, mortgage processing, and financial verification documents
  - Previous `rvl-cdip-sample` configuration remains available by selecting `rvl-cdip` for the `Pattern2Configuration` parameter when deploying or updating stacks

- **Text Confidence View for Document Pages**
  - Added support for displaying OCR text confidence data through new `TextConfidenceUri` field
  - New "Text Confidence View" option in the UI pages panel alongside existing Markdown and Text views
  - Fixed issues with view persistence - Text Confidence View button now always visible with appropriate messaging when content unavailable
  - Fixed view toggle behavior - switching between views no longer closes the viewer window
  - Reordered view buttons to: Markdown View, Text Confidence View, Text View for better user experience

- **Enhanced OCR DPI Configuration for PDF files**
  - DPI for PDF image conversion is now configurable in the configuration editor under OCR image processing settings
  - Default DPI improved from 96 to 150 DPI for better default quality and OCR accuracy
  - Configurable through Web UI without requiring code changes or redeployment

### Changed

- **Converted text confidence data format from JSON to markdown table for improved readability and reduced token usage**
  - Removed unnecessary "page_count" field
  - Changed "text_blocks" array to "text" field containing a markdown table with Text and Confidence columns
  - Reduces prompt size for assessment service while improving UI readability
  - OCR confidence values now rounded to 1 decimal point (e.g., 99.1, 87.3) for cleaner display
  - Markdown table headers now explicitly left-aligned using `|:-----|:-----------|` format for consistent appearance

- **Simplified OCR Service Initialization**
  - OCR service now accepts a single `config` dictionary parameter for cleaner, more consistent API
  - Aligned with classification service pattern for better consistency across IDP services
  - Backward compatibility maintained - old parameter pattern still supported with deprecation warning
  - Updated all lambda functions and notebooks to use new simplified pattern
- Removed fixed image target_height and target_width from default configurations, so images are processed in original resolution by default.

- **Updated Default Configuration for Pattern1 and Pattern2**
  - Changed default configuration for new stacks from "default" to "lending-package-sample" for both Pattern1 and Pattern2
  - Maintains backward compatibility for stack updates by keeping the parameter value "default" mapped to the rvl-cdip-sample for pattern-2.

- **Reduce assessment step costs**
  - Default model for granular assessment is now `us.amazon.nova-lite-v1:0` - experimentation recommended
  - Improved placement of <<CACHEPOINT>> tags in assessment prompt to improve utilization of prompt caching

### Fixed

- **Fixed Image Resizing Behavior for High-Resolution Documents**
  - Fixed issue where empty strings in image configuration were incorrectly resizing images to default 951x1268 pixels instead of preserving original resolution
  - Empty strings (`""`) in `target_width` and `target_height` configuration now preserve original document resolution for maximum processing accuracy
- Fixed issue where PNG files were being unnecessarily converted to JPEG format and resized to lower resolution with lost quality
- Fixed issue where PNG and JPG image files were not rendering inline in the Document Details page
- Fixed issue where PDF files were being downloaded instead of displayed inline
- Fixed pricing data for cacheWrite tokens for Amazon Nova models to resolve innacurate cost estimation in UI.

## [0.3.7]

### Added

- **Criteria Validation Service Class**
  - New document validation service that evaluates documents against dynamic business rules using Large Language Models (LLMs)
  - **Key Capabilities**: Dynamic business rules configuration, asynchronous processing with concurrent criteria evaluation, intelligent text chunking for large documents, multi-file processing with summarization, comprehensive cost and performance tracking
  - **Primary Use Cases**: Healthcare prior authorization workflows, compliance validation, business rule enforcement, quality assurance, and audit preparation
  - **Architecture Features**: Seamless integration with IDP pipeline using common Bedrock client, unified metering with automatic token usage tracking, S3 operations using standardized file operations, configuration compatibility with existing IDP config system
  - **Advanced Features**: Configurable criteria questions without code changes, robust error handling with graceful degradation, Pydantic-based input/output validation with automatic data cleaning, comprehensive timing metrics and token usage tracking
  - **Limitation**: Python idp_common support only, not yet implemented within deployed pattern workflows.

- **Document Process Flow Visualization**
  - Added interactive visualization of Step Functions workflow execution for document processing
  - Visual representation of processing steps with status indicators and execution details
  - Detailed step information including inputs, outputs, and error messages
  - Timeline view showing chronological execution of all processing steps
  - Auto-refresh capability for monitoring active executions in real-time
  - Support for Map state visualization with iteration details
  - Error diagnostics with detailed error messages for troubleshooting
  - Automatic selection of failed steps for quick issue identification

- **Granular Assessment Service for Scalable Confidence Evaluation**
  - New granular assessment approach that breaks down assessment into smaller, focused tasks for improved accuracy and performance
  - **Key Benefits**: Better accuracy through focused prompts, cost optimization via prompt caching, reduced latency through parallel processing, and scalability for complex documents
  - **Task Types**: Simple batch tasks (groups 3-5 simple attributes), group tasks (individual group attributes), and list item tasks (individual list items for maximum accuracy)
  - **Configuration**: Configurable batch sizes (`simple_batch_size`, `list_batch_size`) and parallel processing (`max_workers`) for performance tuning
  - **Prompt Caching**: Leverages LLM caching capabilities with cached base content (document context, images, OCR data) and dynamic task-specific content
  - **Use Cases**: Ideal for bank statements with hundreds of transactions, documents with 10+ attributes, complex nested structures, and performance-critical scenarios
  - **Backward Compatibility**: Maintains same interface as standard assessment service with seamless migration path
  - **Enhanced Documentation**: Comprehensive documentation in `docs/assessment.md` and example notebooks for both standard and granular approaches

- **Reporting Database now has Document Sections Tables to enable querying across document fields**
  - Added comprehensive document sections storage system that automatically creates tables for each section type (classification)
  - **Dynamic Table Creation**: AWS Glue Crawler automatically discovers new section types and creates corresponding tables (e.g., `invoice`, `receipt`, `bank_statement`)
  - **Configurable Crawler Schedule**: Support for manual, every 15 minutes, hourly, or daily (default) crawler execution via `DocumentSectionsCrawlerFrequency` parameter
  - **Partitioned Storage**: Data organized by section type and date for efficient querying with Amazon Athena

- **Partition Projections for Evaluation and Metering tables**
  - **Automated Partition Management**: Eliminates need for `MSCK REPAIR TABLE` operations with projection-based partition discovery
  - **Performance Benefits**: Athena can efficiently prune partitions based on date ranges without manual partition loading
  - **Backward Compatibility Warning**: The partition structure change from `year=2024/month=03/day=15/` to `date=2024-03-15/` means that data saved in the evaluation or metering tables prior to v0.3.7 will not be visible in Athena queries after updating. To retain access to historical data, you can either:
    - Manually reorganize existing S3 data to match the new partition structure
    - Create separate Athena tables pointing to the old partition structure for historical queries

- **Optimize the classification process for single class configurations in Pattern-2**
  - Detects when only a single document class is defined in the configuration
  - Automatically classifies all document pages as that single class
  - Creates a single section containing all pages
  - Bypasses the backend service calls (Bedrock or SageMaker) completely
  - Logs an INFO message indicating the optimization is active

- **Skip the extraction process for classes with no attributes in Pattern 2/3**
  - Add early detection logic in extraction class to check for empty/missing attributes
  - Return zero metering data and empty JSON results when no attributes defined

- **Enhanced State Machine Optimization for Very Large Documents**
  - Improved document compression to store only section IDs rather than full section objects
  - Modified state machine workflow to eliminate nested result structures and reduce payload size
  - Added OutputPath filtering to remove intermediate results from state machine execution
  - Streamlined assessment step to replace extraction results instead of nesting them
  - Resolves "size exceeding the maximum number of bytes service limit" errors for documents with 500+ pages

### Changed

- **Default behavior for image attachment in Pattern-2 and Pattern3**
  - If the prompt contains a `{DOCUMENT_IMAGE}` placeholder, keep the current behavior (insert image at placeholder)
  - If the prompt does NOT contain a `{DOCUMENT_IMAGE}` placeholder, do NOT attach the image at all
  - Previously, if the (classification or extraction) prompt did NOT contain a `{DOCUMENT_IMAGE}` placeholder, the image was appended at the end of the content array anyway
- **Modified default assessment prompt for token efficiency**
  - Removed `confidence_reason` from output to avoid consuming unnecessary output tokens
  - Refactored task_prompt layout to improve <<CACHEPOINT>> placement for efficiency when granular mode is enabled or disabled
- **Enhanced .clinerules with comprehensive memory bank workflows**
  - Enhanced Plan Mode workflow with requirements gathering, reasoning, and user approval loop

### Fixed

- Fixed UI list deletion issue where empty lists were not saved correctly - #18
- Improve structure and clarity for idp_common Python package documentation
- Improved UI in View/Edit Configuration to clarify that Class and Attribute descriptions are used in the classification and extraction prompts
- Automate UI updates for field "HITL (A2I) Status" in the Document list and document details section.
- Fixed image display issue in PagesPanel where URLs containing special characters (commas, spaces) would fail to load by properly URL-encoding S3 object keys in presigned URL generation

## [0.3.6]

### Fixed

- Update Athena/Glue table configuration to use Parquet format instead of JSON #20
- Cloudformation Error when Changing Evaluation Bucket Name #19

### Added

- **Extended Document Format Support in OCR Service**
  - Added support for processing additional document formats beyond PDF and images:
    - Plain text (.txt) files with automatic pagination for large documents
    - CSV (.csv) files with table visualization and structured output
    - Excel workbooks (.xlsx, .xls) with multi-sheet support (each sheet as a page)
    - Word documents (.docx, .doc) with text extraction and visual representation
  - **Key Features**:
    - Consistent processing model across all document formats
    - Standard page image generation for all formats
    - Structured text output in formats compatible with existing extraction pipelines
    - Confidence metrics for all document types
    - Automatic format detection from file content and extension
  - **Implementation Details**:
    - Format-specific processing strategies for optimal results
    - Enhanced text rendering for plain text documents
    - Table visualization for CSV and Excel data
    - Word document paragraph extraction with formatting preservation
    - S3 storage integration matching existing PDF processing workflow

## [0.3.5]

### Added

- **Human-in-the-Loop (HITL) Support - Pattern 1**
  - Added comprehensive Human-in-the-Loop review capabilities using Amazon SageMaker Augmented AI (A2I)
  - **Key Features**:
    - Automatic triggering when extraction confidence falls below configurable threshold
    - Integration with SageMaker A2I Review Portal for human validation and correction
    - Configurable confidence threshold through Web UI Portal Configuration tab (0.0-1.0 range)
    - Seamless result integration with human-verified data automatically updating source results
  - **Workflow Integration**:
    - HITL tasks created automatically when confidence thresholds are not met
    - Reviewers can validate correct extractions or make necessary corrections through the Review Portal
    - Document processing continues with human-verified data after review completion
  - **Configuration Management**:
    - `EnableHITL` parameter for feature toggle
    - Confidence threshold configurable via Web UI without stack redeployment
    - Support for existing private workforce work teams via input parameter
  - **CloudFormation Output**: Added `SageMakerA2IReviewPortalURL` for easy access to review portal
  - **Known Limitations**: Current A2I version cannot provide direct hyperlinks to specific document tasks; template updates require resource recreation
- **Document Compression for Large Documents - all patterns**
  - Added automatic compression support to handle large documents and avoid exceeding Step Functions payload limits (256KB)
  - **Key Features**:
    - Automatic compression (default trigger threshold of 0KB enables compression by default)
    - Transparent handling of both compressed and uncompressed documents in Lambda functions
    - Temporary S3 storage for compressed document state with automatic cleanup via lifecycle policies
  - **New Utility Methods**:
    - `Document.load_document()`: Automatically detects and decompresses document input from Lambda events
    - `Document.serialize_document()`: Automatically compresses large documents for Lambda responses
    - `Document.compress()` and `Document.decompress()`: Compression/decompression methods
  - **Lambda Function Integration**: All relevant Lambda functions updated to use compression utilities
  - **Resolves Step Functions Errors**: Eliminates "result with a size exceeding the maximum number of bytes service limit" errors for large multi-page documents
- **Multi-Backend OCR Support - Pattern 2 and 3**
  - Textract Backend (default): Existing AWS Textract functionality
  - Bedrock Backend: New LLM-based OCR using Claude/Nova models
  - None Backend: Image-only processing without OCR
- **Bedrock OCR Integration - Pattern 2 and 3**
  - Customizable system and task prompts for OCR optimization
  - Better handling of complex documents, tables, and forms
  - Layout preservation capabilities
- **Image Preprocessing - Pattern 2**
  - Adaptive Binarization: Improves OCR accuracy on documents with:
    - Uneven lighting or shadows
    - Low contrast text
    - Background noise or gradients
  - Optional feature with configurable enable/disable
- **YAML Parsing Support for LLM Responses - Pattern 2 and 3**
  - Added comprehensive YAML parsing capabilities to complement existing JSON parsing functionality
  - New `extract_yaml_from_text()` function with robust multi-strategy YAML extraction:
    - YAML in `yaml and`yml code blocks
    - YAML with document markers (---)
    - Pattern-based YAML detection using indentation and key indicators
  - New `detect_format()` function for automatic format detection returning 'json', 'yaml', or 'unknown'
  - New unified `extract_structured_data_from_text()` wrapper function that automatically detects and parses both JSON and YAML formats
  - **Token Efficiency**: YAML typically uses 10-30% fewer tokens than equivalent JSON due to more compact syntax
  - **Service Integration**: Updated classification service to use the new unified parsing function with automatic fallback between formats
  - **Comprehensive Testing**: Added 39 new unit tests covering all YAML extraction strategies, format detection, and edge cases
  - **Backward Compatibility**: All existing JSON functionality preserved unchanged, new functionality is purely additive
  - **Intelligent Fallback**: Robust fallback mechanism handles cases where preferred format fails (e.g., JSON requested as YAML falls back to JSON)
  - **Production Ready**: Handles malformed content gracefully, comprehensive error handling and logging
  - **Example Notebook**: Added `notebooks/examples/step3_extraction_using_yaml.ipynb` demonstrating YAML-based extraction with automatic format detection and token efficiency benefits

### Fixed

- **Enhanced JSON Extraction from LLM Responses (Issue #16)**
  - Modularized duplicate `_extract_json()` functions across classification, extraction, summarization, and assessment services into a common `extract_json_from_text()` utility function
  - Improved multi-line JSON handling with literal newlines in string values that previously caused parsing failures
  - Added robust JSON validation and multiple fallback strategies for better extraction reliability
  - Enhanced string parsing with proper escape sequence handling for quotes and newlines
  - Added comprehensive unit tests covering various JSON formats including multi-line scenarios

## [0.3.4]

### Added

- **Configurable Image Processing and Enhanced Resizing Logic**
  - **Improved Image Resizing Algorithm**: Enhanced aspect-ratio preserving scaling that only downsizes when necessary (scale factor < 1.0) to prevent image distortion
  - **Configurable Image Dimensions**: All processing services (Assessment, Classification, Extraction, OCR) now support configurable image dimensions through configuration with default 951×1268 resolution
  - **Service-Specific Image Optimization**: Each service can use optimal image dimensions for performance and quality tuning
  - **Enhanced OCR Service**: Added configurable DPI for PDF-to-image conversion and optional image resizing with dual image strategy (stores original high-DPI images while using resized images for processing)
  - **Runtime Configuration**: No code changes needed to adjust image processing - all configurable through service configuration
  - **Backward Compatibility**: Default values maintain existing behavior with no immediate action required for existing deployments
- **Enhanced Configuration Management**
  - **Save as Default**: New button to save current configuration as the new default baseline with confirmation modal and version upgrade warnings
  - **Export Configuration**: Export current configuration to local files in JSON or YAML format with customizable filename
  - **Import Configuration**: Import configuration from local JSON or YAML files with automatic format detection and validation
  - Enhanced Lambda resolver with deep merge functionality for proper default configuration updates
  - Automatic custom configuration reset when saving as default to maintain clean state
- **Nested Attribute Groups and Lists Support**
  - Enhanced document configuration schema to support complex nested attribute structures with three attribute types:
    - **Simple attributes**: Single-value extractions (existing behavior)
    - **Group attributes**: Nested object structures with sub-attributes (e.g., address with street, city, state)
    - **List attributes**: Arrays with item templates containing multiple attributes per item (e.g., transactions with date, amount, description)
  - **Web UI Enhancements**: Configuration editor now supports viewing and editing nested attribute structures with proper validation
  - **Extraction Service Updates**: Enhanced `{ATTRIBUTE_NAMES_AND_DESCRIPTIONS}` placeholder processing to generate formatted prompts for nested structures
  - **Assessment Service Enhancements**: Added support for nested structure confidence evaluation with recursive processing of group and list attributes, including proper confidence threshold application from configuration
  - **Evaluation Service Improvements**:
    - Implemented pattern matching for list attributes (e.g., `Transactions[].Date` maps to `Transactions[0].Date`, `Transactions[1].Date`)
    - Added data flattening for complex extraction results using dot notation and array indices
    - Fixed numerical sorting for list items (now sorts 0, 1, 2, ..., 10, 11 instead of alphabetically)
    - Individual evaluation methods applied per nested attribute (EXACT, FUZZY, SEMANTIC, etc.)
  - **Documentation**: Comprehensive updates to evaluation docs and README files with nested structure examples and processing explanations
  - **Use Cases**: Enables complex document processing for bank statements (account details + transactions), invoices (vendor info + line items), and medical records (patient info + procedures)

- **Enhanced Documentation and Examples**
  - New example notebooks with improved clarity, modularity, and documentation

- **Evaluation Framework Enhancements**
  - Added confidence threshold to evaluation outputs to enable prioritizing accuracy results for attributes with higher confidence thresholds

- **Comprehensive Metering Data Collection**
  - The system now captures and stores detailed metering data for analytics, including:
    - Which services were used (Textract, Bedrock, etc.)
    - What operations were performed (analyze_document, Claude, etc.)
    - How many resources were consumed (pages, tokens, etc.)

- **Reporting Database Documentation**
  - Added comprehensive reporting database documentation

### Changed

- Pin packages to tested versions to avoid vulnerability from incompatible new package versions.
- Updated reporting data to use document's queued_time for consistent timestamps
- Create new extensible SaveReportingData class in idp_common package for saving evaluation results to Parquet format
- Remove save_to_reporting from evaluation_function and replace with Lambda invocation, for smaller Lambda packages and better modularity.
- Harden publish process and avoid package version bloat by purging previous build artifacts before re-building

### Fixed

- Defend against non-numeric confidence_threshold values in the configuration - avoid float conversion or numeric comparison exceptions in Assessement step
- Prevent creation of empty configuration fields in UI
- Firefox browser issues with signed URLs (PR #14)
- Improved S3 Partition Key Format for Better Date Range Filtering:
  - Updated reporting data partition keys to use YYYY-MM format for month and YYYY-MM-DD format for day
  - Enables easier date range filtering in analytics queries across different months and years
  - Partition structure now: `year=2024/month=2024-03/day=2024-03-15/` instead of `year=2024/month=03/day=15/`

## [0.3.3]

### Added

- **Amazon Nova Model Fine-tuning Support**
  - Added comprehensive `ModelFinetuningService` class for managing Nova model fine-tuning workflows
  - Support for fine-tuning Amazon Nova models (Nova Lite, Nova Pro) using Amazon Bedrock
  - Complete end-to-end workflow including dataset preparation, job creation, provisioned throughput management, and inference
  - CLI tools for fine-tuning workflow:
    - `prepare_nova_finetuning_data.py` - Dataset preparation from RVL-CDIP or custom datasets
    - `create_finetuning_job.py` - Fine-tuning job creation with automatic IAM role setup
    - `create_provisioned_throughput.py` - Provisioned throughput management for fine-tuned models
    - `inference_example.py` - Model inference and evaluation with comparison capabilities
  - CloudFormation integration with new parameters:
    - `CustomClassificationModelARN` - Support for custom fine-tuned classification models in Pattern-2
    - `CustomExtractionModelARN` - Support for custom fine-tuned extraction models in Pattern-2
  - Automatic integration of fine-tuned models in classification and extraction model selection dropdowns
  - Comprehensive documentation in `docs/nova-finetuning.md` with step-by-step instructions
  - Example notebooks:
    - `finetuning_dataset_prep.ipynb` - Interactive dataset preparation
    - `finetuning_model_service_demo.ipynb` - Service usage demonstration
    - `finetuning_model_document_classification_evaluation.ipynb` - Model evaluation
  - Built-in support for Bedrock fine-tuning format with multi-modal capabilities
  - Data splitting and validation set creation
  - Cost optimization features including provisioned throughput deletion
  - Performance metrics and accuracy evaluation tools

- **Assessment Feature for Extraction Confidence Evaluation (EXPERIMENTAL)**
  - Added new assessment service that evaluates extraction confidence using LLMs to analyze extraction results against source documents
  - Multi-modal assessment capability combining text analysis with document images for comprehensive confidence scoring
  - UI integration with explainability_info display showing per-attribute confidence scores, thresholds, and explanations
  - Optional deployment controlled by `IsAssessmentEnabled` parameter (defaults to false)
  - Added e2e-example-with-assessment.ipynb notebook for testing assessment workflow

- **Enhanced Evaluation Framework with Confidence Integration**
  - Added confidence fields to evaluation reports for quality analysis
  - Automatic extraction and display of confidence scores from assessment explainability_info
  - Enhanced JSON and Markdown evaluation reports with confidence columns
  - Backward compatible integration - shows "N/A" when confidence data unavailable

- **Evaluation Analytics Database and Reporting System**
  - Added comprehensive ReportingDatabase (AWS Glue) with structured evaluation metrics storage
  - Three-tier analytics tables: document_evaluations, section_evaluations, and attribute_evaluations
  - Automatic partitioning by date and document for efficient querying with Amazon Athena
  - Detailed metrics tracking including accuracy, precision, recall, F1 score, execution time, and evaluation methods
  - Added evaluation_reporting_analytics.ipynb notebook for comprehensive performance analysis and visualization
  - Multi-level analytics with document, section, and attribute-level insights
  - Visual dashboards showing accuracy distributions, performance trends, and problematic patterns
  - Configurable filters for date ranges, document types, and evaluation thresholds
  - Integration with existing evaluation framework - metrics automatically saved to database
  - ReportingDatabase output added to CloudFormation template for easy reference

### Fixed

- Fixed build failure related to pandas, numpy, and PyMuPDF dependency conflicts in the idp_common_pkg package
- Fixed deployment failure caused by CodeBuild project timeout, by raising TimeoutInMinutes property
- Added missing cached token metrics to CloudWatch dashboards
- Added Bedrock model access prerequisite to README and deployment doc.

## [0.3.2]

### Added

- **Cost Estimator UI Feature for Context Grouping and Subtotals**
  - Added context grouping functionality to organize cost estimates by logical categories (e.g. OCR, Classification, etc.)
  - Implemented subtotal calculations for better cost breakdown visualization

- **DynamoDB Caching for Resilient Classification**
  - Added optional DynamoDB caching to the multimodal page-level classification service to improve efficiency and resilience
  - Cache successful page classification results to avoid redundant processing during retries when some pages fail due to throttling
  - Exception-safe caching preserves successful work even when individual threads or the overall process fails
  - Configurable via `cache_table` parameter or `CLASSIFICATION_CACHE_TABLE` environment variable
  - Cache entries scoped to document ID and workflow execution ARN with automatic TTL cleanup (24 hours)
  - Significant cost reduction and improved retry performance for large multi-page documents

### Fixed

- "Use as Evaluation Baseline" incorrectly sets document status back to QUEUED. It should remain as COMPLETED.

## [0.3.1]

### Added

- **{DOCUMENT_IMAGE} Placeholder Support in Pattern-2**
  - Added new `{DOCUMENT_IMAGE}` placeholder for precise image positioning in classification and extraction prompts
  - Enables strategic placement of document images within prompt templates for enhanced multimodal understanding
  - Supports both single images and multi-page documents (up to 20 images per Bedrock constraints)
  - Full backward compatibility - existing prompts without placeholder continue to work unchanged
  - Seamless integration with existing `{FEW_SHOT_EXAMPLES}` functionality
  - Added warning logging when image limits are exceeded to help with debugging
  - Enhanced documentation across classification.md, extraction.md, few-shot-examples.md, and pattern-2.md

### Fixed

- When encountering excessive Bedrock throttling, service returned 'unclassified' instead of retrying, when using multi-modal page level classification method.
- Minor documentation issues.

## [0.3.0]

### Added

- **Visual Edit Feature for Document Processing**
  - Interactive visual interface for editing extracted document data combining document image display with overlay annotations and form-based editing.
  - Split-Pane Layout, showing page image(s) and extraction inference results side by side
  - Zoom & Pan Controls for page image
  - Bounding Box Overlay System (Pattern-1 BDA only)
  - Confidence Scores (Pattern-1 BDA only)
  - **User Experience Benefits**
    - Visual context showing exactly where data was extracted from in original documents
    - Precision editing with visual verification ensuring accuracy of extracted data
    - Real-time visual connection between form fields and document locations
    - Efficient workflow eliminating context switching between viewing and editing

- **Enhanced Few Shot Example Support in Pattern-2**
  - Added comprehensive few shot learning capabilities to improve classification and extraction accuracy
  - Support for example-based prompting with concrete document examples and expected outputs
  - Configuration of few shot examples through document class definitions with `examples` field
  - Each example includes `name`, `classPrompt`, `attributesPrompt`, and `imagePath` parameters
  - **Enhanced imagePath Support**: Now supports single files, local directories, or S3 prefixes with multiple images
    - Automatic discovery of all image files with supported extensions (`.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp`, `.tiff`, `.tif`, `.webp`)
    - Images sorted alphabetically in prompt by filename for consistent ordering
  - Automatic integration of examples into classification and extraction prompts via `{FEW_SHOT_EXAMPLES}` placeholder
  - Demonstrated in `config_library/pattern-2/few_shot_example` configuration with letter, email, and multi-page bank-statement examples
  - Environment variable support for path resolution (`CONFIGURATION_BUCKET` and `ROOT_DIR`)
  - Updated documentation in classification and extraction README files and Pattern-2 few-shot examples guide

- **Bedrock Prompt Caching Support**
  - Added support for `<<CACHEPOINT>>` delimiter in prompts to enable Bedrock prompt caching
  - Prompts can now be split into static (cacheable) and dynamic sections for improved performance and cost optimization
  - Available in classification, extraction, and summarization prompts across all patterns
  - Automatic detection and processing of cache point delimiters in BedrockClient

- **Configuration Library Support**
  - Added `config_library/` directory with pre-built configuration templates for all patterns
  - Configuration now loaded from S3 URIs instead of being defined inline in CloudFormation templates
  - Support for multiple configuration presets per pattern (e.g., default, checkboxed_attributes_extraction, medical_records_summarization, few_shot_example)
  - New `ConfigurationDefaultS3Uri` parameter allows specifying custom S3 configuration sources
  - Enhanced configuration management with separation of infrastructure and business logic

### Fixed

- **Lambda Configuration Reload Issue**
  - Fixed lambda functions loading configuration globally which prevented configuration updates from being picked up during warm starts

### Changed

- **Simplified Model Configuration Architecture**
  - Removed individual model parameters from main template: `Pattern1SummarizationModel`, `Pattern2ClassificationModel`, `Pattern2ExtractionModel`, `Pattern2SummarizationModel`, `Pattern3ExtractionModel`, `Pattern3SummarizationModel`, `EvaluationLLMModelId`
  - Model selection now handled through enum constraints in UpdateSchemaConfig sections within each pattern template
  - Added centralized `IsSummarizationEnabled` parameter (true|false) to control summarization functionality across all patterns
  - Updated all pattern templates to use new boolean parameter instead of checking if model is "DISABLED"
  - Refactored IsSummarizationEnabled conditions in all pattern templates to use the new parameter
  - Maintained backward compatibility while significantly reducing parameter complexity

- **Documentation Restructure**
  - Simplified and condensed README
  - Added new ./docs folder with detailed documentation
  - New Contribution Guidelines
  - GitHub Issue Templates
  - Added documentation clarifying the separation between GenAIIDP solution issues and underlying AWS service concerns

## [0.2.20]

### Added

- Added document summarization functionality
  - New summarization service with default model set to Claude 3 Haiku
  - New summarization function added to all patterns
  - Added end-to-end document summarization notebook example
- Added Bedrock Guardrail integration
  - New parameters BedrockGuardrailId and BedrockGuardrailVersion for optional guardrail configuration
  - Support for applying guardrails in Bedrock model invocations (except classification)
  - Added guardrail functionality to Knowledge Base queries
  - Enhanced security and content safety for model interactions
- Improved performance with parallelized operations
  - Enhanced EvaluationService with multi-threaded processing for faster evaluation
    - Parallel processing of document sections using ThreadPoolExecutor
    - Intelligent attribute evaluation parallelization with LLM-specific optimizations
    - Dynamic batch sizing based on workload for optimal resource utilization
  - Reimplemented Copy to Baseline functionality with asynchronous processing
    - Asynchronous Lambda invocation pattern for processing large document collections
    - EvaluationStatus-based progress tracking and UI integration
    - Batch-based S3 object copying for improved efficiency
    - File operation batching with optimal batch size calculation
- Fine-grained document status tracking for UI real-time progress updates
  - Added status transitions (QUEUED → STARTED → RUNNING → OCR → CLASSIFYING → EXTRACTING → POSTPROCESSING → SUMMARIZING → COMPLETE)
- Default OCR configuration now includes LAYOUT, TABLES, SIGNATURE, and markdown generation now supports tables (via textractor[pandas])
- Added document reprocessing capability to the UI - New "Reprocess" button with confirmation dialog

### Changed

- Refactored code for better maintainability
- Updated UI components to support markdown table viewing
- Set default evaluation model to Claude 3 Haiku
- Improved AppSync timeout handling for long-running file copy operations
- Added security headers to UI application per security requirements
- Disabled GraphQL introspection for AppSync API to enhance security
- Added LogLevel parameter to main stack (default WARN level)
- Integration of AppSync helper package into idp_common_pkg
- Various bug fixes and improvements
- Enhanced the Hungarian evaluation method with configurable comparators
- Added dynamic UI form fields based on evaluation method selection
- Fixed multi-page standard output BDA processing in Pattern 1

## [0.2.19]

- Added enhanced EvaluationService with smart attribute discovery and evaluation
  - Automatically discovers and evaluates attributes not defined in configuration
  - Applies default semantic evaluation to unconfigured attributes using LLM method
  - Handles all attribute cases: in both expected/actual, only in expected, only in actual
  - Added new demo notebook examples showing smart attribute discovery in action
- Added SEMANTIC evaluation method using embedding-based comparison

## [0.2.18]

- Improved error handling in service classes
- Support for enum config schema and corresponding picklist in UI. Used for Textract feature selection.
- Removed LLM model choices preserving only multi-modal modals that support multiple image attachments
- Added support for textbased holistic packet classification in Pattern 2
- New holistic classification method in ClassifierService for multi-document packet processing
- Added new example notebook "e2e-holistic-packet-classification.ipynb" demonstrating the holistic classification approach
- Updated Pattern 2 template with parameter for ClassificationMethod selection (multimodalPageLevelClassification or textbasedHolisticClassification)
- Enhanced documentation and READMEs with information about classification methods
- Reorganized main README.md structure for improved navigation and readability

## [0.2.17]

### Enhanced Textract OCR Features

- Added support for Textract advanced features (TABLES, FORMS, SIGNATURES, LAYOUT)
- OCR results now output in rich markdown format for better visualization
- Configurable OCR feature selection through schema configuration
- Improved metering and tracking for different Textract feature combinations

## [0.2.16]

### Add additional model choice

- Claude, Nova, Meta, and DeepSeek model selection now available

### New Document-Based Architecture

The `idp_common_pkg` introduces a unified Document model approach for consistent document processing:

#### Core Classes

- **Document**: Central data model that tracks document state through the entire processing pipeline
- **Page**: Represents individual document pages with OCR results and classification
- **Section**: Represents logical document sections with classification and extraction results

#### Service Classes

- **OcrService**: Processes documents with AWS Textract or Amazon Bedrock and updates the Document with OCR results
- **ClassificationService**: Classifies document pages/sections using Bedrock or SageMaker backends
- **ExtractionService**: Extracts structured information from document sections using Bedrock

### Pattern Implementation Updates

- Lambda functions refactored, and significantly simplified, to use Document and Section objects, and new Service classes

### Key Benefits

1. **Simplified Integration**: Consistent interfaces make service integration straightforward
2. **Improved Maintainability**: Unified data model reduces code duplication and complexity
3. **Better Error Handling**: Standardized approach to error capture and reporting
4. **Enhanced Traceability**: Complete document history throughout the processing pipeline
5. **Flexible Backend Support**: Easy switching between Bedrock and SageMaker backends
6. **Optimized Resource Usage**: Focused document processing for better performance
7. **Granular Package Installation**: Install only required components with extras syntax

### Example Notebook

A new comprehensive Jupyter notebook demonstrates the Document-based workflow:

- Shows complete end-to-end processing (OCR → Classification → Extraction)
- Uses AWS services (S3, Textract, Bedrock)
- Demonstrates Document object creation and manipulation
- Showcases how to access and utilize extraction results
- Provides a template for custom implementations
- Includes granular package installation examples (`pip install "idp_common_pkg[ocr,classification,extraction]"`)

This refactoring sets the foundation for more maintainable, extensible document processing workflows with clearer data flow and easier troubleshooting.

### Refactored publish.sh script

- improved modularity with functions
- improved checksum logic to determine when to rebuild components