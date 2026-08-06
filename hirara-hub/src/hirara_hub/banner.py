"""ASCII startup banner for the Hirara hub."""

BANNER = (
    "    __  __________  ___    ____  ___ \n"
    "   / / / /  _/ __ \\/   |  / __ \\/   |\n"
    "  / /_/ // // /_/ / /| | / /_/ / /| |\n"
    " / __  // // _, _/ ___ |/ _, _/ ___ |\n"
    "/_/ /_/___/_/ |_/_/  |_/_/ |_/_/  |_|"
)

TAGLINE = "self-hosted agent tool hub"


def render(subtitle: str = "") -> str:
    """The banner followed by a subtitle line."""
    return f"{BANNER}\n    {subtitle or TAGLINE}\n"


def show(subtitle: str = "") -> None:
    print(render(subtitle), flush=True)


__all__ = ["BANNER", "TAGLINE", "render", "show"]
