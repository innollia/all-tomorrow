from all_tomorrow.error_normalization import normalize_exception

err1 = RuntimeError("Client failed to connect: All connection attempts failed")
print("err1:", normalize_exception(err1))

try:
    import httpx
    raise httpx.ConnectError("Failed to connect") from None
except Exception as exc:
    print("httpx ConnectError:", normalize_exception(exc))

try:
    raise ConnectionRefusedError("Connection refused")
except Exception as exc:
    print("ConnectionRefusedError:", normalize_exception(exc))
