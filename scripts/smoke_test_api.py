from config.credentials import Credentials
from services.moltbook_api_client import MoltbookAPIClient

creds = Credentials.from_env()

print("== MOLTBOOK CREDENTIALS ==")
print("base_url:", creds.moltbook_base_url)
print("has_api_key:", bool(creds.moltbook_api_key))

print()
print("== FEED TEST ==")
client = MoltbookAPIClient()
resp = client.get_feed(limit=5)

print("success:", getattr(resp, "success", None))
print("status_code:", getattr(resp, "status_code", None))
print("error:", getattr(resp, "error", None))

data = getattr(resp, "data", None)
print("data_type:", type(data).__name__)

if isinstance(data, dict):
    print("data_keys:", list(data.keys())[:20])
elif isinstance(data, list):
    print("data_len:", len(data))
    if data:
        first = data[0]
        print("first_item_type:", type(first).__name__)
        if isinstance(first, dict):
            print("first_item_keys:", list(first.keys())[:20])

