"""Generate a personalized greeting message."""

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from apcore import ModuleAnnotations


class GreetingInput(BaseModel):
    name: str = Field(..., description="Name of the person to greet")
    style: str = Field(default="friendly", description="Greeting style: friendly, formal, pirate")


class GreetingOutput(BaseModel):
    message: str = Field(..., description="The greeting message")
    timestamp: str = Field(..., description="ISO 8601 timestamp")


class Greeting:
    input_schema = GreetingInput
    output_schema = GreetingOutput
    description = "Generate a personalized greeting in different styles"
    tags = ["text", "fun"]
    annotations = ModuleAnnotations(readonly=True, idempotent=False, open_world=False)

    _STYLES = {
        "friendly": "Hey {name}! Great to see you!",
        "formal": "Good day, {name}. It is a pleasure to make your acquaintance.",
        "pirate": "Ahoy, {name}! Welcome aboard, matey!",
    }

    def execute(self, inputs: dict, ctx) -> dict:
        name = inputs["name"]
        style = inputs.get("style", "friendly")
        template = self._STYLES.get(style, self._STYLES["friendly"])
        return {
            "message": template.format(name=name),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
