import os
import json
import subprocess
import socket
from ipaddress import ip_network, ip_address
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.secret_key = 'supersecretkey123'
CONFIG_FILE = 'router_config.json'

def init_config_file():
    if not os.path.exists(CONFIG_FILE) or os.path.getsize(CONFIG_FILE) == 0:
        with open(CONFIG_FILE, 'w') as f:
            json.dump({'addresses': [], 'routes': []}, f, indent=4)

def load_config():
    try:
        init_config_file()
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            if 'addresses' not in config or 'routes' not in config:
                config = {'addresses': [], 'routes': []}
                save_config(config)
            return config
    except json.JSONDecodeError:
        init_config_file()
        return {'addresses': [], 'routes': []}

def save_config(config):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        flash(f'Error saving config: {str(e)}', 'error')

@app.route('/')
def index():
    config = load_config()
    interfaces = ['Ethernet0', 'Ethernet1', 'Ethernet2', 'Ethernet3', 'Ethernet4']
    return render_template('index.html', addresses=config['addresses'], routes=config['routes'], interfaces=interfaces)

@app.route('/add_address', methods=['POST'])
def add_address():
    config = load_config()
    address = request.form['address'].strip()  # Expecting CIDR format, e.g., "192.168.1.10/24"
    interface = request.form['interface']

    # Check if the interface already has an IP address assigned
    for addr in config['addresses']:
        if addr['interface'] == interface:
            flash(f'Interface {interface} already has an IP address assigned.', 'error')
            return redirect(url_for('index'))

    try:
        # Parse CIDR address
        ip_net = ip_network(address, strict=False)
        raw_ip = address.split('/')[0]
        subnet = f"{ip_net.network_address}/{ip_net.prefixlen}"

        # Check if the subnet is already used by another interface
        for addr in config['addresses']:
            existing_subnet = addr.get('subnet')
            if not existing_subnet:
                existing_ip_net = ip_network(addr['address'], strict=False)
                existing_subnet = f"{existing_ip_net.network_address}/{existing_ip_net.prefixlen}"
            if subnet == existing_subnet:
                flash(f'Subnet {subnet} is already assigned to interface {addr["interface"]}.', 'error')
                return redirect(url_for('index'))

        # Check for existing network
        existing_network = None
        result = subprocess.run(['docker', 'network', 'ls', '--format', '{{.Name}}'],
                               capture_output=True, text=True, check=True)
        network_names = result.stdout.strip().split('\n')

        for name in network_names:
            inspect = subprocess.run(['docker', 'network', 'inspect', name],
                                    capture_output=True, text=True)
            if inspect.returncode != 0:
                continue
            if subnet in inspect.stdout:
                existing_network = name
                break

        network_name = existing_network or f'net_{str(ip_net.network_address).replace(".", "_")}_{ip_net.prefixlen}'

        # Check if the IP is already in use
        if existing_network:
            inspect = subprocess.run(['docker', 'network', 'inspect', existing_network],
                                    capture_output=True, text=True)
            if inspect.returncode == 0 and raw_ip in inspect.stdout:
                flash(f'IP address {raw_ip} is already in use on Docker network {existing_network}', 'error')
                return redirect(url_for('index'))

        if not existing_network:
            subprocess.run(["docker", "network", "create", "--subnet", subnet, network_name], check=True)

        container_name = socket.gethostname()

        subprocess.run(["docker", "network", "disconnect", network_name, container_name], check=False)

        subprocess.run(["docker", "network", "connect", "--ip", raw_ip, network_name, container_name], check=True)

        config['addresses'].append({
            'address': address,
            'interface': interface,
            'subnet': subnet
        })
        save_config(config)

        flash(f"Interface {interface} configured with {address} via Docker network {network_name}!", 'success')

    except ValueError as e:
        flash(f'Invalid CIDR address format: {str(e)}', 'error')
    except subprocess.CalledProcessError as e:
        flash(f'Docker error: {e.stderr}', 'error')
    except Exception as e:
        flash(f'Unexpected error: {str(e)}', 'error')

    return redirect(url_for('index'))

@app.route('/delete_address/<int:index>')
def delete_address(index):
    config = load_config()
    if 0 <= index < len(config['addresses']):
        removed = config['addresses'].pop(index)
        save_config(config)

        # Docker cleanup
        try:
            ip_address_input = removed['address']
            raw_ip = ip_address_input.split('/')[0]
            # Use stored subnet if available, otherwise compute from address
            subnet = removed.get('subnet')
            if not subnet:
                ip_net = ip_network(ip_address_input, strict=False)
                subnet = f"{ip_net.network_address}/{ip_net.prefixlen}"
            
            container_name = socket.gethostname()
            network_to_disconnect = None

            result = subprocess.run(['docker', 'network', 'ls', '--format', '{{.Name}}'],
                                   capture_output=True, text=True, check=True)
            for name in result.stdout.strip().split('\n'):
                inspect = subprocess.run(['docker', 'network', 'inspect', name],
                                        capture_output=True, text=True)
                if inspect.returncode != 0:
                    continue
                if subnet in inspect.stdout:
                    network_to_disconnect = name
                    break

            if network_to_disconnect:
                subprocess.run([
                    "docker", "network", "disconnect",
                    network_to_disconnect,
                    container_name
                ], check=False)

            flash('Address deleted successfully!', 'success')
        except Exception as e:
            flash(f'Failed to disconnect Docker network: {e}', 'error')
    else:
        flash('Invalid address index!', 'error')
    return redirect(url_for('index'))

@app.route('/edit_address/<int:index>', methods=['POST'])
def edit_address(index):
    config = load_config()
    if not (0 <= index < len(config['addresses'])):
        flash('Invalid address index!', 'error')
        return redirect(url_for('index'))

    old_entry = config['addresses'][index]
    new_address = request.form['address'].strip()  # Expecting CIDR format, e.g., "192.168.2.10/24"
    new_interface = request.form['interface']

    # Check if the new interface already has an IP address assigned (excluding the current entry)
    for i, addr in enumerate(config['addresses']):
        if i != index and addr['interface'] == new_interface:
            flash(f'Interface {new_interface} already has an IP address assigned.', 'error')
            return redirect(url_for('index'))

    try:
        # Parse new CIDR address
        ip_net = ip_network(new_address, strict=False)
        new_ip = new_address.split('/')[0]
        new_subnet = f"{ip_net.network_address}/{ip_net.prefixlen}"

        # Check if the new subnet is already used by another interface (excluding the current entry)
        for i, addr in enumerate(config['addresses']):
            if i != index:
                existing_subnet = addr.get('subnet')
                if not existing_subnet:
                    existing_ip_net = ip_network(addr['address'], strict=False)
                    existing_subnet = f"{existing_ip_net.network_address}/{existing_ip_net.prefixlen}"
                if new_subnet == existing_subnet:
                    flash(f'Subnet {new_subnet} is already assigned to interface {addr["interface"]}.', 'error')
                    return redirect(url_for('index'))

        # Update config
        config['addresses'][index] = {
            'address': new_address,
            'interface': new_interface,
            'subnet': new_subnet
        }
        save_config(config)

        container_name = socket.gethostname()

        # Disconnect from old Docker network and delete if unused
        old_ip = old_entry['address'].split('/')[0]
        old_subnet = old_entry.get('subnet')
        if not old_subnet:
            old_ip_net = ip_network(old_entry['address'], strict=False)
            old_subnet = f"{old_ip_net.network_address}/{old_ip_net.prefixlen}"

        old_network = None
        result = subprocess.run(['docker', 'network', 'ls', '--format', '{{.Name}}'], 
                               capture_output=True, text=True, check=True)
        network_names = result.stdout.strip().split('\n')
        for name in network_names:
            inspect = subprocess.run(['docker', 'network', 'inspect', name], 
                                   capture_output=True, text=True, check=False)
            if inspect.returncode == 0 and old_subnet in inspect.stdout:
                old_network = name
                break

        if old_network:
            # Disconnect the container from the old network
            disconnect_result = subprocess.run(['docker', 'network', 'disconnect', old_network, container_name], 
                                              capture_output=True, text=True, check=False)
            if disconnect_result.returncode != 0 and "is not connected" not in disconnect_result.stderr:
                flash(f'Failed to disconnect from old network {old_network}: {disconnect_result.stderr}', 'error')
                return redirect(url_for('index'))

            # Check if the old network is used by other containers
            inspect = subprocess.run(['docker', 'network', 'inspect', old_network], 
                                    capture_output=True, text=True, check=False)
            if inspect.returncode == 0:
                network_data = json.loads(inspect.stdout)
                containers = network_data[0].get('Containers', {})
                if not containers:  # No containers are connected after disconnection
                    rm_result = subprocess.run(['docker', 'network', 'rm', old_network], 
                                             capture_output=True, text=True, check=False)
                    if rm_result.returncode != 0:
                        flash(f'Failed to delete old network {old_network}: {rm_result.stderr}', 'error')

        # Connect to new Docker network
        existing_network = None
        for name in network_names:
            inspect = subprocess.run(['docker', 'network', 'inspect', name], 
                                   capture_output=True, text=True, check=False)
            if inspect.returncode == 0 and new_subnet in inspect.stdout:
                existing_network = name
                break

        network_name = existing_network or f'net_{str(ip_net.network_address).replace(".", "_")}_{ip_net.prefixlen}'

        if not existing_network:
            create_result = subprocess.run([
                "docker", "network", "create",
                "--subnet", new_subnet,
                network_name
            ], capture_output=True, text=True, check=True)
            if create_result.returncode != 0:
                flash(f'Failed to create network {network_name}: {create_result.stderr}', 'error')
                return redirect(url_for('index'))

        # Check if the new IP is already in use
        inspect = subprocess.run(['docker', 'network', 'inspect', network_name], 
                                capture_output=True, text=True, check=True)
        network_data = json.loads(inspect.stdout)
        for container in network_data[0].get('Containers', {}).values():
            if container.get('IPv4Address', '').startswith(f"{new_ip}/"):
                flash(f'IP address {new_ip} is already in use on Docker network {network_name}', 'error')
                return redirect(url_for('index'))

        # Connect with the desired IP
        connect_result = subprocess.run([
            "docker", "network", "connect",
            "--ip", new_ip,
            network_name,
            container_name
        ], capture_output=True, text=True, check=True)
        if connect_result.returncode != 0:
            flash(f'Failed to connect to network {network_name}: {connect_result.stderr}', 'error')
            return redirect(url_for('index'))

        flash('Address updated and Docker network updated successfully!', 'success')

    except ValueError as e:
        flash(f'Invalid CIDR address format: {str(e)}', 'error')
    except subprocess.CalledProcessError as e:
        flash(f'Docker error while editing interface: {e.stderr or str(e)}', 'error')
    except Exception as e:
        flash(f'Unexpected error: {str(e)}', 'error')

    return redirect(url_for('index'))

@app.route('/add_route', methods=['POST'])
def add_route():
    config = load_config()
    destination = request.form['destination'].strip()  # Expecting CIDR format, e.g., "10.0.0.0/8"
    next_hop = request.form['next_hop'].strip()

    # Validate destination is in CIDR format
    try:
        ip_network(destination, strict=False)
    except ValueError as e:
        flash(f'Invalid destination CIDR format: {str(e)}', 'error')
        return redirect(url_for('index'))

    # Validate next_hop against interface subnets
    try:
        matched = False
        for addr in config['addresses']:
            subnet = addr.get('subnet')
            if not subnet:
                ip_net = ip_network(addr['address'], strict=False)
                subnet = f"{ip_net.network_address}/{ip_net.prefixlen}"
            if ip_address(next_hop) in ip_network(subnet, strict=False):
                matched = True
                break
        if not matched:
            flash('Next hop must be reachable via one of the router interfaces.', 'error')
            return redirect(url_for('index'))

    except ValueError as e:
        flash(f'Invalid next hop address: {str(e)}', 'error')
        return redirect(url_for('index'))

    config['routes'].append({'destination': destination, 'next_hop': next_hop})
    save_config(config)

    try:
        container_name = socket.gethostname()
        subprocess.run([
            "docker", "exec", container_name,
            "ip", "route", "add", destination, "via", next_hop
        ], check=True)
        flash('Static route added and applied successfully!', 'success')
    except subprocess.CalledProcessError as e:
        flash(f"Failed to apply route: {e.stderr}", 'error')

    return redirect(url_for('index'))

@app.route('/delete_route/<int:index>')
def delete_route(index):
    config = load_config()
    if 0 <= index < len(config['routes']):
        route_to_delete = config['routes'][index]
        destination = route_to_delete['destination']
        config['routes'].pop(index)
        save_config(config)

        try:
            container_name = socket.gethostname()
            subprocess.run([
                "docker", "exec", container_name,
                "ip", "route", "del", destination
            ], check=True)
            flash('Route deleted from container and config.', 'success')
        except subprocess.CalledProcessError as e:
            flash(f'Route deleted from config, but failed to delete from container: {e.stderr}', 'error')
    else:
        flash('Invalid route index!', 'error')
    return redirect(url_for('index'))

@app.route('/edit_route/<int:index>', methods=['POST'])
def edit_route(index):
    config = load_config()
    if not (0 <= index < len(config['routes'])):
        flash('Invalid route index!', 'error')
        return redirect(url_for('index'))

    old_route = config['routes'][index]
    old_destination = old_route['destination']

    new_destination = request.form['destination'].strip()  # Expecting CIDR format
    new_next_hop = request.form['next_hop'].strip()

    # Validate new destination is in CIDR format
    try:
        ip_network(new_destination, strict=False)
    except ValueError as e:
        flash(f'Invalid destination CIDR format: {str(e)}', 'error')
        return redirect(url_for('index'))

    # Validate new next_hop
    try:
        matched = False
        for addr in config['addresses']:
            subnet = addr.get('subnet')
            if not subnet:
                ip_net = ip_network(addr['address'], strict=False)
                subnet = f"{ip_net.network_address}/{ip_net.prefixlen}"
            if ip_address(new_next_hop) in ip_network(subnet, strict=False):
                matched = True
                break
        if not matched:
            flash('Next hop must be reachable via one of the router interfaces.', 'error')
            return redirect(url_for('index'))
    except ValueError as e:
        flash(f'Invalid next hop address: {e}', 'error')
        return redirect(url_for('index'))

    config['routes'][index] = {
        'destination': new_destination,
        'next_hop': new_next_hop
    }
    save_config(config)

    try:
        container_name = socket.gethostname()
        subprocess.run([
            "docker", "exec", container_name,
            "ip", "route", "del", old_destination
        ], check=False)
        subprocess.run([
            "docker", "exec", container_name,
            "ip", "route", "add", new_destination, "via", new_next_hop
        ], check=True)
        flash('Route updated in config and container successfully.', 'success')
    except subprocess.CalledProcessError as e:
        flash(f'Route updated in config, but failed to apply in container: {e.stderr}', 'error')

    return redirect(url_for('index'))

if __name__ == '__main__':
    init_config_file()
    app.run(host='0.0.0.0', port=5002)