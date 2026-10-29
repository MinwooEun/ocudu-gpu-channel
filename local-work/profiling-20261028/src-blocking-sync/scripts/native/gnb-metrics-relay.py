#!/usr/bin/env python3
"""Relay the gNB remote-control WebSocket out of its network namespace.

The native gate runs the gNB under `unshare --net`, so the remote-control
server's 127.0.0.1:8001 lives on a loopback the dashboard cannot reach --
the two processes sit in different network namespaces and no veth joins
them. The ZMQ control and telemetry planes already cross that boundary by
using `ipc://` sockets in the shared run directory; this does the same for
the metrics WebSocket: it listens on an AF_UNIX socket in that directory
and forwards bytes verbatim to the in-namespace TCP port.

It is a byte pump, not a WebSocket implementation. The framing, the
handshake and the subscribe command all belong to the endpoints.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import signal
import socket
import sys
import threading

BUFFER_BYTES = 65536


def pump(source: socket.socket, sink: socket.socket) -> None:
    """Copy until either side closes, then half-close the sink."""

    try:
        while True:
            chunk = source.recv(BUFFER_BYTES)
            if not chunk:
                break
            sink.sendall(chunk)
    except OSError:
        pass
    finally:
        try:
            sink.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def serve_client(client: socket.socket, host: str, port: int) -> None:
    upstream: socket.socket | None = None
    try:
        upstream = socket.create_connection((host, port), timeout=5.0)
        upstream.settimeout(None)
        client.settimeout(None)
        outbound = threading.Thread(
            target=pump, args=(client, upstream), daemon=True
        )
        outbound.start()
        pump(upstream, client)
        outbound.join(timeout=5.0)
    except OSError:
        # The gNB may not have opened its port yet, or may have exited.
        # Dropping this connection is correct; the dashboard reconnects.
        pass
    finally:
        for sock in (client, upstream):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", type=pathlib.Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be in [1, 65535]")

    path = args.socket
    if path.exists() or path.is_symlink():
        # A previous run's socket file blocks bind(); the run directory is
        # per-timestamp so this only ever clears our own stale entry.
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)

    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(str(path))
    os.chmod(path, 0o660)
    listener.listen(8)

    stop = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()
        try:
            listener.close()
        except OSError:
            pass

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    print(
        f'{{"event":"gnb_metrics_relay_start","socket":"{path}",'
        f'"target":"{args.host}:{args.port}"}}',
        flush=True,
    )
    try:
        while not stop.is_set():
            try:
                client, _ = listener.accept()
            except OSError:
                break
            threading.Thread(
                target=serve_client,
                args=(client, args.host, args.port),
                daemon=True,
            ).start()
    finally:
        try:
            listener.close()
        except OSError:
            pass
        try:
            path.unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
