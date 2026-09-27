import socket
import urllib.request

import pytest


def test_sockets_are_blocked():
    with pytest.raises(RuntimeError):
        socket.create_connection(("example.com", 443))


def test_urlopen_is_blocked():
    with pytest.raises(RuntimeError):
        urllib.request.urlopen("https://example.com/")
