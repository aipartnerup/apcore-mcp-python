"""Echo text back — a minimal read-only module for testing."""

from pydantic import BaseModel, Field

from apcore import ModuleAnnotations


class TextEchoInput(BaseModel):
    text: str = Field(..., description="Text to echo back")
    uppercase: bool = Field(default=False, description="Convert to uppercase")


class TextEchoOutput(BaseModel):
    echoed: str = Field(..., description="The echoed text")
    length: int = Field(..., description="Character count")


class TextEcho:
    input_schema = TextEchoInput
    output_schema = TextEchoOutput
    description = "Echo input text back, optionally converting to uppercase"
    tags = ["text", "utility"]
    annotations = ModuleAnnotations(readonly=True, idempotent=True, open_world=False)

    def execute(self, inputs: dict, ctx) -> dict:
        text = inputs["text"]
        if inputs.get("uppercase"):
            text = text.upper()
        return {"echoed": text, "length": len(text)}
