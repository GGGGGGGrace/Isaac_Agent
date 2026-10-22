import json

pages = {json.loads(l)["metadata"]["page"] for l in open("data/chunks/chunks.jsonl", encoding="utf-8")}
missing = []
for line in open("eval/questions.jsonl", encoding="utf-8"):
    q = json.loads(line)
    for p in q["expected_pages"]:
        if p not in pages:
            missing.append((q["id"], p))
print("all expected pages covered" if not missing else f"missing: {missing}")