import os
import json
import subprocess
import socket
from ipaddress import ip_network, ip_address
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.secret_key = 'supersecretkey123'

CONFIG_FILE = 'host_config.json'

# Initialize JSON file if it doesn't exist or is invalid
def init_config_file():
    if not os.path.exists(CONFIG_FILE) or os.path.getsize(CONFIG_FILE) == 0:
        with open(CONFIG_FILE, 'w') as f:
            json.dump({'interface': {}}, f, indent=4)

# Load configuration from JSON file
def load_config():
    try:
        init_config_file()
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            if 'interface' not in config:
                config['interface'] = {}
                save_config(config)
            return config
    except json.JSONDecodeError:
        init_config_file()
        return {'interface': {}}

# Save configuration to JSON file
def save_config(config):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        flash(f'Error saving config: {str(e)}', 'error')

@app.route('/')
def index():
    config = load_config()
    return render_template('index.html', interface=config.get('interface', {}))

@app.route('/set_interface', methods=['POST'])
def set_interface():
    config = load_config()
    ip_address_input = request.form['ip_address'].strip()
    subnet_mask = request.form['subnet_mask'].strip()
    default_gateway = request.form['default_gateway'].strip()
    interface = 'eth0'

    try:
        # Convert subnet mask to CIDR prefix
        mask_parts = subnet_mask.split('.')
        if len(mask_parts) != 4 or not all(part.isdigit() and 0 <= int(part) <= 255 for part in mask_parts):
            flash('Invalid subnet mask format', 'error')
            return redirect(url_for('index'))
        mask_bits = sum(bin(int(part)).count('1') for part in mask_parts)
        raw_ip = ip_address_input.split('/')[0]
        # Use ip_network to get the correct network address
        net = ip_network(f"{raw_ip}/{mask_bits}", strict=False)
        subnet = f"{net.network_address}/{mask_bits}"

        # Validate IP and gateway in the subnet
        if ip_address(default_gateway) not in net:
            flash('Default gateway must be in the same subnet as the IP address', 'error')
            return redirect(url_for('index'))

        container_name = socket.gethostname()

        # Check if there is an existing configuration to clean up
        old_network = None
        if 'interface' in config and config['interface'].get('ip_address') and config['interface'].get('subnet_mask'):
            old_ip = config['interface']['ip_address'].split('/')[0]
            old_subnet_mask = config['interface']['subnet_mask']
            old_mask_parts = old_subnet_mask.split('.')
            old_mask_bits = sum(bin(int(part)).count('1') for part in old_mask_parts)
            old_net = ip_network(f"{old_ip}/{old_mask_bits}", strict=False)
            old_subnet = f"{old_net.network_address}/{old_mask_bits}"

            # Find the old Docker network
            result = subprocess.run(['docker', 'network', 'ls', '--format', '{{.Name}}'], 
                                   capture_output=True, text=True, check=True)
            network_names = result.stdout.strip().split('\n')
            for name in network_names:
                inspect = subprocess.run(['docker', 'network', 'inspect', name], 
                                       capture_output=True, text=True, check=True)
                if old_subnet in inspect.stdout:
                    old_network = name
                    break

            # Disconnect the container from the old network
            if old_network:
                disconnect_result = subprocess.run(['docker', 'network', 'disconnect', old_network, container_name], 
                                                 capture_output=True, text=True, check=False)
                if disconnect_result.returncode != 0 and "is not connected" not in disconnect_result.stderr:
                    flash(f'Failed to disconnect from old network {old_network}: {disconnect_result.stderr}', 'error')
                    return redirect(url_for('index'))

                # Check if the old network is used by other containers
                inspect = subprocess.run(['docker', 'network', 'inspect', old_network], 
                                       capture_output=True, text=True, check=True)
                network_data = json.loads(inspect.stdout)
                containers = network_data[0].get('Containers', {})
                if not containers:  # No containers are connected after disconnection
                    rm_result = subprocess.run(['docker', 'network', 'rm', old_network], 
                                             capture_output=True, text=True, check=True)
                    if rm_result.returncode != 0:
                        flash(f'Failed to delete old network {old_network}: {rm_result.stderr}', 'error')

        # Update configuration
        config['interface'] = {
            'ip_address': ip_address_input,
            'subnet_mask': subnet_mask,
            'default_gateway': default_gateway,
            'interface': interface
        }
        save_config(config)

        # Find or create new Docker network
        existing_network = None
        result = subprocess.run(['docker', 'network', 'ls', '--format', '{{.Name}}'], 
                               capture_output=True, text=True, check=True)
        network_names = result.stdout.strip().split('\n')

        for name in network_names:
            inspect = subprocess.run(['docker', 'network', 'inspect', name], 
                                   capture_output=True, text=True, check=True)
            if subnet in inspect.stdout:
                existing_network = name
                break

        network_name = existing_network or f'net_{str(net.network_address).replace(".", "_")}_{mask_bits}'

        if not existing_network:
            create_result = subprocess.run([
                "docker", "network", "create",
                "--subnet", subnet,
                network_name
            ], capture_output=True, text=True, check=True)
            if create_result.returncode != 0:
                flash(f'Failed to create network {network_name}: {create_result.stderr}', 'error')
                return redirect(url_for('index'))

        # Check if the requested IP is already used
        inspect = subprocess.run(['docker', 'network', 'inspect', network_name], 
                                capture_output=True, text=True, check=True)
        network_data = json.loads(inspect.stdout)
        for container in network_data[0].get('Containers', {}).values():
            if container.get('IPv4Address', '').startswith(f"{raw_ip}/"):
                flash(f'IP address {raw_ip} is already in use on Docker network {network_name}', 'error')
                return redirect(url_for('index'))

        # Disconnect first (safety)
        subprocess.run(['docker', 'network', 'disconnect', network_name, container_name], 
                      capture_output=True, text=True, check=False)

        # Connect with the desired IP
        connect_result = subprocess.run([
            "docker", "network", "connect",
            "--ip", raw_ip,
            network_name,
            container_name
        ], capture_output=True, text=True, check=True)
        if connect_result.returncode != 0:
            flash(f'Failed to connect to network {network_name}: {connect_result.stderr}', 'error')
            return redirect(url_for('index'))

        # Apply the default route
        subprocess.run([
            "docker", "exec", container_name,
            "ip", "route", "del", "default"
        ], capture_output=True, text=True, check=False)

        route_result = subprocess.run([
            "docker", "exec", container_name,
            "ip", "route", "add", "default", "via", default_gateway
        ], capture_output=True, text=True, check=True)
        if route_result.returncode != 0:
            flash(f'Failed to set default gateway: {route_result.stderr}', 'error')
            return redirect(url_for('index'))

        flash(f'Interface {interface} configured via Docker network {network_name}!', 'success')

    except subprocess.CalledProcessError as e:
        flash(f'Docker error: {e.stderr or str(e)}', 'error')
    except Exception as e:
        flash(f'Invalid input or error: {str(e)}', 'error')

    return redirect(url_for('index'))

@app.route('/delete_interface')
def delete_interface():
    config = load_config()
    container_name = socket.gethostname()
    network_to_disconnect = None

    # Extract subnet from stored IP to find matching network
    if 'interface' in config and 'ip_address' in config['interface']:
        try:
            ip_address_input = config['interface']['ip_address']
            subnet_mask = config['interface']['subnet_mask']
            raw_ip = ip_address_input.split('/')[0]
            mask_parts = subnet_mask.split('.')
            mask_bits = sum(bin(int(part)).count('1') for part in mask_parts)
            net = ip_network(f"{raw_ip}/{mask_bits}", strict=False)
            subnet = f"{net.network_address}/{mask_bits}"

            # Search for matching network
            result = subprocess.run(['docker', 'network', 'ls', '--format', '{{.Name}}'], capture_output=True, text=True, check=True)
            network_names = result.stdout.strip().split('\n')

            for name in network_names:
                inspect = subprocess.run(['docker', 'network', 'inspect', name], capture_output=True, text=True)
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
            flash(f'Error during network cleanup: {str(e)}', 'error')

    config['interface'] = {}
    save_config(config)
    flash('Interface deleted and network detached.', 'success')
    return redirect(url_for('index'))

@app.route('/ping', methods=['POST'])
def ping():
    target_ip = request.form['target_ip']
    try:
        result = subprocess.run(['ping', '-c', '4', target_ip], capture_output=True, text=True, timeout=10)
        output = result.stdout if result.returncode == 0 else result.stderr
        flash(f'Ping to {target_ip}:\n{output}', 'success')
    except subprocess.TimeoutExpired:
        flash(f'Ping to {target_ip} timed out.', 'error')
    except Exception as e:
        flash(f'Error pinging {target_ip}: {str(e)}', 'error')
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_config_file()
    app.run(host='0.0.0.0', port=5003)