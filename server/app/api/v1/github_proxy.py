from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import httpx
from app.api.deps import get_current_user
from app.models import User
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/github", tags=["github"])

GITHUB_API = "https://api.github.com"
TIMEOUT = 15.0


class GitHubRepoItem(BaseModel):
    full_name: str
    name: str
    private: bool
    default_branch: str
    description: str | None = None
    language: str | None = None
    updated_at: datetime
    html_url: str
    stargazers_count: int = 0


class GitHubBranch(BaseModel):
    name: str
    sha: str
    is_default: bool = False


class GitHubCommitItem(BaseModel):
    sha: str
    short_sha: str
    message: str
    author_name: str
    author_avatar: str | None = None
    authored_at: datetime


class GitHubMultiBranchCommit(BaseModel):
    sha: str
    short_sha: str
    message: str
    author_name: str
    author_avatar: str | None = None
    authored_at: datetime
    parents: list[str]
    branches: list[str]


def _gh_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _require_token(user: User) -> str:
    if not user.github_access_token:
        raise HTTPException(
            status_code=403,
            detail="GitHub account not linked. Please log in with GitHub.",
        )
    return user.github_access_token


@router.get("/repos", response_model=list[GitHubRepoItem])
async def list_my_repos(
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=100),
    q: str = Query("", description="Filter repos by name substring"),
    current_user: User = Depends(get_current_user),
):
    token = _require_token(current_user)

    url = f"{GITHUB_API}/user/repos?sort=updated&direction=desc&per_page={per_page}&page={page}&type=owner"

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        res = await client.get(url, headers=_gh_headers(token))

    if res.status_code == 401:
        raise HTTPException(
            status_code=401, detail="GitHub token expired. Please re-authenticate."
        )
    if res.status_code != 200:
        logger.warning(
            "GitHub /user/repos returned %d: %s", res.status_code, res.text[:200]
        )
        raise HTTPException(
            status_code=502, detail="Failed to fetch repositories from GitHub"
        )

    raw_repos = res.json()

    results = []
    for r in raw_repos:
        name_lower = (r.get("name") or "").lower()
        if q and q.lower() not in name_lower:
            continue
        results.append(
            GitHubRepoItem(
                full_name=r["full_name"],
                name=r["name"],
                private=r.get("private", False),
                default_branch=r.get("default_branch", "main"),
                description=r.get("description"),
                language=r.get("language"),
                updated_at=r["updated_at"],
                html_url=r["html_url"],
                stargazers_count=r.get("stargazers_count", 0),
            )
        )

    return results


@router.get("/repos/{owner}/{repo}/branches", response_model=list[GitHubBranch])
async def list_repo_branches(
    owner: str,
    repo: str,
    current_user: User = Depends(get_current_user),
):
    token = _require_token(current_user)

    repo_url = f"{GITHUB_API}/repos/{owner}/{repo}"
    branches_url = f"{GITHUB_API}/repos/{owner}/{repo}/branches?per_page=100"

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        repo_res = await client.get(repo_url, headers=_gh_headers(token))
        if repo_res.status_code == 404:
            raise HTTPException(
                status_code=404, detail="Repository not found on GitHub"
            )
        if repo_res.status_code != 200:
            raise HTTPException(
                status_code=502, detail="Failed to fetch repository info"
            )

        default_branch = repo_res.json().get("default_branch", "main")

        branches_res = await client.get(branches_url, headers=_gh_headers(token))
        if branches_res.status_code != 200:
            raise HTTPException(status_code=502, detail="Failed to fetch branches")

    raw_branches = branches_res.json()

    return [
        GitHubBranch(
            name=b["name"],
            sha=b["commit"]["sha"],
            is_default=(b["name"] == default_branch),
        )
        for b in raw_branches
    ]


@router.get("/repos/{owner}/{repo}/commits", response_model=list[GitHubCommitItem])
async def list_repo_commits(
    owner: str,
    repo: str,
    sha: str = Query("", description="Branch name or commit SHA to list commits from"),
    page: int = Query(1, ge=1),
    per_page: int = Query(40, ge=1, le=100),
    current_user: User = Depends(get_current_user),
):
    token = _require_token(current_user)

    url = f"{GITHUB_API}/repos/{owner}/{repo}/commits?per_page={per_page}&page={page}"
    if sha:
        url += f"&sha={sha}"

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        res = await client.get(url, headers=_gh_headers(token))

    if res.status_code == 404:
        raise HTTPException(status_code=404, detail="Repository or branch not found")
    if res.status_code != 200:
        logger.warning(
            "GitHub commits returned %d: %s", res.status_code, res.text[:200]
        )
        raise HTTPException(
            status_code=502, detail="Failed to fetch commits from GitHub"
        )

    raw = res.json()

    return [
        GitHubCommitItem(
            sha=c["sha"],
            short_sha=c["sha"][:7],
            message=(c.get("commit", {}).get("message") or "").split("\n")[0],
            author_name=(
                (c.get("commit", {}).get("author") or {}).get("name")
                or (c.get("author") or {}).get("login")
                or "Unknown"
            ),
            author_avatar=(c.get("author") or {}).get("avatar_url"),
            authored_at=(c.get("commit", {}).get("author") or {}).get(
                "date", "2000-01-01T00:00:00Z"
            ),
        )
        for c in raw
    ]


@router.get(
    "/repos/{owner}/{repo}/commits-multibranch",
    response_model=list[GitHubMultiBranchCommit],
)
async def list_repo_commits_multibranch(
    owner: str,
    repo: str,
    current_user: User = Depends(get_current_user),
):
    token = _require_token(current_user)

    repo_url = f"{GITHUB_API}/repos/{owner}/{repo}"
    branches_url = f"{GITHUB_API}/repos/{owner}/{repo}/branches?per_page=30"

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        repo_res = await client.get(repo_url, headers=_gh_headers(token))
        if repo_res.status_code == 404:
            raise HTTPException(
                status_code=404, detail="Repository not found on GitHub"
            )
        if repo_res.status_code != 200:
            raise HTTPException(
                status_code=502, detail="Failed to fetch repository info"
            )

        default_branch = repo_res.json().get("default_branch", "main")

        branches_res = await client.get(branches_url, headers=_gh_headers(token))
        if branches_res.status_code != 200:
            raise HTTPException(status_code=502, detail="Failed to fetch branches")

    raw_branches = branches_res.json()
    branch_names = [default_branch]
    for b in raw_branches:
        name = b["name"]
        if name != default_branch:
            branch_names.append(name)

    target_branches = branch_names[:5]

    async def fetch_branch_commits(branch_name: str):
        url = f"{GITHUB_API}/repos/{owner}/{repo}/commits?sha={branch_name}&per_page=30"
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            res = await client.get(url, headers=_gh_headers(token))
            if res.status_code == 200:
                return branch_name, res.json()
            return branch_name, []

    tasks = [fetch_branch_commits(name) for name in target_branches]
    results = await asyncio.gather(*tasks)

    commit_dict = {}
    for branch_name, branch_commits in results:
        for c in branch_commits:
            sha = c["sha"]
            if sha not in commit_dict:
                commit_dict[sha] = {
                    "sha": sha,
                    "short_sha": sha[:7],
                    "message": (c.get("commit", {}).get("message") or "").split("\n")[
                        0
                    ],
                    "author_name": (
                        (c.get("commit", {}).get("author") or {}).get("name")
                        or (c.get("author") or {}).get("login")
                        or "Unknown"
                    ),
                    "author_avatar": (c.get("author") or {}).get("avatar_url"),
                    "authored_at": c.get("commit", {})
                    .get("author", {})
                    .get("date", "2000-01-01T00:00:00Z"),
                    "parents": [p["sha"] for p in c.get("parents", [])],
                    "branches": [branch_name],
                }
            else:
                if branch_name not in commit_dict[sha]["branches"]:
                    commit_dict[sha]["branches"].append(branch_name)

    sorted_commits = sorted(
        commit_dict.values(),
        key=lambda x: x["authored_at"],
        reverse=True,
    )

    return [GitHubMultiBranchCommit(**c) for c in sorted_commits[:100]]
