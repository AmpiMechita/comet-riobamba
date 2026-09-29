# -*- coding: utf-8 -*-
"""Tests dirigidos a P-122: karma_updater usa fetch_post_comments(paginate=True)
para encontrar comentarios propios que caen en pagina >=2."""

from unittest.mock import MagicMock

from services.karma_updater import update_karma_from_moltbook


def test_comment_paginate_true_passed_to_client():
    """P-122: el wrapper DEBE pedir paginacion para no perder comentarios
    que caen fuera de la primera pagina."""
    client = MagicMock()
    client.fetch_post_comments.return_value = [
        {"id": "mid-1", "upvotes": 3, "reply_count": 0},
    ]
    entry = {"type": "comment", "moltbook_id": "mid-1", "thread_id": "post-uuid"}

    result = update_karma_from_moltbook(client, entry)

    assert result["success"] is True
    assert result["upvotes"] == 3
    client.fetch_post_comments.assert_called_once_with("post-uuid", paginate=True, max_pages=50)


def test_comment_found_only_when_paginated():
    """Simula la API real: sin paginate solo hay pagina 1; con paginate
    aparece el comentario buscado. Verifica el bug que P-122 corrige."""
    page1 = [{"id": f"other-{i}", "upvotes": 0} for i in range(50)]
    page2 = [{"id": "mid-deep", "upvotes": 9, "reply_count": 1}]

    def fake_fetch(pid, *args, **kwargs):
        if kwargs.get("paginate"):
            return page1 + page2
        return page1

    client = MagicMock()
    client.fetch_post_comments.side_effect = fake_fetch
    entry = {"type": "comment", "moltbook_id": "mid-deep", "thread_id": "post-uuid"}

    result = update_karma_from_moltbook(client, entry)

    assert result["success"] is True
    assert result["upvotes"] == 9
    assert result["comments"] == 1
