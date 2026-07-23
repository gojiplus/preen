"""Interactive prompt system for release workflow."""

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from .checks.base import CheckResult, Impact, Issue


class InteractiveReleaseWorkflow:
    """Implements the devtools::release() style interactive workflow."""

    def __init__(self, console: Console | None = None):
        """Initialize the interactive workflow."""
        self.console = console or Console()
        self.overrides: dict[str, bool] = {}  # Track user overrides

    def run_release_checks(
        self, check_results: dict[str, CheckResult], target: str = "PyPI"
    ) -> bool:
        """Run interactive release workflow similar to devtools::release().

        Returns True if user confirms release should proceed.
        """
        self.console.print(
            f"\n🚀 [bold cyan]Preparing release to {target}[/bold cyan]\n"
        )

        # Categorize all issues by impact
        critical_issues = []
        important_issues = []
        info_issues = []

        for result in check_results.values():
            critical_issues.extend(result.get_issues_by_impact(Impact.CRITICAL))
            important_issues.extend(result.get_issues_by_impact(Impact.IMPORTANT))
            info_issues.extend(result.get_issues_by_impact(Impact.INFORMATIONAL))

        # Handle critical issues (blocking)
        if critical_issues:
            self._handle_critical_issues(critical_issues)
            return False  # Cannot proceed with critical issues

        # Handle important issues (with override)
        if important_issues and not self._handle_important_issues(important_issues):
            return False  # User chose not to proceed

        # Handle informational issues (optional)
        if info_issues:
            self._handle_informational_issues(info_issues)

        # Final confirmation
        return self._final_release_confirmation(target)

    def _handle_critical_issues(self, issues: list[Issue]) -> None:
        """Handle critical issues that block release."""
        self.console.print("🚫 [bold red]Critical Issues Found[/bold red]")
        self.console.print("These issues must be fixed before release:\n")

        for issue in issues:
            panel = Panel(
                f"[red]{issue.description}[/red]\n\n[dim]{issue.explanation}[/dim]",
                title=f"{issue.check} - Critical",
                border_style="red",
            )
            self.console.print(panel)

        self.console.print("\n❌ [bold red]Cannot proceed with release[/bold red]")
        self.console.print("Please fix the critical issues above and try again.\n")

    def _handle_important_issues(self, issues: list[Issue]) -> bool:
        """Handle important issues with override capability."""
        self.console.print("⚠️  [bold yellow]Important Issues Found[/bold yellow]")
        self.console.print("These should be addressed but can be overridden:\n")

        for issue in issues:
            # Show the issue with explanation
            panel = Panel(
                f"[yellow]{issue.description}[/yellow]\n\n"
                f"[dim]{issue.explanation}[/dim]",
                title=f"{issue.check} - Important",
                border_style="yellow",
            )
            self.console.print(panel)

            # Offer fix if available
            if issue.proposed_fix:
                fix_choice = Prompt.ask(
                    "Fix this issue?", choices=["yes", "no", "skip"], default="yes"
                )

                if fix_choice == "yes":
                    self.console.print("  🔧 Applying fix...")
                    issue.proposed_fix.apply()
                    self.console.print("  ✅ [green]Fixed[/green]")
                    continue
                elif fix_choice == "skip":
                    continue

            # Ask override question
            question = (
                issue.override_question
                or "Continue with release despite this issue? (y/N)"
            )

            if not Confirm.ask(question, default=False):
                self.console.print("❌ [red]Release cancelled by user[/red]")
                return False
            else:
                self.console.print("  ⚠️  [yellow]Proceeding despite issue[/yellow]")
                self.overrides[f"{issue.check}:{issue.description}"] = True

        return True

    def _handle_informational_issues(self, issues: list[Issue]) -> None:
        """Handle informational issues (non-blocking)."""
        if not issues:
            return

        self.console.print("\n[bold blue]Suggestions for Improvement[/bold blue]")

        for issue in issues:
            panel = Panel(
                f"[blue]{issue.description}[/blue]\n\n[dim]{issue.explanation}[/dim]",
                title=f"{issue.check} - Info",
                border_style="blue",
            )
            self.console.print(panel)

            # Offer fix if available
            if issue.proposed_fix and Confirm.ask(
                "Apply this improvement?", default=False
            ):
                self.console.print("  🔧 Applying fix...")
                issue.proposed_fix.apply()
                self.console.print("  ✅ [green]Applied[/green]")

    def _final_release_confirmation(self, target: str) -> bool:
        """Final confirmation before release."""
        self.console.print("\n" + "=" * 50)

        if self.overrides:
            self.console.print("\n⚠️  [yellow]Summary of overrides:[/yellow]")
            for override in self.overrides:
                self.console.print(f"  • {override}")
            self.console.print()

        self.console.print("🎯 [bold green]Ready for Release[/bold green]")

        return Confirm.ask(f"\n🚀 Proceed with release to {target}?", default=False)


class EducationalPrompt:
    """Helper for showing educational information about checks."""

    def __init__(self, console: Console | None = None):
        """Initialize the educational prompt helper.

        Args:
            console: Rich console for output.
        """
        self.console = console or Console()

    def explain_check(self, check_name: str, issues: list[Issue]) -> None:
        """Explain why a check matters and what issues mean."""
        if not issues:
            self.console.print(f"✅ [green]{check_name} passed[/green]")
            return

        self.console.print(f"\n📚 [bold]About {check_name} check:[/bold]")

        # Group explanations by unique explanations
        explanations = {issue.explanation for issue in issues if issue.explanation}

        for explanation in explanations:
            if explanation:
                self.console.print(f"  {explanation}")

        self.console.print(f"\n  Found {len(issues)} issue(s):")
        for issue in issues:
            symbol = issue.get_impact_symbol()
            self.console.print(f"  {symbol} {issue.description}")
