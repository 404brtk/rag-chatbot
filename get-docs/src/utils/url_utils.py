from urllib.parse import (
    urljoin,
    urlparse,
    urlunparse,
)

ASSET_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".zip",
        ".tar",
        ".gz",
        ".rar",
        ".7z",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".webp",
        ".ico",
        ".css",
        ".js",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".mp3",
        ".mp4",
        ".avi",
        ".mov",
        ".wmv",
        ".xml",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".exe",
        ".dmg",
        ".deb",
        ".rpm",
    }
)

IGNORED_SCHEMES = frozenset(
    {
        "mailto",
        "javascript",
        "tel",
        "ftp",
        "data",
    }
)


def normalize_url(url: str) -> str:
    parsed = urlparse(
        url
    )  # e.g. ParseResult(scheme='https', netloc='fastapi.tiangolo.com', path='', params='', query='', fragment='')

    path = parsed.path
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    if not path:
        path = "/"

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    return urlunparse((scheme, netloc, path, "", "", ""))


def extract_origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def extract_domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def extract_path(url: str) -> str:
    return urlparse(url).path


def resolve_relative(base_url: str, relative_url: str) -> str:
    return urljoin(base_url, relative_url)


def is_same_domain(url: str, base_url: str) -> bool:
    return extract_domain(url) == extract_domain(base_url)


def is_asset_url(url: str) -> bool:
    parsed = urlparse(url)

    if parsed.scheme in IGNORED_SCHEMES:
        return True

    path = parsed.path.lower()
    for ext in ASSET_EXTENSIONS:
        if path.endswith(ext):
            return True

    return False


def is_absolute_url(url: str) -> bool:
    return url.startswith(("http://", "https://"))


def url_path_parents(url: str) -> list[str]:
    """Walk up url path segments from the given path level to origin root.

    https://example.com/docs/en/home → [
        "https://example.com/docs/en/home",
        "https://example.com/docs/en",
        "https://example.com/docs",
        "https://example.com",
    ]
    """
    origin = extract_origin(url)
    path = urlparse(url).path.rstrip("/")

    parents: list[str] = []
    while path:
        parents.append(origin + path)
        path = path.rsplit("/", 1)[0]

    if not parents or parents[-1] != origin:
        parents.append(origin)

    return parents


def make_url_prefix(url: str) -> str:
    origin = extract_origin(url)
    path = urlparse(url).path.rstrip("/")

    if path:
        last_segment = path.rsplit("/", 1)[-1]
        if "." in last_segment:
            path = path.rsplit("/", 1)[0].rstrip("/")

    return origin + path if path else origin


def is_url_within_scope(url: str, prefix: str) -> bool:
    return url == prefix or url.startswith(prefix + "/")


def strip_git_suffix(name: str) -> str:
    if name.endswith(".git"):
        return name[:-4]
    return name
