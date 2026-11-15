"""Fetch seguro de páginas (seção 13 do PRD).

- Apenas HTTP e HTTPS; loopback, privado, link-local e reservado são bloqueados.
- Validação de resolução e destino em cada salto, inclusive redirecionamentos.
- Limites de tamanho, tempo, redirecionamentos e tipo de conteúdo.
- Sem proxies herdados do ambiente e sem encaminhamento de credenciais.

Limitação conhecida do MVP: a validação ocorre antes de cada conexão
(resolução prévia); não há fixação do IP na conexão TLS.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Callable
from urllib.parse import urljoin, urlparse

import httpx

from formiga.config import Config
from formiga.fetch import FetchedPage, FetchError

MAX_REDIRECTS = 5
USER_AGENT = "formiga/0.1 (harness de pesquisa)"
ALLOWED_CONTENT_TYPES = ("text/html", "text/plain", "application/xhtml")
REDIRECT_CODES = {301, 302, 303, 307, 308}

Resolver = Callable[[str, int], list[str]]


def _default_resolver(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchError(host, f"Falha de resolução DNS: {exc}") from exc
    return [info[4][0] for info in infos]


def _check_ips(ips: list[str], host: str) -> None:
    for ip in ips:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        blocked = (
            addr.is_loopback
            or addr.is_private
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
            or addr.is_unspecified
        )
        if blocked:
            raise FetchError(host, f"Endereço interno bloqueado: {ip}")


def _validate_scheme(url: str) -> urlparse:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise FetchError(url, f"Esquema não permitido: {parsed.scheme or '(vazio)'}")
    if parsed.username or parsed.password:
        raise FetchError(url, "URL com credenciais não é aceita.")
    if not parsed.hostname:
        raise FetchError(url, "URL sem host.")
    return parsed


def _charset(content_type: str) -> str:
    match = re.search(r"charset=([\w-]+)", content_type, re.IGNORECASE)
    return match.group(1) if match else "utf-8"


class SafeFetcher:
    def __init__(
        self,
        config: Config,
        resolver: Resolver | None = None,
        transport: httpx.BaseTransport | None = None,
        remaining_seconds: Callable[[], float] | None = None,
    ) -> None:
        self.max_bytes = config.max_http_bytes
        self.timeout = config.network_timeout
        self._resolve = resolver or _default_resolver
        self._transport = transport
        self._remaining = remaining_seconds

    def _effective_timeout(self) -> float:
        """Timeout limitado ao tempo restante da execução."""
        if self._remaining is None:
            return self.timeout
        return max(0.05, min(self.timeout, self._remaining()))

    def fetch(self, url: str) -> FetchedPage:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            parsed = _validate_scheme(current)
            host = parsed.hostname or ""
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            _check_ips(self._resolve(host, port), host)
            status, headers, content = self._request(current)
            if status in REDIRECT_CODES:
                location = headers.get("location", "")
                if not location:
                    raise FetchError(current, "Redirecionamento sem destino.")
                current = urljoin(current, location)
                continue
            if status >= 400:
                raise FetchError(current, f"HTTP {status}.")
            content_type = headers.get("content-type", "").lower()
            if not any(t in content_type for t in ALLOWED_CONTENT_TYPES):
                raise FetchError(current, f"Tipo de conteúdo não suportado: {content_type}.")
            if len(content) > self.max_bytes:
                raise FetchError(current, f"Conteúdo excede {self.max_bytes} bytes.")
            return FetchedPage(
                requested_url=url,
                final_url=current,
                content=content.decode(_charset(content_type), errors="replace"),
            )
        raise FetchError(url, f"Mais de {MAX_REDIRECTS} redirecionamentos.")

    def _request(self, url: str) -> tuple[int, dict[str, str], bytes]:
        """Uma requisição com corpo limitado a max_bytes durante o download."""
        with httpx.Client(
            transport=self._transport,
            trust_env=False,
            follow_redirects=False,
            timeout=self._effective_timeout(),
        ) as client:
            try:
                with client.stream(
                    "GET", url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"}
                ) as response:
                    buf = bytearray()
                    declared = response.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > self.max_bytes:
                        raise FetchError(url, f"Conteúdo excede {self.max_bytes} bytes.")
                    for chunk in response.iter_bytes(chunk_size=65536):
                        buf.extend(chunk)
                        if len(buf) > self.max_bytes:
                            raise FetchError(url, f"Conteúdo excede {self.max_bytes} bytes.")
                    headers = {k.lower(): v for k, v in response.headers.items()}
                    return response.status_code, headers, bytes(buf)
            except httpx.HTTPError as exc:
                raise FetchError(url, f"Falha de rede: {exc}") from exc
