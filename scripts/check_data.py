import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
data=json.loads((root/'data/snapshot.json').read_text())
assert [a['id'] for a in data['answers']]==['where','last30','feed']
assert len(data['candles'])==24
for c in data['candles']:
    assert c['low']<=min(c['open'],c['close'])<=max(c['open'],c['close'])<=c['high'],c
last=data['candles'][-6:]
assert last[0]['open']==1.12032 and last[-1]['close']==1.12007
assert round((last[-1]['close']-last[0]['open'])*10000,1)==-2.5
assert round((max(c['high'] for c in last)-min(c['low'] for c in last))*10000,1)==8.8
assert (root/'data/bundle.js').read_text()=='window.SNAPSHOT = '+json.dumps(data,separators=(',',':'))+';\n'
print('PASS: 3 prepared answers, 24 valid candles, exact 30-minute snapshot stats, matching browser bundle.')
