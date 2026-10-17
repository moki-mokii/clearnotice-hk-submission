class AppError(Exception):
    def __init__(self, code, message, status=502, *, retryable=False, delay=0):
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable
        self.delay = delay
        super().__init__(code)
