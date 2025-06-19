from scapy.all import *
import sys

iface = sys.argv[1]
server_ip = sys.argv[2]
offered_ip = sys.argv[3]

conf.iface = iface
server_mac = get_if_hwaddr(iface)

def handle_pkt(pkt):
    if DHCP in pkt and pkt[DHCP].options[0][1] == 1:
        print("📥 DHCP Discover received")
        ether = Ether(dst=pkt[Ether].src, src=server_mac)
        ip = IP(src=server_ip, dst="255.255.255.255")
        udp = UDP(sport=67, dport=68)
        bootp = BOOTP(op=2, yiaddr=offered_ip, siaddr=server_ip, chaddr=pkt[BOOTP].chaddr, xid=pkt[BOOTP].xid)
        dhcp = DHCP(options=[
            ("message-type", "offer"),
            ("server_id", server_ip),
            ("lease_time", 600),
            ("subnet_mask", "255.255.255.0"),
            "end"
        ])
        sendp(ether / ip / udp / bootp / dhcp, iface=iface, verbose=False)

    if DHCP in pkt and pkt[DHCP].options[0][1] == 3:
        print("📥 DHCP Request received")
        ether = Ether(dst=pkt[Ether].src, src=server_mac)
        ip = IP(src=server_ip, dst="255.255.255.255")
        udp = UDP(sport=67, dport=68)
        bootp = BOOTP(op=2, yiaddr=offered_ip, siaddr=server_ip, chaddr=pkt[BOOTP].chaddr, xid=pkt[BOOTP].xid)
        dhcp = DHCP(options=[
            ("message-type", "ack"),
            ("server_id", server_ip),
            ("lease_time", 600),
            ("subnet_mask", "255.255.255.0"),
            "end"
        ])
        sendp(ether / ip / udp / bootp / dhcp, iface=iface, verbose=False)

print("🚀 DHCP Server listening on", iface)
sniff(filter="udp and (port 67 or 68)", prn=handle_pkt, iface=iface, store=0, timeout=10)
