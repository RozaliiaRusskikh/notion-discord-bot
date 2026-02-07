import httpx
from datetime import datetime, timedelta, timezone
from typing import List, Dict
from app.config import settings
from app.logger import setup_logger

logger = setup_logger(__name__)


class GitHubService:
    """Service to fetch commits from GitHub repository(ies)"""

    def __init__(self):
        self.base_url = "https://api.github.com"
        self.enabled = settings.github_token is not None

        # Parse repositories from comma-separated string
        if settings.github_repos:
            repo_strings = [r.strip() for r in settings.github_repos.split(",")]
            self.repositories = []
            for repo_str in repo_strings:
                if "/" in repo_str:
                    owner, repo = repo_str.split("/", 1)
                    self.repositories.append(
                        {"owner": owner.strip(), "repo": repo.strip()}
                    )
                else:
                    logger.warning(
                        f"Invalid repository format: {repo_str}. Expected 'owner/repo'"
                    )
        else:
            # No repositories configured
            self.repositories = []
            logger.warning(
                "⚠️ No GitHub repositories configured. Set GITHUB_REPOS in .env file (e.g., 'owner1/repo1,owner2/repo2,owner3/repo3')"
            )

        if self.enabled:
            self.headers = {
                "Authorization": f"token {settings.github_token}",
                "Accept": "application/vnd.github.v3+json",
            }
            repo_list = ", ".join(
                [f"{r['owner']}/{r['repo']}" for r in self.repositories]
            )
            logger.info(f"✅ GitHub service ready for: {repo_list} (filtered by user: {settings.github_user})")
        else:
            self.headers = {
                "Accept": "application/vnd.github.v3+json",
            }
            logger.warning("⚠️ GitHub service disabled: github_token not configured")

    def _fetch_commits_from_repo(
        self, owner: str, repo: str, since_iso: str, max_commits: int = 100
    ) -> List[Dict]:
        """Fetch commits from a single repository"""
        url = f"{self.base_url}/repos/{owner}/{repo}/commits"
        params = {
            "since": since_iso,
            "per_page": min(max_commits, 100),
            "author": settings.github_user,  # Always filter by GitHub username (required)
        }
        
        logger.debug(f"Filtering commits by GitHub user: {settings.github_user}")

        try:
            logger.debug(f"Fetching commits from {owner}/{repo} since {since_iso}")
            with httpx.Client(timeout=30.0) as client:
                response = client.get(url, headers=self.headers, params=params)
                response.raise_for_status()
                commits = response.json()

                # Format commits and add repo info
                formatted_commits = []
                for commit in commits:
                    commit_data = commit.get("commit", {})
                    author = commit_data.get("author", {})
                    author_name = author.get("name", "Unknown")
                    author_email = author.get("email", "")
                    
                    # Additional client-side filtering by GitHub username (double-check)
                    # The API author parameter filters by GitHub username, but we verify here
                    commit_author = commit.get("author")
                    if commit_author:
                        author_login = commit_author.get("login", "").lower()
                        github_user_lower = settings.github_user.lower()
                        if author_login and github_user_lower != author_login:
                            continue  # Skip if GitHub username doesn't match

                    formatted_commits.append(
                        {
                            "sha": commit.get("sha", "")[:7],
                            "message": commit_data.get("message", "").strip(),
                            "author": author_name,
                            "date": author.get("date", ""),
                            "url": commit.get("html_url", ""),
                            "repo": f"{owner}/{repo}",  # Add repo identifier
                        }
                    )

                logger.info(
                    f"Fetched {len(formatted_commits)} commits from {owner}/{repo} (since {since_iso})"
                )
                if formatted_commits:
                    logger.debug(
                        f"Sample commit dates: {[c['date'] for c in formatted_commits[:3]]}"
                    )
                return formatted_commits

        except httpx.HTTPStatusError as e:
            logger.error(
                f"GitHub API error for {owner}/{repo}: {e.response.status_code} - {e.response.text}"
            )
            return []
        except Exception as e:
            logger.error(f"Failed to fetch commits from {owner}/{repo}: {e}")
            return []

    def _fetch_all_commits(
        self, since_iso: str, max_commits: int | None = None
    ) -> List[Dict]:
        """Common logic to fetch commits from all repositories"""
        if not self.enabled:
            logger.warning("GitHub service is disabled: github_token not configured")
            return []

        if not self.repositories:
            logger.warning("No repositories configured")
            return []

        logger.info(
            f"Fetching commits from {len(self.repositories)} repository(ies) since {since_iso}"
        )

        all_commits = []
        for repo_info in self.repositories:
            owner = repo_info["owner"]
            repo = repo_info["repo"]
            commits = self._fetch_commits_from_repo(
                owner, repo, since_iso, max_commits=100
            )
            logger.info(f"Found {len(commits)} commits in {owner}/{repo}")
            all_commits.extend(commits)

        # Sort by date (newest first)
        all_commits.sort(key=lambda x: x.get("date", ""), reverse=True)

        # Limit if specified
        if max_commits:
            all_commits = all_commits[:max_commits]

        # Log summary
        if all_commits:
            logger.info(f"Total commits found: {len(all_commits)}")
            logger.info("Sample commits:")
            for i, commit in enumerate(all_commits[:3], 1):
                logger.info(
                    f"  {i}. [{commit['repo']}] {commit['sha']} - {commit['message'][:50]}... by {commit['author']}"
                )
        else:
            logger.warning(f"No commits found in any repository since {since_iso}")

        return all_commits

    def get_recent_commits(
        self, since_days: int = 3, max_commits: int = 50
    ) -> List[Dict]:
        """
        Fetch recent commits from all configured repositories

        Args:
            since_days: Number of days to look back for commits
            max_commits: Maximum number of commits to return (total across all repos)

        Returns:
            List of commit dictionaries with sha, message, author, date, url, repo
        """
        since = datetime.now(timezone.utc) - timedelta(days=since_days)
        since_iso = since.isoformat()
        logger.info(f"Fetching commits from last {since_days} days")
        return self._fetch_all_commits(since_iso, max_commits)

    def get_commits_since_last_standup(self, last_standup_date: datetime) -> List[Dict]:
        """
        Get commits since a specific date from all configured repositories

        Args:
            last_standup_date: Datetime to fetch commits after (can be timezone-aware or naive)

        Returns:
            List of commit dictionaries with repo information
        """
        # Convert to UTC if timezone-aware, otherwise assume UTC
        if last_standup_date.tzinfo is None:
            # If naive, assume it's UTC
            last_standup_date_utc = last_standup_date.replace(tzinfo=timezone.utc)
        else:
            # Convert to UTC
            last_standup_date_utc = last_standup_date.astimezone(timezone.utc)

        since_iso = last_standup_date_utc.isoformat()
        logger.info(
            f"Fetching commits since {since_iso} (UTC) - original date: {last_standup_date}"
        )
        commits = self._fetch_all_commits(since_iso)

        # Don't filter on client side - GitHub API already filters by 'since' parameter
        # The API returns commits where commit.author.date >= since
        # So we can trust the API response
        logger.info(
            f"Returning {len(commits)} commits from GitHub API (no additional filtering)"
        )
        return commits

    def health_check(self) -> bool:
        """Check if GitHub API is accessible"""
        if not self.enabled:
            return False
        try:
            # Check first repository as health check
            if self.repositories:
                repo = self.repositories[0]
                url = f"{self.base_url}/repos/{repo['owner']}/{repo['repo']}"
                with httpx.Client(timeout=10.0) as client:
                    response = client.get(url, headers=self.headers)
                    return response.status_code == 200
        except Exception:
            return False
        return False


github_service = GitHubService()
