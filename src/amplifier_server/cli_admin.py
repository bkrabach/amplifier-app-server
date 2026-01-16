"""Admin CLI commands for user and API key management."""

import asyncio
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group()
def admin():
    """Admin commands for user management."""
    pass


@admin.command()
@click.option("--username", prompt=True, help="Admin username")
@click.password_option(help="Admin password")
@click.option("--email", help="Admin email (optional)")
@click.option(
    "--data-dir",
    default="~/.amplifier-server",
    help="Server data directory",
)
def init_admin(username: str, password: str, email: str | None, data_dir: str):
    """Initialize first admin user (bootstrap)."""
    import secrets

    from amplifier_server.auth.models import UserRole
    from amplifier_server.auth.security import hash_password, init_security
    from amplifier_server.auth.user_store import UserStore

    data_path = Path(data_dir).expanduser()
    db_path = data_path / "system" / "users.db"

    # Initialize security with a random secret
    init_security(secrets.token_urlsafe(32))

    # Create user store
    user_store = UserStore(db_path)

    async def create_admin():
        await user_store.initialize()

        # Check if users exist
        count = await user_store.count_users()
        if count > 0:
            console.print(
                "[yellow]⚠️  Users already exist. "
                "Use the web admin UI or API to manage users.[/yellow]"
            )
            return

        # Create admin user
        password_hash = hash_password(password)
        user = await user_store.create_user(
            username=username,
            password_hash=password_hash,
            email=email,
            role=UserRole.ADMIN,
        )

        console.print(f"[green]✓[/green] Admin user created: {user.username}")
        console.print(f"[dim]User ID: {user.id}[/dim]")
        console.print(
            "\n[bold]Next steps:[/bold]\n"
            f"1. Start server: amplifier-server\n"
            f"2. Login at: http://localhost:8420/login\n"
            f"3. Username: {username}\n"
        )

        await user_store.close()

    asyncio.run(create_admin())


@admin.command()
@click.option(
    "--data-dir",
    default="~/.amplifier-server",
    help="Server data directory",
)
def users_list(data_dir: str):
    """List all users."""
    import secrets

    from amplifier_server.auth.security import init_security
    from amplifier_server.auth.user_store import UserStore

    data_path = Path(data_dir).expanduser()
    db_path = data_path / "system" / "users.db"

    init_security(secrets.token_urlsafe(32))
    user_store = UserStore(db_path)

    async def list_users():
        await user_store.initialize()
        users = await user_store.list_users()

        if not users:
            console.print("[yellow]No users found.[/yellow]")
            return

        table = Table(title="Users")
        table.add_column("Username", style="cyan")
        table.add_column("Email", style="magenta")
        table.add_column("Role", style="green")
        table.add_column("Active", style="yellow")
        table.add_column("Created", style="dim")

        for user in users:
            table.add_row(
                user.username,
                user.email or "-",
                user.role.value,
                "✓" if user.is_active else "✗",
                user.created_at.strftime("%Y-%m-%d"),
            )

        console.print(table)
        await user_store.close()

    asyncio.run(list_users())


@admin.command()
@click.option("--username", required=True, help="Username")
@click.password_option(help="Password")
@click.option("--email", help="Email (optional)")
@click.option(
    "--data-dir",
    default="~/.amplifier-server",
    help="Server data directory",
)
def users_create(username: str, password: str, email: str | None, data_dir: str):
    """Create new user."""
    import secrets

    from amplifier_server.auth.models import UserRole
    from amplifier_server.auth.security import hash_password, init_security
    from amplifier_server.auth.user_store import UserStore

    data_path = Path(data_dir).expanduser()
    db_path = data_path / "system" / "users.db"

    init_security(secrets.token_urlsafe(32))
    user_store = UserStore(db_path)

    async def create_user():
        await user_store.initialize()

        password_hash = hash_password(password)
        try:
            user = await user_store.create_user(
                username=username,
                password_hash=password_hash,
                email=email,
                role=UserRole.USER,
            )
            console.print(f"[green]✓[/green] User created: {user.username}")
            console.print(f"[dim]User ID: {user.id}[/dim]")
        except ValueError as e:
            console.print(f"[red]✗[/red] Error: {e}")

        await user_store.close()

    asyncio.run(create_user())


@admin.command()
@click.option("--username", required=True, help="Username")
@click.option(
    "--data-dir",
    default="~/.amplifier-server",
    help="Server data directory",
)
def users_disable(username: str, data_dir: str):
    """Disable a user account."""
    import secrets

    from amplifier_server.auth.security import init_security
    from amplifier_server.auth.user_store import UserStore

    data_path = Path(data_dir).expanduser()
    db_path = data_path / "system" / "users.db"

    init_security(secrets.token_urlsafe(32))
    user_store = UserStore(db_path)

    async def disable_user():
        await user_store.initialize()

        user = await user_store.get_user_by_username(username)
        if not user:
            console.print(f"[red]✗[/red] User not found: {username}")
            return

        await user_store.update_user(user.id, is_active=False)
        await user_store.revoke_user_tokens(user.id)

        console.print(f"[green]✓[/green] User disabled: {username}")
        await user_store.close()

    asyncio.run(disable_user())


@admin.command()
@click.option("--username", required=True, help="Username")
@click.option("--name", prompt=True, help="API key name (e.g., 'Windows Desktop')")
@click.option("--expires-days", type=int, help="Expiration in days (optional)")
@click.option(
    "--data-dir",
    default="~/.amplifier-server",
    help="Server data directory",
)
def api_keys_generate(username: str, name: str, expires_days: int | None, data_dir: str):
    """Generate API key for user."""
    import secrets
    from datetime import datetime, timedelta

    from amplifier_server.auth.security import generate_api_key, init_security
    from amplifier_server.auth.user_store import UserStore

    data_path = Path(data_dir).expanduser()
    db_path = data_path / "system" / "users.db"

    init_security(secrets.token_urlsafe(32))
    user_store = UserStore(db_path)

    async def create_api_key():
        await user_store.initialize()

        user = await user_store.get_user_by_username(username)
        if not user:
            console.print(f"[red]✗[/red] User not found: {username}")
            return

        # Generate API key
        full_key, key_hash, prefix = generate_api_key(user.id)

        expires_at = None
        if expires_days:
            expires_at = datetime.utcnow() + timedelta(days=expires_days)

        api_key = await user_store.create_api_key(
            user_id=user.id,
            key_hash=key_hash,
            prefix=prefix,
            name=name,
            expires_at=expires_at,
        )

        console.print(f"[green]✓[/green] API key created for {username}")
        console.print("\n[bold yellow]⚠️  Save this key - it will not be shown again![/bold yellow]")
        console.print(f"\n[bold cyan]{full_key}[/bold cyan]\n")
        console.print(f"[dim]Key ID: {api_key.id}[/dim]")
        console.print(f"[dim]Name: {name}[/dim]")
        if expires_at:
            console.print(f"[dim]Expires: {expires_at.strftime('%Y-%m-%d')}[/dim]")

        await user_store.close()

    asyncio.run(create_api_key())


@admin.command()
@click.option("--username", required=True, help="Username")
@click.option(
    "--data-dir",
    default="~/.amplifier-server",
    help="Server data directory",
)
def api_keys_list(username: str, data_dir: str):
    """List API keys for a user."""
    import secrets

    from amplifier_server.auth.security import init_security
    from amplifier_server.auth.user_store import UserStore

    data_path = Path(data_dir).expanduser()
    db_path = data_path / "system" / "users.db"

    init_security(secrets.token_urlsafe(32))
    user_store = UserStore(db_path)

    async def list_keys():
        await user_store.initialize()

        user = await user_store.get_user_by_username(username)
        if not user:
            console.print(f"[red]✗[/red] User not found: {username}")
            return

        keys = await user_store.list_api_keys(user.id)

        if not keys:
            console.print(f"[yellow]No API keys for {username}[/yellow]")
            return

        table = Table(title=f"API Keys for {username}")
        table.add_column("Name", style="cyan")
        table.add_column("Prefix", style="magenta")
        table.add_column("Active", style="yellow")
        table.add_column("Last Used", style="dim")
        table.add_column("Expires", style="dim")

        for key in keys:
            table.add_row(
                key.name,
                key.prefix,
                "✓" if key.is_active else "✗",
                key.last_used.strftime("%Y-%m-%d %H:%M") if key.last_used else "Never",
                key.expires_at.strftime("%Y-%m-%d") if key.expires_at else "Never",
            )

        console.print(table)
        await user_store.close()

    asyncio.run(list_keys())


if __name__ == "__main__":
    admin()
