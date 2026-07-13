from services.moltbook_api_client import MoltbookAPIClient

client = MoltbookAPIClient()

feed = client.get_feed(limit=5)
print("feed_success:", getattr(feed, "success", None))
print("feed_status:", getattr(feed, "status_code", None))
print("feed_error:", getattr(feed, "error", None))

data = getattr(feed, "data", {}) or {}
posts = data.get("posts", []) if isinstance(data, dict) else []

print("posts_found:", len(posts))

if not posts:
    raise SystemExit("No posts returned from feed")

first = posts[0]
print("first_post_type:", type(first).__name__)

if isinstance(first, dict):
    print("first_post_keys:", list(first.keys())[:20])

post_id = None
if isinstance(first, dict):
    post_id = first.get("id") or first.get("_id") or first.get("post_id")

print("post_id:", post_id)

if not post_id:
    raise SystemExit("Could not determine post_id from feed payload")

comments = client.get_comments(post_id=post_id, limit=5)
print("comments_success:", getattr(comments, "success", None))
print("comments_status:", getattr(comments, "status_code", None))
print("comments_error:", getattr(comments, "error", None))

cdata = getattr(comments, "data", None)
print("comments_data_type:", type(cdata).__name__)

if isinstance(cdata, dict):
    print("comments_data_keys:", list(cdata.keys())[:20])
elif isinstance(cdata, list):
    print("comments_len:", len(cdata))
    if cdata and isinstance(cdata[0], dict):
        print("first_comment_keys:", list(cdata[0].keys())[:20])
