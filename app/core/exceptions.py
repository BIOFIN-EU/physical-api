class AppError(Exception):
    def __init__(self, detail: str, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class NotFoundError(AppError):
    def __init__(self, detail: str = "Resource not found"):
        super().__init__(detail=detail, status_code=404)


class BadRequestError(AppError):
    def __init__(self, detail: str = "Bad request"):
        super().__init__(detail=detail, status_code=400)


class ConflictError(AppError):
    def __init__(self, detail: str = "Conflict"):
        super().__init__(detail=detail, status_code=409)

class IntegrityError(AppError):
    """
    Raised when a database integrity constraint fails
    (foreign key, unique constraint, etc.)
    """

    def __init__(
        self,
        detail: str = "Database integrity constraint violation.",
    ):
        super().__init__(
            detail=detail,
            status_code=400,
        )