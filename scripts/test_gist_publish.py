from dotenv import load_dotenv
import os, requests, json

load_dotenv(override=True)
token = os.getenv("GITHUB_TOKEN")

print("Using token prefix:", token[:8])

payload = {
    "description": "COMET-RIOBAMBA manual test gist",
    "public": False,
    "files": {
        "comet_test.md": {
            "content": "# Test\n\nGist creado manualmente desde COMET-RIOBAMBA."
        }
    }
}

r = requests.post(
    "https://api.github.com/gists",
    headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"
    },
    data=json.dumps(payload),
    timeout=30,
)

print("Status:", r.status_code)
print("Body:", r.text[:200])