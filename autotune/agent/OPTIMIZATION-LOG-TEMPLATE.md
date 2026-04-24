# Optimization Log

This single file documents the past and current progress of the current optimization run. It includes important metadata like the name of the intelligent document processing (IDP) stack, the AWS account name, the optimization requirements, and so on. 

## Required Fields:
AWS account profile name in .aws/credentials: [THIS MUST BE FILLED IN BEFORE BEGINNING]

IDP pattern to use (to start with): [THIS MUST BE FILLED IN BEFORE BEGINNING, DEFAULT IS pattern-2]

IDP stack name and region (must be IDP v0.5.0 or higher): [THIS MUST BE FILLED IN BEFORE BEGINNING]

Directory to IDP source code: [THIS MUST BE FILLED IN BEFORE BEGINNING]

Directory to input dataset of documents: [THIS MUST BE FILLED IN BEFORE BEGINNING]

Ground truth available: [YES or NO — THIS MUST BE FILLED IN BEFORE BEGINNING]
- If **YES**: Provide the directory to ground truth baselines below. The full evaluation workflow (test studio, accuracy metrics, comparison) will be used.
- If **NO**: No accuracy metrics will be available. Optimization will use a best-effort approach: run inference, inspect extraction output qualitatively, iterate on prompts/schemas based on output quality signals. See the `no-ground-truth-optimization` skill for details.

Directory to ground truth baselines: [REQUIRED if ground truth is available, otherwise write "N/A"]

Dataset mode: [THIS MUST BE FILLED IN BEFORE BEGINNING]
- **single-class**: All documents are the same type (e.g., all invoices). Classification is not needed, optimization focuses only on extraction accuracy.
- **multi-class**: Documents are different types mixed together (e.g., invoices, receipts, forms). Both classification AND extraction must be optimized.
- **packet-splitting**: Multiple documents concatenated per file. Page-level classification + splitting + extraction. Use `PacketSplittingDiscovery` to bootstrap config.

List of _a priori_ known document classes ("none" if document classes are not known yet): [THIS MUST BE FILLED IN BEFORE BEGINNING]

Additional information about this dataset: [OPTIONAL, e.g. "documents are pre-sorted by class", "class boundaries are ambiguous between X and Y", "some classes have very different schemas"]

Additional information about requirements: [OPTIONAL, e.g. "cost doesn't matter, it needs to be as accurate as possible", or "class A of documents is much more common than class B", or "when extracting information from this type of class, this field is much more important than the rest"]

Initial configuration file: [OPTIONAL, the user might have a starting point for you. If not, delete this line before proceeding.]

## Optimization Log
