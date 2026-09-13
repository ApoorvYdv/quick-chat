class ErrorResponse:
    """Client-facing (4xx) error message strings.

    Every `HTTPException(detail=...)` in the app must reference a constant
    here instead of an inline literal string, so client-facing wording is
    defined in exactly one place and can be audited/changed without hunting
    through routers/dependencies for string literals.
    """

    CLIENT_NOT_PROVIDED = "Client header is required in headers."
    AGENCY_NOT_FOUND = "Agency not found."
    CASE_NOT_FOUND = "Case not found."
