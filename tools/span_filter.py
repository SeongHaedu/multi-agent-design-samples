"""OTEL スパンの DROP / KEEP ノイズフィルタ。

パターンの出典: cloudwatch-mcp-server の agentcore-investigation Skill が公開している
otel-span-schema.md である。以下に実装した DROP / KEEP のパターンと理由は、
このファイルに記載されているものだけであり、新しいパターンは追加していない。

https://github.com/awslabs/mcp/blob/main/src/cloudwatch-mcp-server/skills/agentcore-investigation/references/otel-span-schema.md

otel-span-schema.md 自体はパターンと理由の 2 つの表だけで構成されており、
判定を行う実装コードは含まれていない。したがって、各パターンをどのフィールドで
判定するかはこのモジュールの実装判断である。想定しているのは、CloudWatch Logs
Insights が返す 1 行 (@timestamp, @message などを持つ辞書) を JSON として
パースしたレコード、または OTEL の resourceSpans/scopeSpans/spans 構造を持つ
レコードである。

依存は標準ライブラリのみ。
"""

from typing import Any

# DROP: 除外するパターンと理由。otel-span-schema.md の表をそのまま転記している。
DROP_REASONS: dict[str, str] = {
    "resource_spans_metadata_only": "OTel envelope, no signal (resourceSpans wrapper with only metadata)",
    "empty_scope_spans": "Empty instrumentation scope (scopeSpans with empty spans[])",
    "instrumentation_scope_metadata_only": "SDK metadata (InstrumentationScope lines with only library name/version)",
    "repeated_schema_url": "Schema boilerplate (repeated schemaUrl entries)",
    "resource_attributes_metadata_only": (
        "Resource metadata, not signal "
        "(resource.attributes containing only service.name, telemetry.sdk.*)"
    ),
    "heartbeat": "Infrastructure noise (heartbeat/keepalive messages)",
    "cw_insights_pointer": "Internal CW pointers (@ptr fields from CW Insights)",
}

# KEEP: 残すパターンと理由。DROP と同じく otel-span-schema.md の表をそのまま転記している。
KEEP_REASONS: dict[str, str] = {
    "error_like": "Errors always matter (any message with error, exception, fault)",
    "duration_positive": "Actual span completions (messages with duration > 0)",
    "tool_invocation": "Tool invocations (messages with tool_use, toolUse, function_call)",
    "non_ok_status": "Non-OK spans (messages with statusCode != 0)",
    "model_inference": "Model inference calls (messages with model_id or modelId)",
    "trace_boundary": "Session boundaries (first and last message per traceId)",
}

_ERROR_KEYWORDS = ("error", "exception", "fault")
_MESSAGE_LIKE_FIELDS = ("@message", "message", "body", "error_type", "statusMessage", "exceptionMessage")


def _text_fields(record: dict[str, Any]) -> str:
    """record からメッセージ相当のテキストフィールドを集めて 1 つの文字列にする。"""
    parts = [record[key] for key in _MESSAGE_LIKE_FIELDS if isinstance(record.get(key), str)]
    return " ".join(parts)


def _is_resource_spans_metadata_only(record: dict[str, Any]) -> bool:
    """resourceSpans wrapper with only metadata。

    record が resourceSpans を持つが、その下の scopeSpans のいずれにも
    spans エントリが存在しない場合、メタデータだけの OTel envelope とみなす。
    """
    resource_spans = record.get("resourceSpans")
    if not isinstance(resource_spans, list) or not resource_spans:
        return False
    for entry in resource_spans:
        if not isinstance(entry, dict):
            continue
        for scope_span in entry.get("scopeSpans", []) or []:
            if isinstance(scope_span, dict) and scope_span.get("spans"):
                return False
    return True


def _is_empty_scope_spans(record: dict[str, Any]) -> bool:
    """scopeSpans with empty spans[]。"""
    scope_spans = record.get("scopeSpans")
    if isinstance(scope_spans, list) and scope_spans:
        return all(isinstance(s, dict) and not s.get("spans") for s in scope_spans)
    if isinstance(scope_spans, dict):
        return not scope_spans.get("spans")
    return False


def _is_instrumentation_scope_metadata_only(record: dict[str, Any]) -> bool:
    """InstrumentationScope lines with only library name/version。"""
    scope = record.get("instrumentationScope") or record.get("InstrumentationScope")
    if not isinstance(scope, dict) or not scope:
        return False
    return set(scope.keys()) <= {"name", "version"}


def _is_resource_attributes_metadata_only(record: dict[str, Any]) -> bool:
    """resource.attributes containing only service.name, telemetry.sdk.*。"""
    resource = record.get("resource")
    if not isinstance(resource, dict):
        return False
    attributes = resource.get("attributes")
    if not isinstance(attributes, dict) or not attributes:
        return False
    for key in attributes:
        if key != "service.name" and not key.startswith("telemetry.sdk."):
            return False
    return True


def _is_heartbeat(record: dict[str, Any]) -> bool:
    """Heartbeat/keepalive messages。"""
    text = _text_fields(record).lower()
    return "heartbeat" in text or "keepalive" in text or "keep-alive" in text


def _is_cw_insights_pointer_only(record: dict[str, Any]) -> bool:
    """@ptr fields from CW Insights。

    @timestamp を除いたキーが @ptr のみである場合、CloudWatch Logs Insights が
    付与する内部ポインタだけのレコードとみなす。
    """
    keys = set(record.keys()) - {"@timestamp"}
    return keys == {"@ptr"}


def match_drop(record: dict[str, Any], *, seen_schema_urls: set[str] | None = None) -> str | None:
    """record が DROP パターンに一致する場合、そのパターン名 (DROP_REASONS のキー) を返す。

    一致しなければ None を返す。

    Args:
        record: 判定対象の 1 レコード。
        seen_schema_urls: 「repeated schemaUrl entries」の判定に使う、
            これまでに見た schemaUrl の集合。呼び出し側がレコードの並びを
            走査しながら同じ集合を渡し続けることで、2 回目以降の出現を
            repeated_schema_url として判定できる。省略した場合、この
            パターンの判定はスキップされる (単体テストで他のパターンだけを
            検証できるようにするため)。
    """
    if _is_resource_spans_metadata_only(record):
        return "resource_spans_metadata_only"
    if _is_empty_scope_spans(record):
        return "empty_scope_spans"
    if _is_instrumentation_scope_metadata_only(record):
        return "instrumentation_scope_metadata_only"

    schema_url = record.get("schemaUrl")
    if isinstance(schema_url, str) and schema_url and seen_schema_urls is not None:
        if schema_url in seen_schema_urls:
            return "repeated_schema_url"
        seen_schema_urls.add(schema_url)

    if _is_resource_attributes_metadata_only(record):
        return "resource_attributes_metadata_only"
    if _is_heartbeat(record):
        return "heartbeat"
    if _is_cw_insights_pointer_only(record):
        return "cw_insights_pointer"
    return None


def match_keep(record: dict[str, Any], *, is_trace_boundary: bool = False) -> str | None:
    """record が KEEP パターンに一致する場合、そのパターン名 (KEEP_REASONS のキー) を返す。

    一致しなければ None を返す。

    Args:
        record: 判定対象の 1 レコード。
        is_trace_boundary: record が、同じ traceId を持つ一連のレコードの
            先頭または末尾であるかどうか。この関数単体では traceId の
            前後関係を判定できないため、呼び出し側 (filter_spans など) が
            判定してから渡す。
    """
    text = _text_fields(record).lower()
    if any(keyword in text for keyword in _ERROR_KEYWORDS):
        return "error_like"

    duration = record.get("duration") or record.get("duration_ms") or record.get("latency_ms")
    if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration > 0:
        return "duration_positive"

    if any(key in record for key in ("tool_use", "toolUse", "function_call")):
        return "tool_invocation"

    status_code = record.get("statusCode")
    if status_code is not None and status_code != 0:
        return "non_ok_status"

    if record.get("model_id") or record.get("modelId"):
        return "model_inference"

    if is_trace_boundary:
        return "trace_boundary"

    return None


def _trace_boundary_ids(records: list[dict[str, Any]]) -> set[int]:
    """各 traceId の先頭・末尾レコードの id() を集める。

    traceId は record 直下の "traceId" キーを前提とする。このキーを持たない
    レコードはどの traceId にも属さないため、境界判定の対象にしない。
    """
    positions: dict[str, list[int]] = {}
    for index, record in enumerate(records):
        trace_id = record.get("traceId")
        if not trace_id:
            continue
        positions.setdefault(trace_id, []).append(index)

    boundary_ids: set[int] = set()
    for indexes in positions.values():
        boundary_ids.add(id(records[indexes[0]]))
        boundary_ids.add(id(records[indexes[-1]]))
    return boundary_ids


def filter_spans(records: list[dict[str, Any]]) -> dict[str, Any]:
    """otel-span-schema.md が定義する 4 ステップの処理を適用する。

    1. Count total results received
    2. Remove entries matching DROP patterns (count removed)
    3. Keep entries matching KEEP patterns
    4. Log: "Filtered: {total} -> {kept} spans ({removed} noise entries dropped)"

    ステップ 3 は「KEEP パターンに一致するものだけを残す」という意味で実装している。
    DROP に一致せず、かつ KEEP のどのパターンにも一致しないレコード (ノイズとも
    信号とも判定できないもの) は、最終的な kept_records には含まれない。

    Returns:
        total (件数), kept_count (残った件数), removed_count (除いた件数),
        kept_records (残ったレコードのリスト), log_line (ステップ 4 のログ文字列)
        を含む辞書。
    """
    total = len(records)
    boundary_ids = _trace_boundary_ids(records)
    seen_schema_urls: set[str] = set()

    after_drop = [
        record for record in records if match_drop(record, seen_schema_urls=seen_schema_urls) is None
    ]

    kept_records = [
        record
        for record in after_drop
        if match_keep(record, is_trace_boundary=id(record) in boundary_ids) is not None
    ]

    kept_count = len(kept_records)
    removed_count = total - kept_count
    log_line = f"Filtered: {total} → {kept_count} spans ({removed_count} noise entries dropped)"

    return {
        "total": total,
        "kept_count": kept_count,
        "removed_count": removed_count,
        "kept_records": kept_records,
        "log_line": log_line,
    }
