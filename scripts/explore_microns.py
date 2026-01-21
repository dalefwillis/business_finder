"""Exploration helper script for Microns.io.

This script is designed to be used alongside Claude Chrome exploration.
It provides utilities to log discoveries and export them as scraper config.

Usage:
    poetry run python scripts/explore_microns.py

The script initializes an exploration session and provides a REPL-like
interface for logging discoveries made during Claude Chrome exploration.
"""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rich.console import Console
from rich.table import Table

from business_finder.db import init_db, log_exploration, get_exploration_logs


console = Console()

SOURCE_ID = "microns"


class ExplorationSession:
    """Helper class for logging exploration discoveries."""

    def __init__(self, source_id: str = SOURCE_ID):
        self.source_id = source_id
        init_db()
        console.print(f"[green]Exploration session started for {source_id}[/green]")

    def log_navigation(self, url: str, description: str) -> int:
        """Log a navigation step.

        Args:
            url: URL navigated to
            description: What was found/observed

        Returns:
            Log entry ID.
        """
        log_id = log_exploration(
            source_id=self.source_id,
            action_type="navigation",
            selector=url,
            description=description,
        )
        console.print(f"[blue]Logged navigation:[/blue] {description}")
        return log_id

    def log_selector(
        self, selector: str, purpose: str, example_value: str | None = None
    ) -> int:
        """Log a discovered selector.

        Args:
            selector: CSS or XPath selector
            purpose: What this selector is for (e.g., 'listing_link', 'price')
            example_value: Example value extracted using this selector

        Returns:
            Log entry ID.
        """
        log_id = log_exploration(
            source_id=self.source_id,
            action_type="selector",
            selector=selector,
            description=purpose,
            example_value=example_value,
        )
        console.print(f"[yellow]Logged selector for {purpose}:[/yellow] {selector}")
        if example_value:
            console.print(f"  Example: {example_value}")
        return log_id

    def log_extraction_pattern(
        self,
        field_name: str,
        selector: str,
        transform: str | None = None,
        example_value: str | None = None,
    ) -> int:
        """Log how to extract a specific field.

        Args:
            field_name: Name of the field (e.g., 'asking_price', 'mrr')
            selector: CSS selector to find the element
            transform: Optional transformation (e.g., 'parse_price', 'strip_text')
            example_value: Example of extracted value

        Returns:
            Log entry ID.
        """
        description = f"field:{field_name}"
        if transform:
            description += f" transform:{transform}"

        log_id = log_exploration(
            source_id=self.source_id,
            action_type="extract",
            selector=selector,
            description=description,
            example_value=example_value,
        )
        console.print(f"[green]Logged extraction for {field_name}:[/green] {selector}")
        if example_value:
            console.print(f"  Example: {example_value}")
        return log_id

    def show_logs(self) -> None:
        """Display all logged discoveries for this source."""
        logs = get_exploration_logs(self.source_id)

        if not logs:
            console.print("[yellow]No exploration logs yet.[/yellow]")
            return

        table = Table(title=f"Exploration Logs for {self.source_id}")
        table.add_column("ID", style="cyan")
        table.add_column("Type", style="magenta")
        table.add_column("Selector/URL")
        table.add_column("Description")
        table.add_column("Example")

        for log in logs:
            table.add_row(
                str(log["id"]),
                log["action_type"],
                log["selector"] or "",
                log["description"] or "",
                log["example_value"] or "",
            )

        console.print(table)

    def export_to_scraper_config(self) -> dict:
        """Export discoveries as config for Playwright scraper.

        Returns:
            Dict with scraper configuration derived from exploration.
        """
        logs = get_exploration_logs(self.source_id)

        config = {
            "source_id": self.source_id,
            "base_url": "https://microns.io",
            "selectors": {},
            "field_extractions": {},
            "navigations": [],
        }

        for log in logs:
            if log["action_type"] == "selector":
                config["selectors"][log["description"]] = log["selector"]
            elif log["action_type"] == "extract":
                # Parse field name from description
                desc = log["description"]
                if desc.startswith("field:"):
                    field_name = desc.split()[0].replace("field:", "")
                    config["field_extractions"][field_name] = {
                        "selector": log["selector"],
                        "example": log["example_value"],
                    }
            elif log["action_type"] == "navigation":
                config["navigations"].append(
                    {"url": log["selector"], "description": log["description"]}
                )

        return config


def main():
    """Interactive exploration session."""
    session = ExplorationSession()

    console.print("\n[bold]Exploration Commands:[/bold]")
    console.print("  nav <url> <description>  - Log a navigation")
    console.print("  sel <selector> <purpose> [example] - Log a selector")
    console.print("  ext <field> <selector> [example] - Log field extraction")
    console.print("  show - Show all logs")
    console.print("  export - Export config")
    console.print("  quit - Exit\n")

    while True:
        try:
            cmd = console.input("[bold blue]explore>[/bold blue] ").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if not cmd:
            continue

        parts = cmd.split(maxsplit=3)
        action = parts[0].lower()

        if action == "quit" or action == "q":
            break
        elif action == "show":
            session.show_logs()
        elif action == "export":
            config = session.export_to_scraper_config()
            console.print_json(data=config)
        elif action == "nav" and len(parts) >= 3:
            session.log_navigation(parts[1], " ".join(parts[2:]))
        elif action == "sel" and len(parts) >= 3:
            example = parts[3] if len(parts) > 3 else None
            session.log_selector(parts[1], parts[2], example)
        elif action == "ext" and len(parts) >= 3:
            example = parts[3] if len(parts) > 3 else None
            session.log_extraction_pattern(parts[1], parts[2], example_value=example)
        else:
            console.print("[red]Unknown command or missing arguments[/red]")

    console.print("[green]Exploration session ended.[/green]")


if __name__ == "__main__":
    main()
