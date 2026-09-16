"""FastAPI application, server endpoints, and dossier generator."""

from aegiswatch.server.app import app
from aegiswatch.server.dossier import RegulatoryDossierGenerator

__all__ = ["app", "RegulatoryDossierGenerator"]
