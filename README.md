English | [Japanese](README_JA.md)

# Multi-Agent Design Samples: AgentCore Runtime Log Investigation

> [!NOTE]
> This repository is not provided by AWS. It is a sample accompanying a blog post, based on verification in one personal environment. My opinions are my own.

Sample code for a workflow-style Agent Skill that investigates Amazon Bedrock AgentCore Runtime logs without flooding the main agent's context with raw log records. The skill delegates log retrieval, noise filtering, and summarization to a subagent; the subagent returns only a JSON summary and a file path, and the raw records never enter the main agent's context.

Blog post (Japanese): (記事公開後に追記)

## Structure

```
.
├── skills/
│   └── agentcore-log-investigation/
│       └── SKILL.md             Workflow-style Agent Skill. Pipeline Display, 4 steps
│                                 (confirm objective / retrieve+summarize via subagent /
│                                 present conclusion / review the conclusion via subagent),
│                                 each with Constraints, Acceptance Criteria, and a
│                                 fixed-format Checkpoint.
├── tools/
│   ├── logs_insights.py         CloudWatch Logs Insights query helper. Wraps StartQuery /
│                                 GetQueryResults polling and summarizes the result into
│                                 record_count / representative_records / field_value_counts.
│                                 boto3 only.
│   └── span_filter.py           DROP / KEEP noise filter for OTEL spans, following the
│                                 patterns published in cloudwatch-mcp-server's
│                                 agentcore-investigation skill. Standard library only.
├── agent-failing/
│   ├── main.py                  Sample agent that fails on purpose, so that there are logs
│                                 worth investigating. FAILURE_MODE switches between a tool
│                                 exception, a timeout, and an invalid-input error.
│   ├── Dockerfile
│   └── requirements.txt
├── scripts/
│   ├── deploy.py                Deploy agent-failing to AgentCore Runtime.
│   └── cleanup.py               Delete the resources deploy.py created.
├── requirements.txt              boto3 only
└── .gitignore
```

## Prerequisites

- Python 3.10 or later.
- AWS credentials with, at minimum, the following IAM permissions for `tools/logs_insights.py`:
  - `logs:StartQuery`
  - `logs:GetQueryResults`
  - `logs:StopQuery`
  - `logs:DescribeLogGroups`
- `scripts/deploy.py` and `scripts/cleanup.py` create and delete more than log queries: an AgentCore Runtime, an ECR repository, and an IAM role. Running them needs additional permissions for `bedrock-agentcore-control` (`CreateAgentRuntime`, `DeleteAgentRuntime`, `ListAgentRuntimes`, `GetAgentRuntime`), `ecr` (`CreateRepository`, `DeleteRepository`, `DescribeRepositories`), and `iam` (`CreateRole`, `DeleteRole`, `PutRolePolicy`, `DeleteRolePolicy`, `GetRole`, `ListRoleTags`). This repository does not run those scripts itself, so start from the four log permissions above and add the rest only when you actually deploy.
- Docker with `docker buildx` if you build the `agent-failing` container image yourself. AgentCore Runtime microVMs run ARM64 Linux.

## Setup

```bash
git clone https://github.com/SeongHaedu/multi-agent-design-samples.git
cd multi-agent-design-samples

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run every command below from the repository root.

## Using the skill

`skills/agentcore-log-investigation/SKILL.md` is a Claude Code Agent Skill. Copy the
`skills/agentcore-log-investigation/` directory into a project that has Claude Code's skill
discovery enabled (for example, a `.claude/skills/` directory), and invoke it by describing
the investigation you want, such as "an agent on AgentCore Runtime is failing, investigate
why." The skill walks through 4 steps: confirming the objective, delegating retrieval and
summarization to a subagent, presenting a conclusion, and having a separate reviewer
subagent check that the conclusion is grounded only in the saved summary and not on anything
the main agent guessed. It pauses at a Checkpoint after each step for your approval, and the
review step can send you back to revise the conclusion.

Behind the scenes, the subagent step calls `tools/logs_insights.py`'s
`run_logs_insights_query()` to run a CloudWatch Logs Insights query and summarize the result,
and, for OTEL spans, `tools/span_filter.py`'s `filter_spans()` to drop noise before
summarizing. You can also call either module directly:

```bash
python tools/logs_insights.py \
  --log-group /aws/bedrock-agentcore/runtimes/<agent-id>-DEFAULT \
  --query 'fields @timestamp, @message | filter @message like /ERROR/' \
  --minutes 60 \
  --limit 50
```

This prints a JSON summary (`record_count`, `representative_records`, `field_value_counts`)
to stdout; it never prints the full set of matching log records.

## Trying the failing agent

`agent-failing/main.py` is a minimal agent built on the `bedrock-agentcore` SDK. It emits a
configurable number of near-identical INFO log lines (`NORMAL_LOG_LINES`, default 200) and
then, depending on `FAILURE_MODE`, either raises inside a simulated tool call
(`tool_exception`, the default), sleeps past a caller's timeout (`timeout`), or rejects a
payload missing `customer_id` (`invalid_input`). Set `FAILURE_MODE=none` to only emit the
normal logs.

```bash
docker buildx build --platform linux/arm64 \
  -t <account-id>.dkr.ecr.<region>.amazonaws.com/multi-agent-design-agent-failing:latest \
  --push agent-failing/

AGENTCORE_CONTAINER_URI=<account-id>.dkr.ecr.<region>.amazonaws.com/multi-agent-design-agent-failing:latest \
  python scripts/deploy.py
```

`scripts/deploy.py` prefixes every resource it creates (the IAM role, the ECR repository, the
AgentCore Runtime) with `RESOURCE_PREFIX` (default `multi-agent-design-`), and prints the
target Region and the account id (with everything but the last 4 digits masked) before making
any AWS call. It creates the ECR repository and the IAM role if they do not already exist, and
writes the created runtime's id and ARN to `results/deploy.json`.

## Cleanup

> [!WARNING]
> `scripts/cleanup.py` deletes real AWS resources: the AgentCore Runtime, the ECR repository,
> and the IAM role that `scripts/deploy.py` created. Two safeguards apply together, and both
> are required.
>
> - Prefix guard: only resources whose name starts with `RESOURCE_PREFIX` are touched. An
>   empty prefix is refused before any AWS call, because `"".startswith("")` is always true
>   and would otherwise match every resource in the account and Region.
> - Confirmation flag: without `--yes`, the script only prints what it would delete and exits.
>   Nothing is deleted unless `--yes` is passed explicitly.

```bash
python scripts/cleanup.py        # list the targets only
python scripts/cleanup.py --yes  # actually delete them
```

## References

- [Context Rot: How Increasing Input Tokens Impacts LLM Performance](https://research.trychroma.com/context-rot)
- [agentcore-investigation SKILL.md](https://github.com/awslabs/mcp/blob/main/src/cloudwatch-mcp-server/skills/agentcore-investigation/SKILL.md)
- [otel-span-schema.md](https://github.com/awslabs/mcp/blob/main/src/cloudwatch-mcp-server/skills/agentcore-investigation/references/otel-span-schema.md)
- [Claude Code Subagents](https://code.claude.com/docs/en/sub-agents)
- [Claude Code Agent Skills](https://code.claude.com/docs/en/skills)
- [AgentCore Observability - Configure observability for your agents](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html)
- [GetQueryResults - Amazon CloudWatch Logs API Reference](https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_GetQueryResults.html)
- [awslabs/agentcore-samples - cloudwatch_client.py](https://github.com/awslabs/agentcore-samples/blob/main/06-workshops/07-AgentCore-evaluations/03-advanced/01-end-to-end-on-demand-with-boto3/utils/cloudwatch_client.py)
