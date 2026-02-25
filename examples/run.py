"""Launch MCP server with all example modules — class-based + binding.yaml.

Usage (from the project root):
    PYTHONPATH=./examples/binding_demo python examples/run.py

Then open http://127.0.0.1:8000/explorer/ in your browser.
"""

from apcore import BindingLoader, Registry

from apcore_mcp import serve

# 1. Discover class-based modules from extensions/
registry = Registry(extensions_dir="./examples/extensions")
n_class = registry.discover()

# 2. Load binding.yaml modules into the same registry
loader = BindingLoader()
binding_modules = loader.load_binding_dir("./examples/binding_demo/extensions", registry)

print(f"Class-based modules: {n_class}")
print(f"Binding modules:     {len(binding_modules)}")
print(f"Total:               {len(registry.module_ids)}")

# 3. Launch MCP server with Explorer UI
serve(
    registry,
    transport="streamable-http",
    host="127.0.0.1",
    port=8000,
    explorer=True,
    allow_execute=True,
)
