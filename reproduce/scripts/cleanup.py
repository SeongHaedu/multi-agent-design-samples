# reproduce/scripts/cleanup.py
#
# Deletes the resources scripts/deploy.py created: the AgentCore Runtime, the ECR
# repository, and the IAM role, all named with RESOURCE_PREFIX.
#
# Safeguards:
#   1. Prefix guard. Only resources whose name starts with RESOURCE_PREFIX are touched.
#      "".startswith("") is always true, so an empty prefix would match every resource in
#      the account and Region. This is checked, and the script exits before making any AWS
#      call, if RESOURCE_PREFIX is empty.
#   2. Confirmation flag. Without --yes, the script only prints what it would delete and
#      exits. Nothing is deleted unless --yes is passed explicitly.
#   3. The IAM role and the ECR repository are deleted only when they carry the ManagedBy
#      tag that deploy.py applies, so a role or repository that already existed under the
#      same name is left alone.
#
# usage:
#   python scripts/cleanup.py            # print the targets only
#   python scripts/cleanup.py --yes      # actually delete them
import os
import sys

import boto3
from botocore.exceptions import ClientError

RESOURCE_PREFIX = os.environ.get("RESOURCE_PREFIX") or "multi-agent-design-"
REGION = os.environ.get("AWS_REGION") or "us-east-1"
PROFILE = os.environ.get("AWS_PROFILE") or None

MANAGED_TAG_KEY = "ManagedBy"
MANAGED_TAG_VALUE = "multi-agent-design-samples"

USAGE = "usage: python scripts/cleanup.py [--yes]"


def make_session() -> boto3.Session:
    return boto3.Session(profile_name=PROFILE) if PROFILE else boto3.Session()


def masked_account_id(sts_client) -> str:
    account_id = sts_client.get_caller_identity()["Account"]
    return f"{'*' * (len(account_id) - 4)}{account_id[-4:]}"


def is_managed(tags: list) -> bool:
    return any(t.get("Key") == MANAGED_TAG_KEY and t.get("Value") == MANAGED_TAG_VALUE for t in tags)


def find_runtimes(control_client) -> list:
    paginator = control_client.get_paginator("list_agent_runtimes")
    found = []
    for page in paginator.paginate():
        for runtime in page.get("agentRuntimes", []):
            if runtime["agentRuntimeName"].startswith(RESOURCE_PREFIX):
                found.append(runtime)
    return found


def find_role(iam_client):
    role_name = f"{RESOURCE_PREFIX}agent-failing-role"
    try:
        role = iam_client.get_role(RoleName=role_name)["Role"]
    except ClientError as error:
        if error.response["Error"]["Code"] == "NoSuchEntity":
            return None
        raise
    tags = iam_client.list_role_tags(RoleName=role_name)["Tags"]
    return {"name": role_name, "arn": role["Arn"], "managed": is_managed(tags)}


def find_repository(ecr_client):
    repo_name = f"{RESOURCE_PREFIX}agent-failing"
    try:
        repo = ecr_client.describe_repositories(repositoryNames=[repo_name])["repositories"][0]
    except ClientError as error:
        if error.response["Error"]["Code"] == "RepositoryNotFoundException":
            return None
        raise
    tags = ecr_client.list_tags_for_resource(resourceArn=repo["repositoryArn"])["tags"]
    return {"name": repo_name, "managed": is_managed(tags)}


def main() -> None:
    for arg in sys.argv[1:]:
        if arg != "--yes":
            raise SystemExit(f"unknown argument: {arg}\n{USAGE}")
    apply_delete = "--yes" in sys.argv[1:]

    # An empty prefix would make every resource name match ("".startswith("") is always
    # true). Fail before any AWS call rather than deleting everything in the account.
    if RESOURCE_PREFIX == "":
        raise SystemExit(
            "RESOURCE_PREFIX is empty. Refusing to run: an empty prefix would match every "
            "resource in the account and Region."
        )

    session = make_session()
    sts = session.client("sts", region_name=REGION)
    print(f"region:  {REGION}")
    print(f"account: {masked_account_id(sts)}")
    print(f"prefix:  {RESOURCE_PREFIX!r}")

    control = session.client("bedrock-agentcore-control", region_name=REGION)
    iam = session.client("iam", region_name=REGION)
    ecr = session.client("ecr", region_name=REGION)

    runtimes = find_runtimes(control)
    role = find_role(iam)
    repository = find_repository(ecr)

    print("\nRuntimes matching the prefix:")
    for runtime in runtimes:
        print(f"  - {runtime['agentRuntimeName']} ({runtime['agentRuntimeId']}) status={runtime['status']}")
    if not runtimes:
        print("  (none)")

    print("\nOther resources:")
    others = [r for r in (role, repository) if r is not None]
    for resource in others:
        note = "" if resource["managed"] else f"  [skipped: no {MANAGED_TAG_KEY}={MANAGED_TAG_VALUE} tag]"
        print(f"  - {resource['name']}{note}")
    if not others:
        print("  (none)")

    if not apply_delete:
        print("\nRan without --yes, so nothing was deleted. Re-run with --yes to delete.")
        return

    for runtime in runtimes:
        name = runtime["agentRuntimeName"]
        if not name.startswith(RESOURCE_PREFIX):
            print(f"[skip] {name} does not match the prefix")
            continue
        print(f"[runtime] deleting {name}")
        try:
            control.delete_agent_runtime(agentRuntimeId=runtime["agentRuntimeId"])
        except ClientError as error:
            print(f"[runtime] delete failed: {error.response['Error']['Code']}")

    if repository is not None and repository["managed"]:
        print(f"[ecr] deleting {repository['name']}")
        try:
            ecr.delete_repository(repositoryName=repository["name"], force=True)
        except ClientError as error:
            print(f"[ecr] delete failed: {error.response['Error']['Code']}")

    if role is not None and role["managed"]:
        print(f"[role] deleting {role['name']}")
        try:
            iam.delete_role_policy(RoleName=role["name"], PolicyName=f"{RESOURCE_PREFIX}agent-failing-policy")
            iam.delete_role(RoleName=role["name"])
        except ClientError as error:
            print(f"[role] delete failed: {error.response['Error']['Code']}")


if __name__ == "__main__":
    main()
