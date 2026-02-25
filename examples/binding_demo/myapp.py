"""Plain business logic — NO apcore imports, NO framework dependencies.

This file represents an existing project's code that we want to expose
as MCP tools without modifying a single line.
"""


def convert_temperature(value: float, from_unit: str = "celsius", to_unit: str = "fahrenheit") -> dict:
    """Convert temperature between Celsius, Fahrenheit, and Kelvin."""
    # Normalize to Celsius first
    if from_unit == "celsius":
        celsius = value
    elif from_unit == "fahrenheit":
        celsius = (value - 32) * 5 / 9
    elif from_unit == "kelvin":
        celsius = value - 273.15
    else:
        raise ValueError(f"Unknown unit: {from_unit}")

    # Convert from Celsius to target
    if to_unit == "celsius":
        result = celsius
    elif to_unit == "fahrenheit":
        result = celsius * 9 / 5 + 32
    elif to_unit == "kelvin":
        result = celsius + 273.15
    else:
        raise ValueError(f"Unknown unit: {to_unit}")

    return {
        "input": f"{value} {from_unit}",
        "output": f"{round(result, 2)} {to_unit}",
        "result": round(result, 2),
    }


def word_count(text: str) -> dict:
    """Count words, characters, and lines in a text string."""
    words = text.split()
    return {
        "words": len(words),
        "characters": len(text),
        "lines": text.count("\n") + 1 if text else 0,
    }
