import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from services.persistence import load_agent_state, save_agent_state


def main():
    state = load_agent_state()
    state["posts_today"] = 0
    save_agent_state(state)
    print("posts_today reset to 0:", state)


if __name__ == "__main__":
    main()
