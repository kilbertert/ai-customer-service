"""PR13: ChatRequest.attachment_ids field validation (unit tests).

Imports are deferred into each test so the conftest's autouse fixtures
get a chance to fully load `api.v1.schemas` (which itself triggers
`services.__init__.py`) first — same pattern as the PR11 widget locale
tests.
"""

import pytest
from pydantic import ValidationError


def _req(ids):
    from api.v1.schemas import ChatRequest
    return ChatRequest(agent_id="agt_test", message="hello", attachment_ids=ids)


def test_attachment_ids_default_is_empty():
    from api.v1.schemas import ChatRequest
    req = ChatRequest(agent_id="agt_test", message="hi")
    assert req.attachment_ids == []


def test_attachment_ids_accepts_valid_format():
    req = _req(["att_0123456789ab", "att_abcdefabcdef"])
    assert len(req.attachment_ids) == 2


@pytest.mark.parametrize("bad", ["bad_id", "att_xyz", "att_", "att_12", "att_1234567890abc"])
def test_attachment_ids_rejects_bad_format(bad):
    with pytest.raises(ValidationError):
        _req([bad])


def test_attachment_ids_rejects_more_than_three():
    with pytest.raises(ValidationError):
        _req(["att_0123456789ab", "att_0123456789ac", "att_0123456789ad", "att_0123456789ae"])
