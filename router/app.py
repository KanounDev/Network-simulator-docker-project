import os
import json
import subprocess
import socket
from ipaddress import ip_network, ip_address
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = 'supersecretkey123'

CONFIG_FILE = 'router_config.json'

def init_config_file():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'w') as f:
            json.dump({'addresses': [], 'routes': []}, f, indent=4)

def load_config():
    init_config_file()
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

@app.route('/')
def index():
    config = load_config()
    interfaces = ['Ethernet0', 'Ethernet1', 'Ethernet2', 'Ethernet3', 'Ethernet4']
    return render_template('index.html', addresses=config['addresses'], routes=config['routes'], interfaces=interfaces)

@app.route('/add_address', methods=['POST'])
def add_address():
    config = load_config()
    address = request.form['address'].strip()
    interface = request.form['interface']

    raw_ip = address.split('/')[0]
    subnet = '.'.join(raw_ip.split('.')[:3]) + '.0/24'

    try:
        # Step 1: Check for existing network
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

        network_name = existing_network or f'net_{interface.lower()}'

        # Step 2: Check if the IP is already in use
        if existing_network:
            inspect = subprocess.run(['docker', 'network', 'inspect', existing_network],
                                     capture_output=True, text=True)
            if inspect.returncode == 0 and raw_ip in inspect.stdout:
                flash(f'IP address {raw_ip} is already in use on Docker network {existing_network}', 'error')
                return redirect('/')

        if not existing_network:
            subprocess.run(["docker", "network", "create", "--subnet", subnet, network_name], check=True)

        container_name = socket.gethostname()

        subprocess.run(["docker", "network", "disconnect", network_name, container_name], check=False)

        subprocess.run(["docker", "network", "connect", "--ip", raw_ip, network_name, container_name], check=True)

        config['addresses'].append({
            'address': address,
            'interface': interface
        })
        save_config(config)

        flash(f"Interface {interface} configured via Docker network {network_name}!", 'success')

    except subprocess.CalledProcessError as e:
        flash(f"Docker error: {e}", 'error')
    except Exception as ex:
        flash(f'Unexpected error: {str(ex)}', 'error')

    return redirect('/')

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
            subnet = '.'.join(raw_ip.split('.')[:3]) + '.0/24'
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

        except Exception as e:
            flash(f'Failed to disconnect Docker network: {e}', 'error')

        flash('Address deleted successfully!', 'success')
    else:
        flash('Invalid address index!', 'error')
    return redirect('/')

@app.route('/edit_address/<int:index>', methods=['POST'])
def edit_address(index):
    config = load_config()
    if not (0 <= index < len(config['addresses'])):
        flash('Invalid address index!', 'error')
        return redirect('/')

    old_entry = config['addresses'][index]
    new_entry = {
        'address': request.form['address'].strip(),
        'interface': request.form['interface']
    }

    # Update config first
    config['addresses'][index] = new_entry
    save_config(config)

    try:
        container_name = socket.gethostname()

        # OLD subnet
        old_ip = old_entry['address'].split('/')[0]
        old_subnet = '.'.join(old_ip.split('.')[:3]) + '.0/24'

        # NEW subnet
        new_ip = new_entry['address'].split('/')[0]
        new_subnet = '.'.join(new_ip.split('.')[:3]) + '.0/24'

        # Disconnect from old Docker network
        old_network = None
        result = subprocess.run(['docker', 'network', 'ls', '--format', '{{.Name}}'], capture_output=True, text=True, check=True)
        for name in result.stdout.strip().split('\n'):
            inspect = subprocess.run(['docker', 'network', 'inspect', name], capture_output=True, text=True)
            if old_subnet in inspect.stdout:
                old_network = name
                break
        if old_network:
            subprocess.run(["docker", "network", "disconnect", old_network, container_name], check=False)

        # Reconnect to new Docker network
        existing_network = None
        for name in result.stdout.strip().split('\n'):
            inspect = subprocess.run(['docker', 'network', 'inspect', name], capture_output=True, text=True)
            if new_subnet in inspect.stdout:
                existing_network = name
                break

        network_name = existing_network or f'net_{new_entry["interface"].lower()}'

        if not existing_network:
            subprocess.run([
                "docker", "network", "create",
                "--subnet", new_subnet,
                network_name
            ], check=True)

        subprocess.run([
            "docker", "network", "connect",
            "--ip", new_ip,
            network_name,
            container_name
        ], check=True)

        flash('Address updated and Docker network updated successfully!', 'success')

    except subprocess.CalledProcessError as e:
        flash(f'Docker error while editing interface: {e}', 'error')
    except Exception as ex:
        flash(f'Unexpected error: {str(ex)}', 'error')

    return redirect('/')

@app.route('/add_route', methods=['POST'])
def add_route():
    config = load_config()
    destination = request.form['destination'].strip()
    next_hop = request.form['next_hop'].strip()

    # Validate gateway matches one of the subnets
    try:
        matched = False
        for addr in config['addresses']:
            subnet = '.'.join(addr['address'].split('/')[0].split('.')[:3]) + '.0/24'
            if ip_address(next_hop) in ip_network(subnet, strict=False):
                matched = True
                break
        if not matched:
            flash('Next hop must be reachable via one of the router interfaces.', 'error')
            return redirect('/')

    except Exception as e:
        flash(f'Invalid next hop address: {e}', 'error')
        return redirect('/')

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
        flash(f"Failed to apply route: {e}", 'error')

    return redirect('/')

@app.route('/delete_route/<int:index>')
def delete_route(index):
    config = load_config()
    if 0 <= index < len(config['routes']):
        # Get route to delete before removing
        route_to_delete = config['routes'][index]
        destination = route_to_delete['destination']
        next_hop = route_to_delete['next_hop']

        # Remove from config
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
            flash(f'Route deleted from config, but failed to delete from container: {e}', 'error')
    else:
        flash('Invalid route index!', 'error')
    return redirect('/')


@app.route('/edit_route/<int:index>', methods=['POST'])
def edit_route(index):
    config = load_config()
    if not (0 <= index < len(config['routes'])):
        flash('Invalid route index!', 'error')
        return redirect('/')

    old_route = config['routes'][index]
    old_destination = old_route['destination']

    new_destination = request.form['destination'].strip()
    new_next_hop = request.form['next_hop'].strip()

    # Validate new next hop is in a known subnet
    try:
        matched = False
        for addr in config['addresses']:
            subnet = '.'.join(addr['address'].split('/')[0].split('.')[:3]) + '.0/24'
            if ip_address(new_next_hop) in ip_network(subnet, strict=False):
                matched = True
                break
        if not matched:
            flash('Next hop must be reachable via one of the router interfaces.', 'error')
            return redirect('/')
    except Exception as e:
        flash(f'Invalid next hop address: {e}', 'error')
        return redirect('/')

    # Update the route in the config
    config['routes'][index] = {
        'destination': new_destination,
        'next_hop': new_next_hop
    }
    save_config(config)

    try:
        container_name = socket.gethostname()

        # Remove old route
        subprocess.run([
            "docker", "exec", container_name,
            "ip", "route", "del", old_destination
        ], check=False)

        # Add new route
        subprocess.run([
            "docker", "exec", container_name,
            "ip", "route", "add", new_destination, "via", new_next_hop
        ], check=True)

        flash('Route updated in config and container successfully.', 'success')
    except subprocess.CalledProcessError as e:
        flash(f'Route updated in config, but failed to apply in container: {e}', 'error')

    return redirect('/')

if __name__ == '__main__':
    init_config_file()
    app.run(host='0.0.0.0', port=5002)
