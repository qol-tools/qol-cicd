#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from typing import Sequence

SEMVER_RE = re.compile(r"^([0-9]+)\.([0-9]+)\.([0-9]+)$")
RELEASE_SUBJECT_RE = re.compile(
    r"^chore\(release\):\s*v[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.-]+)?$",
    re.IGNORECASE,
)
BREAKING_SUBJECT_RE = re.compile(r"^[a-z0-9_-]+(\([^)]+\))?!:", re.IGNORECASE)
BREAKING_BODY_RE = re.compile(r"(^|\n)BREAKING[ -]CHANGE:", re.IGNORECASE)
FEATURE_SUBJECT_RE = re.compile(r"^feat(\([^)]+\))?:", re.IGNORECASE)
RELEASABLE_SUBJECT_RE = re.compile(r"^(feat|fix|perf)(\([^)]+\))?!?:", re.IGNORECASE)


@dataclass(frozen=True)
class Commit:
    subject: str
    body: str = ""


@dataclass(frozen=True)
class VersionResult:
    should_release: bool
    version: str | None
    bump: str | None
    commit_count: int


def parse_semver(version: str) -> tuple[int, int, int]:
    match = SEMVER_RE.match(version.strip())
    if not match:
        raise ValueError(f"Invalid semver: {version}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def is_release_commit(subject: str) -> bool:
    return RELEASE_SUBJECT_RE.match(subject.strip()) is not None


def normalize_commits(raw_commits: Iterable[Commit | dict[str, str]]) -> list[Commit]:
    commits: list[Commit] = []
    for raw in raw_commits:
        if isinstance(raw, Commit):
            commits.append(raw)
            continue
        if not isinstance(raw, dict):
            raise TypeError(f"Unsupported commit shape: {type(raw)}")
        subject = str(raw.get("subject", ""))
        body = str(raw.get("body", ""))
        commits.append(Commit(subject=subject, body=body))
    return commits


def detect_bump(commits: Sequence[Commit]) -> str:
    bump = "patch"
    for commit in commits:
        subject = commit.subject.strip()
        if not subject or is_release_commit(subject):
            continue
        body = commit.body or ""
        if BREAKING_SUBJECT_RE.match(subject) or BREAKING_BODY_RE.search(body):
            return "major"
        if bump == "patch" and FEATURE_SUBJECT_RE.match(subject):
            bump = "minor"
    return bump


def increment_semver(version: str, bump: str) -> str:
    major, minor, patch = parse_semver(version)
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    if bump == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"Invalid bump: {bump}")


def next_available_version(version: str, existing_tags: Iterable[str], tag_prefix: str = "v") -> str:
    major, minor, patch = parse_semver(version)
    tag_set = {tag.strip() for tag in existing_tags if str(tag).strip()}
    candidate = f"{major}.{minor}.{patch}"
    while f"{tag_prefix}{candidate}" in tag_set:
        patch += 1
        candidate = f"{major}.{minor}.{patch}"
    return candidate


def is_releasable_commit(commit: Commit) -> bool:
    """A commit triggers a release if it is feat/fix/perf or any breaking change."""
    subject = commit.subject.strip()
    if not subject or is_release_commit(subject):
        return False
    if BREAKING_SUBJECT_RE.match(subject) or BREAKING_BODY_RE.search(commit.body or ""):
        return True
    return RELEASABLE_SUBJECT_RE.match(subject) is not None


def compute_next_version(
    base_version: str,
    raw_commits: Iterable[Commit | dict[str, str]],
    existing_tags: Iterable[str],
    tag_prefix: str = "v",
) -> VersionResult:
    parse_semver(base_version)
    commits = normalize_commits(raw_commits)
    release_candidates = [commit for commit in commits if is_releasable_commit(commit)]
    if not release_candidates:
        return VersionResult(should_release=False, version=None, bump=None, commit_count=0)
    bump = detect_bump(release_candidates)
    initial = increment_semver(base_version, bump)
    version = next_available_version(initial, existing_tags, tag_prefix=tag_prefix)
    return VersionResult(should_release=True, version=version, bump=bump, commit_count=len(release_candidates))


def _run_git(repo: Path, args: Sequence[str]) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise RuntimeError(message)
    return result.stdout


def load_git_commits(repo: Path, from_ref: str | None, to_ref: str = "HEAD") -> list[Commit]:
    rev_range = f"{from_ref}..{to_ref}" if from_ref else to_ref
    output = _run_git(repo, ["log", "--format=%s%x1f%b%x1e", rev_range])
    commits: list[Commit] = []
    for raw_commit in output.split("\x1e"):
        item = raw_commit.strip("\n")
        if not item:
            continue
        subject, separator, body = item.partition("\x1f")
        if not separator:
            body = ""
        commits.append(Commit(subject=subject.strip(), body=body.rstrip("\n")))
    return commits


def load_git_tags(repo: Path, pattern: str = "v*") -> list[str]:
    output = _run_git(repo, ["tag", "--list", pattern])
    return [line.strip() for line in output.splitlines() if line.strip()]


def version_from_tag_ref(ref: str, tag_prefix: str = "v") -> str | None:
    value = ref.strip()
    if value.startswith("refs/tags/"):
        value = value[len("refs/tags/") :]
    escaped = re.escape(tag_prefix)
    match = re.match(rf"^{escaped}([0-9]+\.[0-9]+\.[0-9]+)$", value)
    if not match:
        return None
    return match.group(1)


def emit_result(result: VersionResult, output_format: str, github_output_path: str | None) -> None:
    if output_format == "json":
        sys.stdout.write(json.dumps(asdict(result)))
        sys.stdout.write("\n")
        return

    should_release = "true" if result.should_release else "false"
    lines = [f"should_release={should_release}", f"commit_count={result.commit_count}"]
    if result.version is not None:
        lines.append(f"version={result.version}")
    if result.bump is not None:
        lines.append(f"bump={result.bump}")
    payload = "\n".join(lines) + "\n"
    if github_output_path:
        with open(github_output_path, "a", encoding="utf-8") as handle:
            handle.write(payload)
    else:
        sys.stdout.write(payload)


def run_eval_command(args: argparse.Namespace) -> int:
    with open(args.commits_json, "r", encoding="utf-8") as handle:
        commits_payload = json.load(handle)
    if not isinstance(commits_payload, list):
        raise ValueError("--commits-json must contain a JSON array")

    tags_payload: list[str] = []
    if args.existing_tags_json:
        with open(args.existing_tags_json, "r", encoding="utf-8") as handle:
            tags_data = json.load(handle)
        if not isinstance(tags_data, list):
            raise ValueError("--existing-tags-json must contain a JSON array")
        tags_payload = [str(item) for item in tags_data]

    result = compute_next_version(
        base_version=args.base_version,
        raw_commits=commits_payload,
        existing_tags=tags_payload,
        tag_prefix=args.tag_prefix,
    )
    emit_result(result, output_format=args.output_format, github_output_path=args.github_output)
    return 0


def run_git_command(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    commits = load_git_commits(repo=repo, from_ref=args.from_ref, to_ref=args.to_ref)
    tags = load_git_tags(repo=repo, pattern=args.tag_pattern)

    base_version = args.base_version
    if not base_version:
        if not args.from_ref:
            raise ValueError("--base-version is required when --from-ref is not set")
        parsed = version_from_tag_ref(args.from_ref, tag_prefix=args.tag_prefix)
        if parsed is None:
            raise ValueError("--from-ref must be a plain semver tag when --base-version is omitted")
        base_version = parsed

    result = compute_next_version(
        base_version=base_version,
        raw_commits=commits,
        existing_tags=tags,
        tag_prefix=args.tag_prefix,
    )
    emit_result(result, output_format=args.output_format, github_output_path=args.github_output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="next_version.py")
    subparsers = parser.add_subparsers(dest="command", required=True)

    eval_parser = subparsers.add_parser("eval")
    eval_parser.add_argument("--base-version", required=True)
    eval_parser.add_argument("--commits-json", required=True)
    eval_parser.add_argument("--existing-tags-json")
    eval_parser.add_argument("--tag-prefix", default="v")
    eval_parser.add_argument("--output-format", choices=("json", "github"), default="json")
    eval_parser.add_argument("--github-output")
    eval_parser.set_defaults(handler=run_eval_command)

    git_parser = subparsers.add_parser("git")
    git_parser.add_argument("--repo", default=".")
    git_parser.add_argument("--from-ref")
    git_parser.add_argument("--to-ref", default="HEAD")
    git_parser.add_argument("--base-version")
    git_parser.add_argument("--tag-pattern", default="v*")
    git_parser.add_argument("--tag-prefix", default="v")
    git_parser.add_argument("--output-format", choices=("json", "github"), default="json")
    git_parser.add_argument("--github-output")
    git_parser.set_defaults(handler=run_git_command)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler")
    return handler(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
