# Artifacts

This package stores provider-neutral Artifact descriptors and materializes
trusted image sources into local files. It never accepts a caller-supplied URL:
the source must come from a descriptor discovered by a registered Provider.

The registry keeps private source metadata locally so signed URLs and `blob:`
references are not emitted in ordinary CLI output or logs. Materialization is
bounded, MIME-checked, hashed, and written through an atomic rename.
