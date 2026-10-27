from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def install_error_handler(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_request: Request, error: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status,
            content={"error": error.code, "message": error.message},
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, error: RequestValidationError) -> JSONResponse:
        field = error.errors()[0]
        location = ".".join(map(str, field["loc"]))
        return JSONResponse(
            status_code=422,
            content={"error": "validation_error", "message": f"{location}: {field['msg']}"},
        )
