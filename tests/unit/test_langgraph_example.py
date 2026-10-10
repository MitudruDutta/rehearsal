"""The LangGraph ReAct example sends exactly one action per turn and always answers a turn."""

import importlib.util
import pathlib
from types import SimpleNamespace

import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("langchain_openai")

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402

spec = importlib.util.spec_from_file_location("langgraph_react", pathlib.Path(__file__).parents[2] / "examples" / "agents" / "langgraph_react.py")
lg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lg)


class Fake(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


TOOLS = [
    {"type": "function", "function": {"name": "get_ticket", "description": "Read a ticket", "parameters": {"type": "object", "properties": {"ticket_id": {"type": "integer"}, "password": {"type": "string"}}, "required": ["ticket_id"]}}},
    {"type": "function", "function": {"name": "wait", "description": "Wait", "parameters": {"type": "object", "properties": {}}}},
]


def test_one_action_per_turn_and_words_only_answers_yield_the_turn():
    acts = []
    rh = SimpleNamespace(external=SimpleNamespace(act=lambda ep, actor, tool, args, idempotency_key: acts.append((tool, args)) or {"status": 200}))
    two_calls = AIMessage("", tool_calls=[{"name": "get_ticket", "args": {"ticket_id": 42}, "id": "c1"}, {"name": "get_ticket", "args": {"ticket_id": 43}, "id": "c2"}])
    seat = lg.Seat(rh, Fake(responses=[two_calls, AIMessage("All done.")]), "ep_1", "agent")
    assert seat.take_turn({"actor": "agent", "new": [{"role": "system", "content": "You are agent."}, {"role": "user", "content": "check 42"}], "tools": TOOLS}) == "get_ticket"
    assert seat.take_turn({"actor": "agent", "new": [{"role": "tool", "content": "{}"}, {"role": "user", "content": "thanks"}], "tools": TOOLS}) == "wait"
    assert acts == [("get_ticket", {"ticket_id": 42}), ("wait", {})]
