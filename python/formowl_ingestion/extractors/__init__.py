"""Extractor adapter implementations."""

from .audio import FixtureAudioTranscriptExtractor
from .document import FixtureDocumentParserExtractor
from .mail import FixtureMailArchiveExtractor
from .metadata import FileTechnicalMetadataExtractor
from .ocr import FixtureOcrExtractor
from .text import PlainTextObservationExtractor
from .video import FixtureVideoSceneExtractor

__all__ = [
    "FileTechnicalMetadataExtractor",
    "FixtureAudioTranscriptExtractor",
    "FixtureDocumentParserExtractor",
    "FixtureMailArchiveExtractor",
    "FixtureOcrExtractor",
    "FixtureVideoSceneExtractor",
    "PlainTextObservationExtractor",
]
