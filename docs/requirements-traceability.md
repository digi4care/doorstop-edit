# Requirements traceability

The `requirements/` Doorstop tree records only explicit requirements from approved project documents. Each item cites its source section and named test evidence where available. Items without evidence are visibly marked uncovered/untestable; this is not a formal-compliance claim.

Run `uv run python tools/check_requirements.py` to validate the Doorstop tree and source/evidence targets. Missing or malformed named links fail; uncovered items are reported without failing the check.
