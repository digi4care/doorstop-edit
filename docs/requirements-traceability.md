# Requirements traceability

The `requirements/` Doorstop tree records only explicit requirements from approved project documents. Each item cites its source section and named test evidence where available. Items without evidence are visibly marked uncovered/untestable; this is not a formal-compliance claim.

The planned QML migration traceability graph has a separate schema contract in [`migration-traceability-ontology.md`](migration-traceability-ontology.md). That contract is distinct from the in-app Doorstop-project graph in [`app-knowledge-graph-ontology.md`](app-knowledge-graph-ontology.md); generation, validation and impact queries are tracked separately under Beads `.8.2` and `.8.3` and are not claimed as implemented here.

Run `uv run python tools/check_requirements.py` to validate the Doorstop tree and source/evidence targets. Missing or malformed named links fail; uncovered items are reported without failing the check.
