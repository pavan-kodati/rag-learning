"""Typed application errors. The API maps each to an RFC 7807 problem response."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status = 500
    code = "internal_error"
    title = "Internal error"

    def __init__(self, detail: str = "", **extra: Any) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        self.extra = extra


class BadRequest(AppError):
    status, code, title = 400, "bad_request", "Bad request"


class Unauthorized(AppError):
    status, code, title = 401, "unauthorized", "Authentication required"


class Forbidden(AppError):
    status, code, title = 403, "forbidden", "Not permitted"


class NotFound(AppError):
    status, code, title = 404, "not_found", "Not found"


class Conflict(AppError):
    status, code, title = 409, "conflict", "Conflict"


class PayloadTooLarge(AppError):
    status, code, title = 413, "payload_too_large", "Payload too large"


class UnsupportedMedia(AppError):
    status, code, title = 415, "unsupported_media_type", "Unsupported file type"


class ValidationFailed(AppError):
    status, code, title = 422, "validation_failed", "Validation failed"


class RateLimited(AppError):
    status, code, title = 429, "rate_limited", "Too many requests"


class ServiceUnavailable(AppError):
    status, code, title = 503, "service_unavailable", "Service unavailable"


# --- domain-specific -------------------------------------------------------------------------
class DuplicateDocument(Conflict):
    code, title = "duplicate_document", "This file is already in the matter"


class BatchClosed(Conflict):
    code, title = "batch_closed", "The batch is not open for new documents"


class ParseError(ValidationFailed):
    """The document could not be read (corrupt, encrypted, empty, unsupported)."""

    code, title = "document_unreadable", "The document could not be read"


class ModelUnavailable(ServiceUnavailable):
    code, title = "model_unavailable", "The language model is not reachable"


class ModelOutputInvalid(AppError):
    """The model answered but not with usable structured output."""

    status, code, title = 502, "model_output_invalid", "The model returned unusable output"
