"""Disposable Docker network boundary probe. Fail on any direct outbound access."""
import json
import socket
import sys
import time


def must_fail_direct(address, port):
    try:
        with socket.create_connection((address, port), timeout=2):
            raise AssertionError(f"worker escaped sealed network to {address}:{port}")
    except (TimeoutError, OSError):
        return


def main():
    for ip, port in (("1.1.1.1", 443), ("169.254.169.254", 80), ("8.8.8.8", 53)):
        must_fail_direct(ip, port)
    def connect_proxy():
        for attempt in range(20):
            try:
                return socket.create_connection(("egress", 3128), timeout=2)
            except (OSError, TimeoutError):
                if attempt == 19:
                    raise
                time.sleep(0.5)
    with connect_proxy() as s:
        s.sendall(b"CONNECT evil.example.org:443 HTTP/1.1\r\nHost: evil.example.org:443\r\n\r\n")
        response=s.recv(128)
        assert response.startswith(b"HTTP/1.1 403"), response
    with socket.create_connection(("egress", 3128), timeout=10) as s:
        s.sendall(b"CONNECT 169.254.169.254:443 HTTP/1.1\r\nHost: 169.254.169.254:443\r\n\r\n")
        response=s.recv(128)
        assert response.startswith(b"HTTP/1.1 403"), response
    print(json.dumps({"result":"pass","scope":"disposable Docker sealed bridge",
                      "limitations":"No external DNS-rebind drill or production host firewall proof"}))


if __name__ == "__main__":
    main()
