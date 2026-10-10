from rehearsal.compiler.apispec import operations, to_tool


def test_openapi3_ref_body_resolves_to_parameters():
    # requestBody.content.<media>.schema is deep before the $ref: nesting must not truncate it (Chatwoot)
    spec = {
        "openapi": "3.1.0",
        "paths": {"/api/v1/accounts/{account_id}/agents": {"post": {
            "operationId": "add-new-agent",
            "parameters": [{"name": "account_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
            "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/agent"}}}},
        }}},
        "components": {"schemas": {"agent": {"type": "object", "required": ["name", {"bad": 1}], "properties": {"name": {"type": "string"}, "role": {"type": "string", "enum": ["agent", "administrator"]}}}}},
    }
    (op,) = operations(spec)
    tool = to_tool(op, name="add_agent", description="Add an agent", service="web", roles=["admin"])
    assert [(p.name, p.location, p.required) for p in tool.params] == [("account_id", "path", True), ("name", "body", True), ("role", "body", False)]


def test_cyclic_refs_stop():
    spec = {"swagger": "2.0", "paths": {"/n": {"post": {"parameters": [{"in": "body", "name": "b", "schema": {"$ref": "#/definitions/N"}}]}}},
            "definitions": {"N": {"type": "object", "properties": {"child": {"$ref": "#/definitions/N"}}}}}
    (op,) = operations(spec)
    assert op.body["properties"]["child"]["properties"]["child"]


def test_tool_params_drop_malformed_schema_keywords():
    # worlds compiled before the resolver fix stored truncated values; providers reject the whole tool list
    from rehearsal.core.contracts import ToolParam, clean_schema

    bad = {"type": {"type": "object"}, "format": {"type": "object"}, "description": "{'type': 'object'}"}
    assert clean_schema(bad) == {}
    p = ToolParam.model_validate({"name": "branch", "location": "body", "schema": bad, "description": "{'type': 'object'}"})
    assert p.schema_ == {} and p.description == ""
    assert clean_schema({"type": "integer", "format": "int64", "minimum": 0, "enum": [1, 2]}) == {"type": "integer", "format": "int64", "minimum": 0, "enum": [1, 2]}
    assert clean_schema({"type": "boolean", "default": False}) == {"type": "boolean", "default": False}
    assert clean_schema({"type": "array"}) == {"type": "array", "items": {}}


def test_tools_resolve_operations_however_the_model_names_them():
    from rehearsal.compiler.apispec import Operation
    from rehearsal.compiler.pipeline import _find_operation, _manual_tool

    ops = [
        Operation("list_all_conversations", "GET", "/api/v1/accounts/{account_id}/conversations", "", []),
        Operation("create_a_new_message", "POST", "/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages", "", []),
    ]
    index = {o.op_id: o for o in ops}
    assert _find_operation(ops, index, {"op_id": "List-All-Conversations"}).op_id == "list_all_conversations"
    assert _find_operation(ops, index, {"op_id": "GET /api/v1/accounts/{id}/conversations"}).op_id == "list_all_conversations"
    assert _find_operation(ops, index, {"op_id": "web:POST /api/v1/accounts/:a/conversations/:c/messages"}).op_id == "create_a_new_message"
    assert _find_operation(ops, index, {"method": "get", "path": "/api/v1/accounts/{a}/conversations/"}).op_id == "list_all_conversations"
    assert _find_operation(ops, index, {"op_id": "invented_name"}) is None
    # an application without a specification: the tool is defined directly
    tool = _manual_tool({"method": "GET", "path": "/api/v4/users/:user_id", "description": "Get a user", "roles": ["member"]}, name="get_user", service="mattermost")
    assert tool.path == "/api/v4/users/{user_id}" and tool.params[0].location == "path" and not tool.mutating


def test_submit_arguments_sent_as_json_text_are_parsed():
    from rehearsal.compiler.agent import _unstring

    assert _unstring({"tools": '[{"name": "a"}]', "note": "plain text", "n": 3}) == {"tools": [{"name": "a"}], "note": "plain text", "n": 3}
    assert _unstring({"tools": "[not json"}) == {"tools": "[not json"}


def test_login_session_tokens_are_recognised_by_their_expiry():
    import base64, json, time

    from rehearsal.compiler.pipeline import token_ttl

    def jwt(claims):
        part = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
        return f"Bearer {part({'alg': 'HS256'})}.{part(claims)}.sig"

    assert 500 < token_ttl(jwt({"exp": time.time() + 600})) <= 600  # ten-minute session
    assert token_ttl(jwt({"sub": "1"})) is None and token_ttl("Bearer tk_1234567890abcdef") is None
