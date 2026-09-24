# reproduce/agent-failing/main.py
#
# Amazon Bedrock AgentCore Runtime 上で動き、意図的に失敗するサンプル エージェント。
# 目的は、各 coding agent ディレクトリ (kiro/, claude-code/, codex/) の
# agentcore-log-investigation Skill が調査する対象のログを CloudWatch Logs に
# 発生させることである。
#
# FAILURE_MODE で失敗の種類を切り替える。
#   tool_exception : ツール呼び出しが例外を投げる (既定)
#   timeout        : ハンドラが長時間応答を返さず、呼び出し元のタイムアウトを誘発する
#   invalid_input   : payload に必須フィールドが無い場合にバリデーション エラーを返す
#   none           : 失敗させない (正常系ログだけを出す動作確認用)
#
# 正常系のログは NORMAL_LOG_LINES 件出力する。文面がほぼ同一のログが大量に並ぶ
# 状況を再現するためであり、Zenn 記事の「ログ調査が Context Rot を起こしやすい
# 理由」で述べている distractor の多さをこのサンプルで再現することが目的である。
#
# tool_exception モードでは、さらに次の 2 点を再現する。
#   - 真因が 1 箇所のログ行にしか現れない ("紛らわしい情報" の再現)。
#     正常系ログのループの中で、これから失敗する customer_id が最後に登場する
#     1 行だけ account_tier の値が "standard" から "suspended" に変わる。
#     この行は "error" や "exception" のような検索しやすい語を含まない。
#   - 失敗メッセージの語彙と、真因の行の語彙が一致しない
#     ("問いと答えの語彙が一致しない" の再現)。ツール呼び出し失敗時のログ
#     ("upstream service rejected the request") は "account_tier" や
#     "suspended" という語を含まないため、失敗メッセージの語で検索しても
#     真因の行にはたどり着かない。
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

from bedrock_agentcore.runtime import BedrockAgentCoreApp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("agent-failing")

app = BedrockAgentCoreApp()

# os.environ.get(KEY, default) は KEY が空文字列で export された場合に既定値へ
# 落ちないため使わない。すべて os.environ.get(KEY) or default の形にする。
FAILURE_MODE = os.environ.get("FAILURE_MODE") or "tool_exception"
NORMAL_LOG_LINES = int(os.environ.get("NORMAL_LOG_LINES") or "200")
TIMEOUT_SLEEP_SECONDS = int(os.environ.get("TIMEOUT_SLEEP_SECONDS") or "120")

_CUSTOMER_IDS = [f"CUST-{n:05d}" for n in range(1, 21)]


def _last_index_for_customer(target_customer_id: str) -> int:
    """target_customer_id が正常系ログのループ中で最後に登場するステップ番号を返す。

    見つからない場合は -1 を返す。真因の 1 行を、失敗する直前の自然な位置
    (その顧客の直近の状態) に置くために使う。
    """
    last_index = -1
    for i in range(NORMAL_LOG_LINES):
        if _CUSTOMER_IDS[i % len(_CUSTOMER_IDS)] == target_customer_id:
            last_index = i
    return last_index


def _emit_normal_logs(
    request_id: str,
    session_id: str | None,
    target_customer_id: str,
    inject_root_cause: bool,
) -> None:
    """正常系の INFO ログを NORMAL_LOG_LINES 件出す。

    文面はほぼ同一で、ステップ番号と顧客 ID だけが変わる。実際のアプリケーション
    ログが distractor になりやすいことを再現するための構成である。

    inject_root_cause が真の場合、target_customer_id が最後に登場する行だけ
    account_tier を "suspended" にする。他の全ての行 (target_customer_id の
    他の出現も含む) は "standard" のままであり、真因はこの 1 行にしか現れない。
    """
    root_cause_index = _last_index_for_customer(target_customer_id) if inject_root_cause else -1

    for i in range(NORMAL_LOG_LINES):
        customer_id = _CUSTOMER_IDS[i % len(_CUSTOMER_IDS)]
        account_tier = "suspended" if i == root_cause_index else "standard"
        logger.info(
            "processing request request_id=%s session_id=%s step=%d customer_id=%s "
            "account_tier=%s status=in_progress",
            request_id,
            session_id,
            i,
            customer_id,
            account_tier,
        )


def _fetch_customer_record(customer_id: str) -> dict:
    """例外を投げるツール呼び出しを模した関数。FAILURE_MODE=tool_exception で使う。

    例外メッセージは "upstream service rejected the request" とだけ述べ、
    _emit_normal_logs が出す真因の行 (account_tier=suspended) の語彙を含まない。
    """
    if FAILURE_MODE == "tool_exception":
        raise RuntimeError(f"failed to fetch customer record for {customer_id}: upstream service rejected the request (HTTP 403)")
    return {"customer_id": customer_id, "status": "ok"}


@app.entrypoint
def invoke(payload, context):
    request_id = str(uuid.uuid4())
    session_id = getattr(context, "session_id", None)

    logger.info(
        "invoke start request_id=%s session_id=%s failure_mode=%s",
        request_id,
        session_id,
        FAILURE_MODE,
    )

    customer_id = payload.get("customer_id") if isinstance(payload, dict) else None
    if not customer_id:
        customer_id = _CUSTOMER_IDS[0]

    _emit_normal_logs(
        request_id,
        session_id,
        target_customer_id=customer_id,
        inject_root_cause=(FAILURE_MODE == "tool_exception"),
    )

    if FAILURE_MODE == "invalid_input":
        if not isinstance(payload, dict) or "customer_id" not in payload:
            logger.error(
                "invalid input request_id=%s session_id=%s error_type=user reason=missing_customer_id",
                request_id,
                session_id,
            )
            return {
                "status": "error",
                "error_type": "invalid_input",
                "reason": "customer_id is required",
                "request_id": request_id,
            }

    if FAILURE_MODE == "timeout":
        logger.warning(
            "simulated slow dependency request_id=%s session_id=%s sleep_seconds=%d",
            request_id,
            session_id,
            TIMEOUT_SLEEP_SECONDS,
        )
        time.sleep(TIMEOUT_SLEEP_SECONDS)
        # 通常は呼び出し元 (クライアントまたはランタイム) のタイムアウトが先に発火し、
        # ここには到達しない想定である。
        return {"status": "ok", "request_id": request_id, "note": "did not actually time out"}

    if FAILURE_MODE == "tool_exception":
        try:
            record = _fetch_customer_record(customer_id)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "tool call failed request_id=%s session_id=%s customer_id=%s error_type=%s error_message=%s",
                request_id,
                session_id,
                customer_id,
                type(exc).__name__,
                exc,
            )
            return {
                "status": "error",
                "error_type": "tool_exception",
                "reason": str(exc),
                "request_id": request_id,
            }
        logger.info("tool call succeeded request_id=%s record=%s", request_id, json.dumps(record))

    logger.info(
        "invoke end request_id=%s session_id=%s status=ok now=%s",
        request_id,
        session_id,
        datetime.now(timezone.utc).isoformat(),
    )
    return {
        "status": "ok",
        "request_id": request_id,
        "session_id": session_id,
        "failure_mode": FAILURE_MODE,
    }


if __name__ == "__main__":
    app.run()
