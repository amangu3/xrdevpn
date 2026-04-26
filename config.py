#!/usr/bin/env python3
"""
Interactive EVPN Config Generator
Supports: Single-Home and Multi-Home EVPN config generation
Output: Prints config to screen + saves to file
"""

import random
import re
import os

# ─── Helpers ──────────────────────────────────────────────────────────────────

def generate_random_mac_cisco():
    r = [random.randint(0, 255) for _ in range(6)]
    return f"{r[0]:02x}{r[1]:02x}.{r[2]:02x}{r[3]:02x}.{r[4]:02x}{r[5]:02x}"

def normalize_mac_to_cisco(mac_input):
    clean = re.sub(r'[:\-\.]', '', mac_input).lower()
    if len(clean) != 12:
        raise ValueError(f"Invalid MAC address: {mac_input}")
    return f"{clean[0:4]}.{clean[4:8]}.{clean[8:12]}"

def mac_to_esi(mac_input):
    clean = re.sub(r'[:\-\.]', '', mac_input).lower()
    if len(clean) != 12:
        raise ValueError(f"Invalid MAC: {mac_input}")
    b = [clean[i:i+2] for i in range(0, 12, 2)]
    return f"00.{b[0]}.{b[1]}.{b[2]}.{b[3]}.{b[4]}.{b[5]}.00.00.00"

def ask(prompt, default=None):
    if default:
        val = input(f"  {prompt} [{default}]: ").strip()
        return val if val else default
    else:
        while True:
            val = input(f"  {prompt}: ").strip()
            if val:
                return val

def ask_yes_no(prompt):
    while True:
        val = input(f"  {prompt} (yes/no): ").strip().lower()
        if val in ('yes', 'y'):
            return True
        elif val in ('no', 'n'):
            return False

def ask_interfaces(label):
    interfaces = []
    print(f"\n    Enter interfaces for {label} (empty line to stop):")
    while True:
        iface = input(f"      Interface: ").strip()
        if not iface:
            if not interfaces:
                print("      At least one interface required!")
                continue
            break
        interfaces.append(iface)
    return interfaces

def ask_mac(prompt):
    while True:
        raw = input(f"  {prompt} (e.g. aac1.abc9.e5a2): ").strip()
        try:
            return normalize_mac_to_cisco(raw)
        except ValueError:
            print("  Invalid MAC format. Try again.")

def ask_choice(prompt, options):
    print(f"\n  {prompt}")
    for i, opt in enumerate(options, 1):
        print(f"    {i}. {opt}")
    while True:
        val = input(f"  Enter choice (1-{len(options)}): ").strip()
        if val.isdigit() and 1 <= int(val) <= len(options):
            return val
        print(f"  Invalid. Enter 1 to {len(options)}.")

def print_header(title):
    print("\n" + "="*60)
    print(f"  {title}")
    print("="*60)

def save_config(filename, content):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    filepath   = os.path.join(script_dir, filename)
    with open(filepath, 'w') as f:
        f.write(content)
    print(f"  [OK] Config saved to: {filepath}")


# ─── Load Balancing Mode ──────────────────────────────────────────────────────

def ask_load_balancing_mode():
    choice = ask_choice(
        "Select load-balancing mode:",
        [
            "all-active (default, no extra config)",
            "port-active",
            "single-active",
        ]
    )

    lb_line  = ""
    sc_lines = ""

    if choice == '1':
        pass  # all-active default, nothing to add

    elif choice == '2':
        lb_line = "   load-balancing-mode port-active"
        configure_sc = ask_yes_no("\n  Do you want to configure service-carving?")
        if configure_sc:
            sc_choice = ask_choice("Select service-carving type:", ["manual", "preference-based"])
            if sc_choice == '1':
                primary   = ask("Enter primary EVI range (e.g. 1-100)")
                secondary = ask("Enter secondary EVI range (e.g. 101-200)")
                sc_lines  = f"   service-carving manual\n    primary {primary} secondary {secondary}"
            elif sc_choice == '2':
                weight   = ask("Enter weight (1-100, higher = more preferred)")
                sc_lines = f"   service-carving preference-based\n    weight {weight}"

    elif choice == '3':
        lb_line = "   load-balancing-mode single-active"
        configure_sc = ask_yes_no("\n  Do you want to configure service-carving?")
        if configure_sc:
            primary   = ask("Enter primary VLAN/EVI range (e.g. 10)")
            secondary = ask("Enter secondary VLAN/EVI range (e.g. 20)")
            sc_lines  = f"   service-carving manual\n    primary {primary} secondary {secondary}"

    return lb_line, sc_lines


# ─── Subinterface + L2 Service ────────────────────────────────────────────────

def ask_subinterface(node_name, evi, is_second_node=False, sub1_name=None, vlan_tag=None):
    """
    Ask subinterface details for a node.
    For node2 in MH: subinterface name may differ but vlan/rewrite stays same.
    Returns (subif_name, vlan_tag, config_lines)
    """
    print(f"\n  -- Subinterface for {node_name} --")

    if is_second_node:
        sub_name = ask(f"Enter subinterface name for {node_name} (e.g. Bundle-Ether200.10)")
        # vlan and rewrite same as node1
        v = vlan_tag
    else:
        sub_name = ask(f"Enter subinterface name for {node_name} (e.g. Bundle-Ether100.10)")
        v        = ask("Enter VLAN tag (e.g. 10)")

    cfg  = f"!\ninterface {sub_name} l2transport\n"
    cfg += f" encapsulation dot1q {v}\n"
    cfg += f" rewrite ingress tag pop 1 symmetric\n"
    cfg += f"!\n"

    return sub_name, v, cfg


def ask_l2_service(evi, sub_name_node1, sub_name_node2=None, bundle_iface=None, is_mh=False):
    """
    Ask xconnect or bridge-domain config.
    Returns (config_node1, config_node2)
    """
    choice = ask_choice(
        "Select L2 service type:",
        ["xconnect (VPWS)", "bridge-domain"]
    )

    cfg1 = ""
    cfg2 = ""

    if choice == '1':
        # xconnect
        xc_group = ask("Enter xconnect group name (e.g. VPWS)")
        p2p_name = ask("Enter p2p name (e.g. 10)")

        def xc_config(sub_name):
            c  = f"!\nl2vpn\n"
            c += f" xc group {xc_group}\n"
            c += f"  p2p {p2p_name}\n"
            c += f"   interface {sub_name}\n"
            c += f"   neighbor evpn evi {evi} service {evi}\n"
            c += f"  !\n !\n!\n"
            return c

        cfg1 = xc_config(sub_name_node1)
        if is_mh and sub_name_node2:
            cfg2 = xc_config(sub_name_node2)

    elif choice == '2':
        # bridge-domain
        bd_group  = ask("Enter bridge-domain group name (e.g. 100)")
        bd_domain = ask("Enter bridge-domain name (e.g. 100)")

        def bd_config(sub_name):
            c  = f"!\nl2vpn\n"
            c += f" bridge group {bd_group}\n"
            c += f"  bridge-domain {bd_domain}\n"
            c += f"   interface {sub_name}\n"
            c += f"   !\n"
            c += f"   evi {evi}\n"
            c += f"   !\n"
            c += f"  !\n !\n!\n"
            return c

        cfg1 = bd_config(sub_name_node1)
        if is_mh and sub_name_node2:
            cfg2 = bd_config(sub_name_node2)

    return cfg1, cfg2


# ─── Single Home ──────────────────────────────────────────────────────────────

def single_home(site_num):
    print_header(f"Single-Home - Site {site_num}")

    node         = ask("Enter node name (e.g. R36)")
    evi          = ask("Enter EVI / VPN-ID (e.g. 100)")
    bundle_iface = ask("Enter access interface (e.g. Bundle-Ether100)")

    core_iso    = ask_yes_no("\n  Do you want core-isolation?")
    group_no    = None
    core_ifaces = []
    if core_iso:
        group_no    = ask("Enter core-isolation group number (e.g. 1)")
        core_ifaces = ask_interfaces("core-facing interfaces")

    # EVPN block
    config  = f"!\n! --- EVPN Config for {node} (Single-Home, Site {site_num}) ---\n!\n"
    config += f"evpn\n evi {evi}\n  advertise-mac\n !\n"

    if core_iso:
        config += f" group {group_no}\n"
        for iface in core_ifaces:
            config += f"  core interface {iface}\n"
        config += " !\n"

    config += f" interface {bundle_iface}\n"
    config += f"  ethernet-segment\n"
    config += f"   type 1 auto-generation-disable\n"
    config += f"  !\n"
    if core_iso:
        config += f"  core-isolation-group {group_no}\n"
    config += " !\n!\n"

    # Subinterface
    sub_name, vlan_tag, sub_cfg = ask_subinterface(node, evi)
    config += sub_cfg

    # L2 service
    l2_cfg, _ = ask_l2_service(evi, sub_name, bundle_iface=bundle_iface, is_mh=False)
    config += l2_cfg

    print_header(f"Config - {node}")
    print(config)
    save_config(f"evpn_sh_{node.lower()}_evi{evi}_site{site_num}.txt", config)


# ─── Multi Home ───────────────────────────────────────────────────────────────

def multi_home(site_num):
    print_header(f"Multi-Home - Site {site_num}")

    node1 = ask("Enter Node 1 name (e.g. R36)")
    node2 = ask("Enter Node 2 name (e.g. R37)")
    evi   = ask("Enter EVI / VPN-ID (e.g. 100)")

    ifaces_node1 = ask_interfaces(f"{node1} physical interfaces")
    ifaces_node2 = ask_interfaces(f"{node2} physical interfaces")

    bundle_iface1    = ask(f"\n  Enter Bundle interface name for {node1} (e.g. Bundle-Ether100)")
    bundle_iface2    = ask(f"  Enter Bundle interface name for {node2} (e.g. Bundle-Ether100)")
    bundle_id_match1 = re.search(r'(\d+)$', bundle_iface1)
    bundle_id_match2 = re.search(r'(\d+)$', bundle_iface2)
    bundle_id1       = bundle_id_match1.group(1) if bundle_id_match1 else evi
    bundle_id2       = bundle_id_match2.group(1) if bundle_id_match2 else evi

    # LACP MAC
    print("\n  -- LACP System MAC --")
    lacp_known = ask_yes_no("  Do you know the LACP common system MAC?")
    if lacp_known:
        lacp_mac = ask_mac("Enter LACP system MAC")
    else:
        use_iface_mac = ask_yes_no("  Use interface MAC as base?")
        if use_iface_mac:
            lacp_mac = ask_mac("Enter interface MAC")
        else:
            lacp_mac = generate_random_mac_cisco()
            print(f"  [OK] Generated LACP system MAC: {lacp_mac}")

    # ESI
    print("\n  -- Ethernet Segment Identifier (ESI) --")
    esi_known = ask_yes_no("  Do you know the ESI (type 0)?")
    if esi_known:
        esi = ask("Enter ESI (e.g. 36.37.00.00.00.00.00.11.00)")
    else:
        use_iface_mac_esi = ask_yes_no("  Derive ESI from interface MAC?")
        if use_iface_mac_esi:
            base_mac = ask_mac("Enter interface MAC for ESI derivation")
            esi = mac_to_esi(base_mac)
        else:
            rand_mac = generate_random_mac_cisco()
            esi = mac_to_esi(rand_mac)
        print(f"  [OK] ESI: {esi}")

    # Load Balancing Mode
    print("\n  -- Load Balancing Mode --")
    lb_line, sc_lines = ask_load_balancing_mode()

    # Core Isolation
    print("\n  -- Core Isolation --")
    core_iso      = ask_yes_no("  Do you want core-isolation?")
    group_no      = None
    core_ifaces_1 = []
    core_ifaces_2 = []
    if core_iso:
        group_no      = ask("Enter core-isolation group number (e.g. 1)")
        core_ifaces_1 = ask_interfaces(f"{node1} core-facing")
        core_ifaces_2 = ask_interfaces(f"{node2} core-facing")

    # Subinterfaces
    sub_name1, vlan_tag, sub_cfg1 = ask_subinterface(node1, evi)
    sub_name2, _,        sub_cfg2 = ask_subinterface(node2, evi,
                                                      is_second_node=True,
                                                      sub1_name=sub_name1,
                                                      vlan_tag=vlan_tag)

    # L2 service (ask once, apply to both)
    l2_cfg1, l2_cfg2 = ask_l2_service(
        evi,
        sub_name1,
        sub_name_node2=sub_name2,
        bundle_iface=bundle_iface1,
        is_mh=True
    )

    # ── Build full config per node ──
    def build_evpn_block(node_name, phys_ifaces, core_ifaces, bundle_iface, bundle_id):
        cfg  = f"!\n! --- EVPN Config for {node_name} (Multi-Home, Site {site_num}) ---\n!\n"
        cfg += f"evpn\n evi {evi}\n  advertise-mac\n !\n"

        if core_iso:
            cfg += f" group {group_no}\n"
            for iface in core_ifaces:
                cfg += f"  core interface {iface}\n"
            cfg += " !\n"

        cfg += f" interface {bundle_iface}\n"
        cfg += f"  ethernet-segment\n"
        cfg += f"   identifier type 0 {esi}\n"
        if lb_line:
            cfg += f"{lb_line}\n"
        if sc_lines:
            for line in sc_lines.splitlines():
                cfg += f"{line}\n"
        cfg += f"  !\n"
        if core_iso:
            cfg += f"  core-isolation-group {group_no}\n"
        cfg += " !\n!\n"

        # Bundle interface with LACP system mac
        cfg += f"!\ninterface {bundle_iface}\n"
        cfg += f" lacp system mac {lacp_mac}\n!\n"

        # Physical interfaces -> bundle
        for iface in phys_ifaces:
            cfg += f"!\ninterface {iface}\n"
            cfg += f" bundle id {bundle_id} mode active\n!\n"

        return cfg

    config1  = build_evpn_block(node1, ifaces_node1, core_ifaces_1, bundle_iface1, bundle_id1)
    config1 += sub_cfg1
    config1 += l2_cfg1

    config2  = build_evpn_block(node2, ifaces_node2, core_ifaces_2, bundle_iface2, bundle_id2)
    config2 += sub_cfg2
    config2 += l2_cfg2

    print_header(f"Config - {node1}")
    print(config1)
    print_header(f"Config - {node2}")
    print(config2)

    save_config(f"evpn_mh_{node1.lower()}_evi{evi}_site{site_num}.txt", config1)
    save_config(f"evpn_mh_{node2.lower()}_evi{evi}_site{site_num}.txt", config2)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print_header("EVPN Config Generator")

    num_sites = int(ask("How many sites do you want to configure?"))

    for site in range(1, num_sites + 1):
        print(f"\n{'-'*60}")
        print(f"  SITE {site} of {num_sites}")
        print(f"{'-'*60}")

        choice = ask_choice("Select setup type:", ["Single-Home", "Multi-Home"])

        if choice == '1':
            single_home(site)
        elif choice == '2':
            multi_home(site)

    print_header("All sites configured!")


if __name__ == "__main__":
    main()