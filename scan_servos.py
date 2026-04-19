"""Scan servo IDs 1-10 and print which respond with their current positions."""

from scservo_sdk import PortHandler, PacketHandler, COMM_SUCCESS

PORT = "/dev/cu.usbmodem5A7C1172351"
BAUD = 1_000_000
ADDR_PRESENT_POSITION = 56

ph = PortHandler(PORT)
pkt = PacketHandler(0)

if not ph.openPort():
    raise SystemExit(f"Cannot open {PORT}")
if not ph.setBaudRate(BAUD):
    raise SystemExit(f"Cannot set baud {BAUD}")

print(f"Scanning IDs 1-10 on {PORT} at {BAUD} baud…\n")
found = {}
for sid in range(1, 11):
    pos, result, _ = pkt.read2ByteTxRx(ph, sid, ADDR_PRESENT_POSITION)
    if result == COMM_SUCCESS:
        found[sid] = pos
        print(f"  ID {sid:2d}: FOUND  — position {pos}")
    else:
        print(f"  ID {sid:2d}: no response")

print(f"\nResponding IDs: {list(found.keys())}")
ph.closePort()
