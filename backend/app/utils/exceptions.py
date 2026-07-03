"""Application specific exceptions."""


class DuplicateVendorError(Exception):
    def __init__(self, field: str, value: str) -> None:
        self.field = field
        self.value = value
        super().__init__(f"Vendor with {field} '{value}' already exists")
