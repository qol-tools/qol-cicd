from __future__ import annotations

import re

import pytest
from hypothesis import given
from hypothesis import settings
from hypothesis import strategies as st

from standards.versioning.next_version import Commit
from standards.versioning.next_version import compute_next_version
from standards.versioning.next_version import detect_bump
from standards.versioning.next_version import increment_semver
from standards.versioning.next_version import next_available_version
from standards.versioning.next_version import parse_semver

MAX_EXAMPLES = 2_000


def _semver(major: int, minor: int, patch: int) -> str:
    return f"{major}.{minor}.{patch}"


def _version_strategy(max_major: int = 20, max_minor: int = 200, max_patch: int = 200) -> st.SearchStrategy[str]:
    return st.tuples(
        st.integers(min_value=0, max_value=max_major),
        st.integers(min_value=0, max_value=max_minor),
        st.integers(min_value=0, max_value=max_patch),
    ).map(lambda parts: _semver(parts[0], parts[1], parts[2]))


scope_text = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", min_size=1, max_size=12)
message_text = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789 ", min_size=1, max_size=40)


@st.composite
def commit_with_kind(draw: st.DrawFn) -> tuple[Commit, str]:
    kind = draw(st.sampled_from(["release", "feat", "fix", "breaking_subject", "breaking_body", "other"]))
    scope = draw(st.one_of(st.just(""), scope_text.map(lambda value: f"({value})")))
    message = draw(message_text)
    if kind == "release":
        version = draw(_version_strategy(max_major=8, max_minor=30, max_patch=30))
        casing = draw(st.sampled_from(["chore(release)", "Chore(Release)", "CHORE(RELEASE)"]))
        return Commit(subject=f"{casing}: v{version}", body=""), kind
    if kind == "feat":
        return Commit(subject=f"feat{scope}: {message}", body=""), kind
    if kind == "fix":
        return Commit(subject=f"fix{scope}: {message}", body=""), kind
    if kind == "breaking_subject":
        prefix = draw(st.sampled_from(["feat", "fix", "refactor", "chore"]))
        return Commit(subject=f"{prefix}{scope}!: {message}", body=""), kind
    if kind == "breaking_body":
        body_tail = draw(message_text)
        return Commit(subject=f"refactor{scope}: {message}", body=f"meta\nBREAKING CHANGE: {body_tail}"), kind
    return Commit(subject=f"docs{scope}: {message}", body=""), kind


@st.composite
def commit_batch(draw: st.DrawFn) -> tuple[list[Commit], int, bool, bool]:
    pairs = draw(st.lists(commit_with_kind(), min_size=0, max_size=60))
    commits = [pair[0] for pair in pairs]
    non_release = [pair for pair in pairs if pair[1] != "release" and pair[0].subject.strip()]
    has_breaking = any(pair[1] in {"breaking_subject", "breaking_body"} for pair in non_release)
    has_feat = any(pair[1] == "feat" for pair in non_release)
    return commits, len(non_release), has_breaking, has_feat


@st.composite
def existing_tag_set(draw: st.DrawFn) -> tuple[set[str], str]:
    base = draw(_version_strategy(max_major=10, max_minor=50, max_patch=50))
    bump = draw(st.sampled_from(["major", "minor", "patch"]))
    seed = increment_semver(base, bump)
    major, minor, patch = parse_semver(seed)
    collision_count = draw(st.integers(min_value=0, max_value=25))
    collisions = {f"v{major}.{minor}.{patch + offset}" for offset in range(collision_count)}
    noise = draw(
        st.sets(
            _version_strategy(max_major=10, max_minor=80, max_patch=80).map(lambda value: f"v{value}"),
            min_size=0,
            max_size=30,
        )
    )
    return collisions | noise, seed


def test_patch_for_fix_only() -> None:
    commits = [Commit(subject="fix: close panic path"), Commit(subject="chore: tweak docs")]
    result = compute_next_version("1.2.3", commits, [])
    assert result.should_release is True
    assert result.bump == "patch"
    assert result.version == "1.2.4"


def test_minor_for_feat() -> None:
    commits = [Commit(subject="feat: add monitor-aware placement"), Commit(subject="fix: typo")]
    result = compute_next_version("1.2.3", commits, [])
    assert result.should_release is True
    assert result.bump == "minor"
    assert result.version == "1.3.0"


def test_major_for_breaking_change_footer() -> None:
    commits = [Commit(subject="refactor: cleanup flow", body="BREAKING CHANGE: config path moved")]
    result = compute_next_version("1.2.3", commits, [])
    assert result.should_release is True
    assert result.bump == "major"
    assert result.version == "2.0.0"


def test_no_release_when_only_release_commits() -> None:
    commits = [Commit(subject="chore(release): v1.2.4"), Commit(subject="chore(release): v1.2.5")]
    result = compute_next_version("1.2.3", commits, [])
    assert result.should_release is False
    assert result.version is None
    assert result.bump is None


def test_invalid_semver_raises() -> None:
    with pytest.raises(ValueError, match=re.escape("Invalid semver: 1.2")):
        parse_semver("1.2")


@settings(max_examples=MAX_EXAMPLES)
@given(batch=commit_batch())
def test_property_bump_precedence(batch: tuple[list[Commit], int, bool, bool]) -> None:
    commits, non_release_count, has_breaking, has_feat = batch
    expected = "patch"
    if has_breaking:
        expected = "major"
    elif has_feat:
        expected = "minor"

    assert detect_bump(commits) == expected
    result = compute_next_version("1.2.3", commits, [])
    assert result.should_release is (non_release_count > 0)
    if non_release_count > 0:
        assert result.bump == expected
        assert result.version is not None


@settings(max_examples=MAX_EXAMPLES)
@given(data=existing_tag_set())
def test_property_next_available_keeps_bump_axis(data: tuple[set[str], str]) -> None:
    tags, seed = data
    seed_major, seed_minor, seed_patch = parse_semver(seed)
    candidate = next_available_version(seed, tags)
    cand_major, cand_minor, cand_patch = parse_semver(candidate)
    assert cand_major == seed_major
    assert cand_minor == seed_minor
    assert cand_patch >= seed_patch
    assert f"v{candidate}" not in tags


@settings(max_examples=MAX_EXAMPLES)
@given(
    base=_version_strategy(max_major=6, max_minor=40, max_patch=40),
    batch=commit_batch(),
    existing=st.sets(
        _version_strategy(max_major=8, max_minor=80, max_patch=80).map(lambda value: f"v{value}"),
        min_size=0,
        max_size=80,
    ),
)
def test_property_compute_matches_manual_pipeline(
    base: str,
    batch: tuple[list[Commit], int, bool, bool],
    existing: set[str],
) -> None:
    commits, non_release_count, _, _ = batch
    result = compute_next_version(base, commits, existing)

    if non_release_count == 0:
        assert result.should_release is False
        assert result.version is None
        assert result.bump is None
        assert result.commit_count == 0
        return

    expected_bump = detect_bump(commits)
    expected_seed = increment_semver(base, expected_bump)
    expected_version = next_available_version(expected_seed, existing)

    assert result.should_release is True
    assert result.bump == expected_bump
    assert result.version == expected_version
    assert result.commit_count == non_release_count
    assert f"v{result.version}" not in existing
