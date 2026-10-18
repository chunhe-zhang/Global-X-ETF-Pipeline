"""Load the public multi-region Global X catalog snapshot."""
import json
from pathlib import Path

_DATA = json.loads((Path(__file__).parent / "catalog_data.json").read_text(encoding="utf-8"))
PRODUCTS = _DATA["products"]
CATALOG_AS_OF = _DATA["catalog_as_of"]
