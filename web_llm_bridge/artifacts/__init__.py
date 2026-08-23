"""Artifact descriptors, local registry, and safe materialization helpers."""

from .model import ArtifactRecord, make_artifact_id
from .store import ArtifactStore
from .downloader import ArtifactMaterializer

__all__ = ["ArtifactRecord", "ArtifactMaterializer", "ArtifactStore", "make_artifact_id"]
