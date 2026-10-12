"""Pin user-supplied cloud model requests to validated public network addresses."""

import asyncio
import ipaddress
import socket

import httpx

from app.errors import AppError


async def public_model_target(url, timeout):
    url = httpx.URL(url)
    try:
        addresses = [ipaddress.ip_address(url.host)]
    except ValueError:
        try:
            records = await asyncio.wait_for(
                asyncio.get_running_loop().getaddrinfo(
                    url.host, url.port or (443 if url.scheme == "https" else 80), type=socket.SOCK_STREAM
                ),
                timeout=timeout,
            )
        except (OSError, TimeoutError):
            raise AppError("MODEL_CONFIGURATION", "模型接口域名无法解析，请检查 API 地址", 502) from None
        addresses = list({ipaddress.ip_address(record[4][0]) for record in records})
    if not addresses or any(
        not address.is_global or address.is_multicast or address.is_reserved for address in addresses
    ):
        raise AppError("MODEL_ADDRESS_BLOCKED", "自定义云模型仅支持公网地址，不能访问本机或内网服务", 422)
    # Connect to the checked IP, rather than resolving the hostname again (DNS rebinding).
    address = sorted(addresses, key=lambda value: (value.version, int(value)))[0]
    return url.copy_with(host=str(address)), url.netloc.decode("ascii"), url.raw_host.decode("ascii")
