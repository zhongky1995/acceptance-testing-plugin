import json
import sys
from contracts import producer_accepts, consumer_accepts

value = json.load(sys.stdin)
print(json.dumps({"producer_accepts": producer_accepts(value), "consumer_accepts": consumer_accepts(value),
                  "producer_evidence": "contracts.py:producer_accepts evaluated input",
                  "consumer_evidence": "contracts.py:consumer_accepts evaluated same input"}))
