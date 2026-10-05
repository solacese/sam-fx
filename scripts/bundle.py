"""Embed local JSON so the static page also works with file://."""
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
data=json.loads((root/'data/snapshot.json').read_text())
(root/'data/bundle.js').write_text('window.SNAPSHOT = '+json.dumps(data,separators=(',',':'))+';\n')
