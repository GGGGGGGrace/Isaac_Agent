from config import MODEL_NAME          # first: keeps HF offline mode
from search import retrieve

checks = {
    "p01": ("Which item turns my shots into a blood laser that I have to charge up?", "charged blood laser"),
    "f03": ("What does the D6 do and how long is its recharge?", "6 rooms"),
    "p02": ("Is there an active item that rerolls every item pedestal in the room I'm in?", "re-rolls all items"),
    "v02": ("What happens if I pick up two Brimstones in Repentance compared to older versions?", "first additional copy"),
}
for qid, (question, phrase) in checks.items():
    hits = retrieve(question, k=30)
    ranks = [h["rank"] for h in hits if phrase.lower() in h["text"].lower()]
    print(qid, "evidence at ranks:", ranks or "not in top 30", "| top 3:", [h["chunk_id"] for h in hits[:3]])