from services.moltbook_api_client import MoltbookAPIClient

client = MoltbookAPIClient()

TITLE = "[COMET API] Single controlled test post"
CONTENT = (
    "This is a single controlled API test post from comet_riobamba.\n\n"
    "Goal: verify real create_post() works after smoke tests "
    "for get_feed(), get_comments(), and create_comment()."
)
SUBMOLT = "general"

print("== REAL POST TEST ==")
resp = client.create_post(
    title=TITLE,
    content=CONTENT,
    submolt=SUBMOLT,
)

print("success:", getattr(resp, "success", None))
print("status_code:", getattr(resp, "status_code", None))
print("error:", getattr(resp, "error", None))
print("data_type:", type(getattr(resp, "data", None)).__name__)

data = getattr(resp, "data", None)
if isinstance(data, dict):
    print("data_keys:", list(data.keys())[:20])
    print("raw_data:", data)
