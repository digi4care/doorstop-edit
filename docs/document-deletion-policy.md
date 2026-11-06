# Document deletion policy

## Decision: block deletion when child documents exist

Doorstop Edit must refuse to delete a document that has child documents. It must show a clear error
identifying that the document has children. It must not move or reparent those children
automatically.

The refusal must happen before any destructive operation: do not delete the selected document, its
items, or any child document. The document list and item tree remain unchanged. The user can remove
or otherwise resolve the child documents explicitly, then retry deleting the parent.

This policy applies only to deleting a document with children. Confirmation and deletion behavior
for a document without children are specified by MVP 4 separately.
