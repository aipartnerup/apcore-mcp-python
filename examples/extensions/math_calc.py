"""Basic arithmetic calculator module."""

from pydantic import BaseModel, Field

from apcore import ModuleAnnotations


class MathCalcInput(BaseModel):
    a: float = Field(..., description="First operand")
    b: float = Field(..., description="Second operand")
    op: str = Field(
        default="add",
        description="Operation: add, sub, mul, div",
    )


class MathCalcOutput(BaseModel):
    result: float = Field(..., description="Calculation result")
    expression: str = Field(..., description="Human-readable expression")


class MathCalc:
    input_schema = MathCalcInput
    output_schema = MathCalcOutput
    description = "Perform basic arithmetic: add, subtract, multiply, or divide"
    tags = ["math", "utility"]
    annotations = ModuleAnnotations(readonly=True, idempotent=True, open_world=False)

    _OPS = {
        "add": ("+", lambda a, b: a + b),
        "sub": ("-", lambda a, b: a - b),
        "mul": ("*", lambda a, b: a * b),
        "div": ("/", lambda a, b: a / b),
    }

    def execute(self, inputs: dict, ctx) -> dict:
        a, b, op = inputs["a"], inputs["b"], inputs.get("op", "add")
        if op not in self._OPS:
            raise ValueError(f"Unknown operation: {op!r}. Expected: add, sub, mul, div")
        if op == "div" and b == 0:
            raise ValueError("Division by zero")
        symbol, fn = self._OPS[op]
        return {"result": fn(a, b), "expression": f"{a} {symbol} {b} = {fn(a, b)}"}
