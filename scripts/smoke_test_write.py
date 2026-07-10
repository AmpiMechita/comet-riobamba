from services.moltbook_api_client import MoltbookAPIClient

client = MoltbookAPIClient()

print("== CREATE POST TEST ==")
post_resp = client.create_post(
    title="Comet API smoke test",
    content="This is a controlled smoke test from comet_riobamba.",
    submolt="general"
)
print("post_success:", getattr(post_resp, "success", None))
print("post_status:", getattr(post_resp, "status_code", None))
print("post_error:", getattr(post_resp, "error", None))
print("post_data_type:", type(getattr(post_resp, "data", None)).__name__)

print()
print("== CREATE COMMENT TEST ==")
comment_resp = client.create_comment(
    post_id="fa3523bb-3a6d-4ca5-81c4-2cbcf2183b0c",
    content="Controlled API smoke test comment from comet_riobamba."
)
print("comment_success:", getattr(comment_resp, "success", None))
print("comment_status:", getattr(comment_resp, "status_code", None))
print("comment_error:", getattr(comment_resp, "error", None))
print("comment_data_type:", type(getattr(comment_resp, "data", None)).__name__)
