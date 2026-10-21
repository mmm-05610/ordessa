"""Harness catalog-owned admission and identity errors."""


class CatalogIdentityConflict(RuntimeError):
    code = "IDENTITY_MISMATCH"


class CatalogAdmissionRefused(RuntimeError):
    code = "ADMISSION_REFUSED"


class CatalogUnavailable(RuntimeError):
    code = "GUARANTEE_UNAVAILABLE"
