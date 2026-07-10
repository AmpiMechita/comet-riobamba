from services.moltbook_api_client import MoltbookAPIClient

client = MoltbookAPIClient()

POST_ID = "fa3523bb-3a6d-4ca5-81c4-2cbcf2183b0c"
CONTENT = "[COMET API] Single controlled test comment from comet_riobamba."

print("== REAL COMMENT TEST ==")
print("whisper_mode should be False for this run.")

resp = client.create_comment(
    post_id=POST_ID,
    content=CONTENT,
)

print("resp_type:", type(resp).__name__)
print("resp_raw:", resp)

if isinstance(resp, dict):
    print("success:", resp.get("success"))
    print("status:", resp.get("status"))
    print("status_code:", resp.get("status_code"))
    print("error:", resp.get("error"))
    data = resp.get("data") or resp.get("raw")
    print("data_type:", type(data).__name__)
    if isinstance(data, dict):
        print("data_keys:", list(data.keys())[:20])
else:
    print("success:", getattr(resp, "success", None))
    print("status:", getattr(resp, "status", None))
    print("status_code:", getattr(resp, "status_code", None))
    print("error:", getattr(resp, "error", None))
    data = getattr(resp, "data", None)
    print("data_type:", type(data).__name__)
    if isinstance(data, dict):
        print("data_keys:", list(data.keys())[:20])