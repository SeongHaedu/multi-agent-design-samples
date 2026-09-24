# reproduce/scripts/deploy.py
#
# Deploys agent-failing/ to Amazon Bedrock AgentCore Runtime as a container agent.
#
# Every resource this script creates (the IAM role, the ECR repository, the AgentCore
# Runtime) shares one name prefix, controlled by the RESOURCE_PREFIX environment variable
# (default "multi-agent-design-"). scripts/cleanup.py deletes only resources matching the
# same prefix.
#
# This script makes real AWS calls. Before doing anything, it prints the target Region and
# the account id with everything but the last 4 digits masked.
#
# Prerequisites:
#   - AWS credentials configured (env vars, a profile, or an instance/role credential source).
#   - If AGENTCORE_CONTAINER_URI is not set, this script creates the ECR repository but does
#     not build or push the image. Build and push it yourself before invoking the runtime:
#       docker buildx build --platform linux/arm64 -t <repository-uri>:<tag> --push agent-failing/
#
# usage:
#   python scripts/deploy.py
import json
import os
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

RESOURCE_PREFIX = os.environ.get("RESOURCE_PREFIX") or "multi-agent-design-"
REGION = os.environ.get("AWS_REGION") or "us-east-1"
PROFILE = os.environ.get("AWS_PROFILE") or None

ROLE_NAME = f"{RESOURCE_PREFIX}agent-failing-role"
ROLE_POLICY_NAME = f"{RESOURCE_PREFIX}agent-failing-policy"
ECR_REPOSITORY = f"{RESOURCE_PREFIX}agent-failing"
RUNTIME_NAME = f"{RESOURCE_PREFIX}agent-failing"

MANAGED_TAG_KEY = "ManagedBy"
MANAGED_TAG_VALUE = "multi-agent-design-samples"

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

TRUST_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }
    ],
}

EXECUTION_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents",
                "logs:PutResourcePolicy",
            ],
            "Resource": "*",
        },
        {
            "Effect": "Allow",
            "Action": [
                "ecr:GetDownloadUrlForLayer",
                "ecr:BatchGetImage",
                "ecr:BatchCheckLayerAvailability",
            ],
            "Resource": "*",
        },
    ],
}


def make_session() -> boto3.Session:
    return boto3.Session(profile_name=PROFILE) if PROFILE else boto3.Session()


def masked_account_id(sts_client) -> str:
    account_id = sts_client.get_caller_identity()["Account"]
    return f"{'*' * (len(account_id) - 4)}{account_id[-4:]}"


def print_target(sts_client) -> None:
    print(f"region:  {REGION}")
    print(f"account: {masked_account_id(sts_client)}")
    print(f"prefix:  {RESOURCE_PREFIX}")


def ensure_role(iam_client) -> str:
    try:
        role = iam_client.get_role(RoleName=ROLE_NAME)["Role"]
        print(f"[role] reusing existing role {ROLE_NAME}")
        return role["Arn"]
    except ClientError as error:
        if error.response["Error"]["Code"] != "NoSuchEntity":
            raise

    print(f"[role] creating {ROLE_NAME}")
    role = iam_client.create_role(
        RoleName=ROLE_NAME,
        AssumeRolePolicyDocument=json.dumps(TRUST_POLICY),
        Tags=[{"Key": MANAGED_TAG_KEY, "Value": MANAGED_TAG_VALUE}],
    )["Role"]
    iam_client.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName=ROLE_POLICY_NAME,
        PolicyDocument=json.dumps(EXECUTION_POLICY),
    )
    # IAM role propagation can take several seconds. Without this wait, the immediately
    # following create_agent_runtime call can fail to assume the role it just created.
    time.sleep(10)
    return role["Arn"]


def ensure_ecr_repository(ecr_client) -> str:
    try:
        repo = ecr_client.describe_repositories(repositoryNames=[ECR_REPOSITORY])["repositories"][0]
        print(f"[ecr] reusing existing repository {ECR_REPOSITORY}")
        return repo["repositoryUri"]
    except ClientError as error:
        if error.response["Error"]["Code"] != "RepositoryNotFoundException":
            raise

    print(f"[ecr] creating {ECR_REPOSITORY}")
    repo = ecr_client.create_repository(
        repositoryName=ECR_REPOSITORY,
        tags=[{"Key": MANAGED_TAG_KEY, "Value": MANAGED_TAG_VALUE}],
    )["repository"]
    return repo["repositoryUri"]


def create_runtime(control_client, role_arn: str, container_uri: str) -> dict:
    print(f"[runtime] creating {RUNTIME_NAME} image={container_uri}")
    return control_client.create_agent_runtime(
        agentRuntimeName=RUNTIME_NAME,
        agentRuntimeArtifact={"containerConfiguration": {"containerUri": container_uri}},
        roleArn=role_arn,
        networkConfiguration={"networkMode": "PUBLIC"},
        environmentVariables={
            "PYTHONUNBUFFERED": "1",
            "FAILURE_MODE": os.environ.get("FAILURE_MODE") or "tool_exception",
        },
    )


def main() -> None:
    session = make_session()
    sts = session.client("sts", region_name=REGION)
    print_target(sts)

    ecr = session.client("ecr", region_name=REGION)
    container_uri = os.environ.get("AGENTCORE_CONTAINER_URI")
    if not container_uri:
        repository_uri = ensure_ecr_repository(ecr)
        image_tag = os.environ.get("AGENTCORE_IMAGE_TAG") or "latest"
        container_uri = f"{repository_uri}:{image_tag}"
        print(
            "[hint] AGENTCORE_CONTAINER_URI is not set. Build and push the image before "
            f"invoking the runtime:\n"
            f"  docker buildx build --platform linux/arm64 -t {container_uri} --push agent-failing/"
        )

    iam = session.client("iam", region_name=REGION)
    role_arn = os.environ.get("AGENTCORE_ROLE_ARN") or ensure_role(iam)

    control = session.client("bedrock-agentcore-control", region_name=REGION)
    try:
        response = create_runtime(control, role_arn, container_uri)
    except ClientError as error:
        print(
            f"[runtime] create_agent_runtime failed: "
            f"{error.response['Error']['Code']}: {error.response['Error']['Message']}"
        )
        sys.exit(1)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    result_path = RESULTS_DIR / "deploy.json"
    result_path.write_text(
        json.dumps(
            {
                "runtime_name": RUNTIME_NAME,
                "agent_runtime_id": response.get("agentRuntimeId"),
                "agent_runtime_arn": response.get("agentRuntimeArn"),
                "role_arn": role_arn,
                "container_uri": container_uri,
                "region": REGION,
            },
            indent=2,
        )
    )
    print(f"[runtime] created. id={response.get('agentRuntimeId')} saved to {result_path}")


if __name__ == "__main__":
    main()
