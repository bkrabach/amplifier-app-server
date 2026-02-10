"""CLI entry point for Amplifier Server."""

import logging
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

console = Console()


def setup_logging(verbose: bool = False) -> None:
    """Configure logging with rich output."""
    level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """Amplifier Server - Always-on AI agent runtime."""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    setup_logging(verbose)


@cli.command()
@click.option(
    "--host",
    default="0.0.0.0",
    help="Host to bind to",
)
@click.option(
    "--port",
    default=19420,
    type=int,
    help="Port to listen on",
)
@click.option(
    "--data-dir",
    default="~/.amplifier-server",
    type=click.Path(),
    help="Directory for server data",
)
@click.option(
    "--bundle",
    "bundles",
    multiple=True,
    help="Bundle(s) to load on startup (can specify multiple)",
)
@click.pass_context
def run(
    ctx: click.Context,
    host: str,
    port: int,
    data_dir: str,
    bundles: tuple[str, ...],
) -> None:
    """Run the Amplifier Server."""
    from amplifier_server.server import create_server

    console.print("[bold blue]Amplifier Server[/bold blue] v0.1.0")
    console.print(f"Data directory: {Path(data_dir).expanduser()}")
    console.print(f"Listening on: http://{host}:{port}")
    console.print()

    server = create_server(
        data_dir=data_dir,
        host=host,
        port=port,
    )

    # Create initial sessions for specified bundles
    if bundles:
        import asyncio

        async def create_initial_sessions():
            for bundle in bundles:
                try:
                    session_id = await server.session_manager.create_session(bundle=bundle)
                    console.print(f"[green]✓[/green] Created session: {session_id} ({bundle})")
                except Exception as e:
                    console.print(f"[red]✗[/red] Failed to create session for {bundle}: {e}")

        asyncio.get_event_loop().run_until_complete(create_initial_sessions())
        console.print()

    console.print("[dim]Press Ctrl+C to stop[/dim]")
    console.print()

    try:
        server.run()
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down...[/yellow]")


@cli.command()
@click.option(
    "--server",
    default="http://localhost:19420",
    help="Server URL",
)
def status(server: str) -> None:
    """Check server status."""
    import httpx

    try:
        response = httpx.get(f"{server}/health", timeout=5)
        data = response.json()

        console.print(f"[bold green]Server Status: {data['status']}[/bold green]")
        console.print(f"Sessions: {data['sessions']}")
        console.print(f"Connected devices: {data['connected_devices']}")

    except httpx.ConnectError:
        console.print(f"[bold red]Cannot connect to server at {server}[/bold red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        sys.exit(1)


@cli.command()
@click.option(
    "--server",
    default="http://localhost:19420",
    help="Server URL",
)
def sessions(server: str) -> None:
    """List active sessions."""
    import httpx

    try:
        response = httpx.get(f"{server}/sessions", timeout=5)
        data = response.json()

        if not data:
            console.print("[dim]No active sessions[/dim]")
            return

        table = Table(title="Active Sessions")
        table.add_column("Session ID", style="cyan")
        table.add_column("Bundle", style="green")
        table.add_column("Status")
        table.add_column("Messages", justify="right")
        table.add_column("Created")

        for session in data:
            status_style = "green" if session["status"] == "ready" else "yellow"
            table.add_row(
                session["session_id"],
                session["bundle"],
                f"[{status_style}]{session['status']}[/{status_style}]",
                str(session["message_count"]),
                session["created_at"][:19],
            )

        console.print(table)

    except httpx.ConnectError:
        console.print(f"[bold red]Cannot connect to server at {server}[/bold red]")
        sys.exit(1)


@cli.command()
@click.option(
    "--server",
    default="http://localhost:19420",
    help="Server URL",
)
def devices(server: str) -> None:
    """List connected devices."""
    import httpx

    try:
        response = httpx.get(f"{server}/devices", timeout=5)
        data = response.json()

        if not data:
            console.print("[dim]No connected devices[/dim]")
            return

        table = Table(title="Connected Devices")
        table.add_column("Device ID", style="cyan")
        table.add_column("Name")
        table.add_column("Platform", style="green")
        table.add_column("Connected")
        table.add_column("Last Seen")

        for device in data:
            table.add_row(
                device["device_id"],
                device.get("device_name") or "-",
                device["platform"],
                device["connected_at"][:19],
                device["last_seen"][:19],
            )

        console.print(table)

    except httpx.ConnectError:
        console.print(f"[bold red]Cannot connect to server at {server}[/bold red]")
        sys.exit(1)


@cli.command()
@click.argument("bundle")
@click.option(
    "--server",
    default="http://localhost:19420",
    help="Server URL",
)
@click.option(
    "--session-id",
    default=None,
    help="Custom session ID",
)
def create(bundle: str, server: str, session_id: str | None) -> None:
    """Create a new session with a bundle."""
    import httpx

    try:
        payload = {"bundle": bundle}
        if session_id:
            payload["session_id"] = session_id

        response = httpx.post(f"{server}/sessions", json=payload, timeout=30)

        if response.status_code == 200:
            data = response.json()
            console.print(f"[green]✓[/green] {data['message']}")
            console.print(f"Session ID: [cyan]{data['session_id']}[/cyan]")
        else:
            console.print(f"[red]Error: {response.text}[/red]")
            sys.exit(1)

    except httpx.ConnectError:
        console.print(f"[bold red]Cannot connect to server at {server}[/bold red]")
        sys.exit(1)


@cli.command()
@click.argument("session_id")
@click.argument("prompt")
@click.option(
    "--server",
    default="http://localhost:19420",
    help="Server URL",
)
def execute(session_id: str, prompt: str, server: str) -> None:
    """Execute a prompt in a session."""
    import httpx

    try:
        response = httpx.post(
            f"{server}/sessions/{session_id}/execute",
            json={"prompt": prompt},
            timeout=120,
        )

        if response.status_code == 200:
            data = response.json()
            console.print(data["response"])
            console.print()
            console.print(f"[dim]Duration: {data['duration_ms']}ms[/dim]")
        else:
            console.print(f"[red]Error: {response.text}[/red]")
            sys.exit(1)

    except httpx.ConnectError:
        console.print(f"[bold red]Cannot connect to server at {server}[/bold red]")
        sys.exit(1)


@cli.command()
@click.argument("session_id")
@click.option(
    "--server",
    default="http://localhost:19420",
    help="Server URL",
)
def chat(session_id: str, server: str) -> None:
    """Interactive chat with a session."""
    import asyncio
    import json

    import websockets

    ws_url = server.replace("http://", "ws://").replace("https://", "wss://")

    async def chat_loop():
        try:
            async with websockets.connect(f"{ws_url}/ws/chat/{session_id}") as ws:
                console.print(f"[green]Connected to session {session_id}[/green]")
                console.print("[dim]Type 'quit' to exit[/dim]\n")

                while True:
                    try:
                        prompt = console.input("[bold cyan]You:[/bold cyan] ")

                        if prompt.lower() in ("quit", "exit", "q"):
                            break

                        if not prompt.strip():
                            continue

                        # Send message
                        await ws.send(
                            json.dumps(
                                {
                                    "type": "chat",
                                    "payload": {"prompt": prompt},
                                }
                            )
                        )

                        # Wait for response
                        while True:
                            response = await ws.recv()
                            data = json.loads(response)

                            if data["type"] == "ack":
                                console.print("[dim]Processing...[/dim]")
                            elif data["type"] == "response":
                                content = data["payload"]["content"]
                                console.print(f"\n[bold green]Assistant:[/bold green] {content}\n")
                                break
                            elif data["type"] == "error":
                                console.print(f"[red]Error: {data['payload']['message']}[/red]\n")
                                break

                    except KeyboardInterrupt:
                        break

        except Exception as e:
            console.print(f"[red]Connection error: {e}[/red]")

    asyncio.get_event_loop().run_until_complete(chat_loop())


@cli.group()
def service():
    """Manage Cortex Server as a systemd service (Linux)."""
    pass


@service.command("install")
@click.option(
    "--port",
    default=19420,
    type=int,
    help="Port to run the server on",
)
@click.option(
    "--env-file",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to environment file with API keys etc.",
)
def service_install(port: int, env_file: Path | None) -> None:
    """Install Cortex Server as a systemd user service.

    This configures the server to start automatically when you log in,
    and enables 'lingering' so it runs even when you're not logged in.

    Examples:

        # Basic install
        amplifier-server service install

        # With custom port
        amplifier-server service install --port 8080

        # With environment file for API keys
        amplifier-server service install --env-file ~/.cortex/server.env
    """
    from amplifier_server import startup

    if startup.install(port=port, env_file=env_file):
        console.print("[green]✅ Installed![/green] Cortex Server will start automatically.")
        console.print()
        console.print("To start it now:")
        console.print("  amplifier-server service start")
        console.print()
        console.print("To check status:")
        console.print("  amplifier-server service status")
        console.print()
        console.print("To view logs:")
        console.print("  amplifier-server service logs")
    else:
        console.print("[red]❌ Installation failed.[/red] See errors above.")
        sys.exit(1)


@service.command("uninstall")
def service_uninstall() -> None:
    """Remove Cortex Server from systemd.

    This stops the service and removes it from automatic startup.
    """
    from amplifier_server import startup

    if startup.uninstall():
        console.print(
            "[green]✅ Uninstalled.[/green] Cortex Server will no longer start automatically."
        )
    else:
        console.print("[red]❌ Uninstallation failed.[/red] See errors above.")
        sys.exit(1)


@service.command("status")
def service_status() -> None:
    """Check if Cortex Server service is installed and running."""
    from amplifier_server import startup

    status = startup.get_status()

    if not status.get("installed"):
        console.print("[yellow]Not installed[/yellow] as a systemd service")
        console.print()
        console.print("To install:")
        console.print("  amplifier-server service install")
        return

    console.print("[green]✅ Installed[/green] as systemd user service")
    console.print()

    if status.get("running"):
        console.print("Status: [green]Running[/green]")
    else:
        console.print("Status: [yellow]Stopped[/yellow]")

    if status.get("active"):
        console.print(f"Active: {status['active']}")
    if status.get("pid"):
        console.print(f"PID: {status['pid']}")


@service.command("start")
def service_start() -> None:
    """Start the Cortex Server service."""
    from amplifier_server import startup

    if not startup.is_installed():
        console.print("[red]❌ Not installed.[/red] Run 'amplifier-server service install' first.")
        sys.exit(1)

    if startup.start():
        console.print("[green]✅ Started[/green] Cortex Server")
    else:
        console.print("[red]❌ Failed to start.[/red] See errors above.")
        console.print()
        console.print("Check logs with: amplifier-server service logs")
        sys.exit(1)


@service.command("stop")
def service_stop() -> None:
    """Stop the Cortex Server service."""
    from amplifier_server import startup

    if startup.stop():
        console.print("[green]✅ Stopped[/green] Cortex Server")
    else:
        console.print("[red]❌ Failed to stop.[/red] See errors above.")
        sys.exit(1)


@service.command("restart")
def service_restart() -> None:
    """Restart the Cortex Server service."""
    from amplifier_server import startup

    if not startup.is_installed():
        console.print("[red]❌ Not installed.[/red] Run 'amplifier-server service install' first.")
        sys.exit(1)

    if startup.restart():
        console.print("[green]✅ Restarted[/green] Cortex Server")
    else:
        console.print("[red]❌ Failed to restart.[/red] See errors above.")
        console.print()
        console.print("Check logs with: amplifier-server service logs")
        sys.exit(1)


@service.command("logs")
@click.option("-f", "--follow", is_flag=True, help="Follow log output (like tail -f)")
@click.option("-n", "--lines", default=50, help="Number of lines to show")
def service_logs(follow: bool, lines: int) -> None:
    """View Cortex Server service logs."""
    from amplifier_server import startup

    if not startup.is_installed():
        console.print("[red]❌ Not installed.[/red] No logs available.")
        sys.exit(1)

    output = startup.logs(follow=follow, lines=lines)
    if output:
        console.print(output)


def main() -> None:
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
