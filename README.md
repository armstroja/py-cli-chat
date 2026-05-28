netmsg.py — a pure-Python, zero-dependency LAN messenger. Here's how to use it:

Running it
bash# Basic — uses your hostname and port 55000
python3 netmsg.py

# Custom name and port
python3 netmsg.py --name Alice --port 55000
Run it on every machine that wants to participate. They all need to use the same port.

Sending messages
Once running, just type an IP and your message:
> 192.168.1.42 Hey, are you there?
Or use the explicit command:
> /send 192.168.1.42 Hello from Alice!

Other commands
CommandWhat it does/historyPrint full message log/clearClear the screen/quitExit

How it works

Each instance listens on a TCP port (default 55000) in a background thread for incoming connections.
When you send, it opens a short-lived TCP connection to the target IP, sends a JSON payload {"name": "...", "text": "..."}, and closes it.
No server, no internet, no dependencies beyond Python 3.9+. Works entirely on your local network.


Firewall note: If messages don't arrive, make sure port 55000 (or your chosen port) is allowed through the firewall on the receiving machine. On Linux: sudo ufw allow 55000/tcp
