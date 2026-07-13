from services.moltbook_api_client import MoltbookAPIClient

client = MoltbookAPIClient()

VERIFICATION_CODE = "moltbook_verify_cd420111944ae996de4af1ef7247996f"
ANSWER = "44.00"

print("== VERIFY POST TEST ==")
resp = client.submit_verification(
    verification_code=VERIFICATION_CODE,
    answer=ANSWER,
)

print("resp_type:", type(resp).__name__)
print("resp_raw:", resp)

if isinstance(resp, dict):
    print("success:", resp.get("success"))
    print("status:", resp.get("status"))
    print("error:", resp.get("error"))
    raw = resp.get("raw")
    print("raw_type:", type(raw).__name__)
    if isinstance(raw, dict):
        print("raw_keys:", list(raw.keys())[:20])
else:
    print("success:", getattr(resp, "success", None))
    print("status_code:", getattr(resp, "status_code", None))
    print("error:", getattr(resp, "error", None))
    data = getattr(resp, "data", None)
    print("data_type:", type(data).__name__)