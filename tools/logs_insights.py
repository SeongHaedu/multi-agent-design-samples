"""Amazon CloudWatch Logs Insights を実行し、要約した結果を返すユーティリティ。

run_logs_insights_query() は生のログ レコードを返さない。返すのは次の 3 種類に
要約した辞書だけである。

- record_count: クエリが返したレコードの件数。
- representative_records: 代表例。先頭 5 件のみ。
- field_value_counts: フィールド (@message, level, errorType) ごとに、
  出現回数が多い上位 5 件の値を集計したもの。

目的は、ログの生レコードを呼び出し元 (main agent や subagent) の context に
流し込まず、要約だけを渡すことで context を節約することである。件数を絞る
`| limit` はサーバー側 (CloudWatch Logs Insights API) の対策であり、この要約は
クライアント側でさらに切り詰める対策にあたる。

依存は boto3 のみ。StartQuery / GetQueryResults / StopQuery の 3 API をラップする。
参考実装: awslabs/agentcore-samples の
06-workshops/07-AgentCore-evaluations/03-advanced/01-end-to-end-on-demand-with-boto3/utils/cloudwatch_client.py
https://github.com/awslabs/agentcore-samples/blob/main/06-workshops/07-AgentCore-evaluations/03-advanced/01-end-to-end-on-demand-with-boto3/utils/cloudwatch_client.py
"""

import argparse
import json
import os
import time
from collections import Counter
from typing import Any

import boto3
from botocore.exceptions import ClientError

POLL_INTERVAL_SECONDS = 2
DEFAULT_TIMEOUT_SECONDS = 60


def run_logs_insights_query(
    log_group_name: str,
    query_string: str,
    start_time: int,
    end_time: int,
    limit: int,
    region_name: str = "us-east-1",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Logs Insights クエリを実行し、結果を要約した辞書で返す。

    Args:
        log_group_name: 対象ログ グループ名。
        query_string: Logs Insights クエリ文字列。`| limit` を含めない場合は
            この関数が自動で末尾に追加する。
        start_time: 検索開始時刻 (epoch seconds)。
        end_time: 検索終了時刻 (epoch seconds)。
        limit: クエリに強制する上限件数。StartQuery / クエリ内 `| limit` の
            いずれにも既定値の記載がないため、呼び出し側に明示を必須とする。
        region_name: クエリを実行するリージョン。
        timeout_seconds: ポーリングのタイムアウト。CloudWatch Logs 自体は
            60 分でクエリをタイムアウトするが、subagent の応答時間を優先し
            既定を 60 秒に短く設定している。

    Returns:
        件数・代表例・集計値に要約した辞書。ログの生レコードはそのまま
        含めない。
    """
    if "| limit" not in query_string and "|limit" not in query_string:
        query_string = f"{query_string} | limit {limit}"

    client = boto3.client("logs", region_name=region_name)

    start_response = client.start_query(
        logGroupName=log_group_name,
        startTime=start_time,
        endTime=end_time,
        queryString=query_string,
        limit=limit,
    )
    query_id = start_response["queryId"]

    deadline = time.monotonic() + timeout_seconds
    response: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get_query_results(queryId=query_id)
        status = response.get("status")
        # API の status が取り得る継続状態は "Running" と "Scheduled" だけ
        # であり、それ以外はすべて終了状態である。"Timeout" (クエリ自体が
        # 60 分の上限に達した場合) と "Unknown" もここに含めないと、
        # 該当した際にポーリングが終了せず PollingTimeout まで待ち続ける。
        if status in ("Complete", "Failed", "Cancelled", "Timeout", "Unknown"):
            break
        time.sleep(POLL_INTERVAL_SECONDS)
    else:
        try:
            client.stop_query(queryId=query_id)
        except ClientError:
            # StopQuery は既に終了したクエリに対してエラーを返す仕様であり、
            # ポーリング打ち切りの時点でクエリが完了済みでも処理を継続する。
            pass
        return {
            "status": "PollingTimeout",
            "query_id": query_id,
            "record_count": 0,
            "representative_records": [],
            "field_value_counts": {},
        }

    if response.get("status") != "Complete":
        return {
            "status": response.get("status", "Unknown"),
            "query_id": query_id,
            "record_count": 0,
            "representative_records": [],
            "field_value_counts": {},
        }

    records = [
        {field["field"]: field["value"] for field in line}
        for line in response.get("results", [])
    ]

    if not records:
        return {
            "status": "Complete",
            "query_id": query_id,
            "record_count": 0,
            "representative_records": [],
            "field_value_counts": {},
        }

    return _summarize(records, query_id)


def _summarize(records: list[dict[str, str]], query_id: str) -> dict[str, Any]:
    """生レコードを件数・代表例・集計値に要約する。

    Context Rot 対策の本体はここである。呼び出し元の context には、
    この要約だけを渡し、records そのものは渡さない。
    """
    representative_count = min(5, len(records))
    field_value_counts: dict[str, dict[str, int]] = {}
    for field_name in ("@message", "level", "errorType"):
        values = [r[field_name] for r in records if field_name in r]
        if values:
            field_value_counts[field_name] = dict(Counter(values).most_common(5))

    return {
        "status": "Complete",
        "query_id": query_id,
        "record_count": len(records),
        "representative_records": records[:representative_count],
        "field_value_counts": field_value_counts,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "CloudWatch Logs Insights クエリを実行し、要約した JSON を標準出力に印字する。"
        )
    )
    parser.add_argument(
        "--log-group",
        default=os.environ.get("LOG_GROUP_NAME") or None,
        help="対象ログ グループ名。LOG_GROUP_NAME 環境変数でも指定できる。",
    )
    parser.add_argument(
        "--query",
        default=os.environ.get("QUERY_STRING") or "fields @timestamp, @message",
        help="Logs Insights クエリ文字列。既定は fields @timestamp, @message。",
    )
    parser.add_argument(
        "--minutes",
        type=int,
        default=int(os.environ.get("LOOKBACK_MINUTES") or "60"),
        help="現在時刻からの遡り時間 (分)。既定は 60 分。",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=int(os.environ.get("QUERY_LIMIT") or "50"),
        help="クエリに強制する上限件数。既定は 50。",
    )
    parser.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION") or "us-east-1",
        help="クエリを実行するリージョン。既定は us-east-1。",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.environ.get("QUERY_TIMEOUT_SECONDS") or str(DEFAULT_TIMEOUT_SECONDS)),
        help=f"ポーリングのタイムアウト (秒)。既定は {DEFAULT_TIMEOUT_SECONDS}。",
    )
    args = parser.parse_args()
    if not args.log_group:
        parser.error("--log-group または LOG_GROUP_NAME 環境変数が必要である。")
    return args


def main() -> None:
    args = _parse_args()
    end_time = int(time.time())
    start_time = end_time - args.minutes * 60

    result = run_logs_insights_query(
        log_group_name=args.log_group,
        query_string=args.query,
        start_time=start_time,
        end_time=end_time,
        limit=args.limit,
        region_name=args.region,
        timeout_seconds=args.timeout,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
