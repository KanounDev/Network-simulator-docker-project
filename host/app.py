import os
import json
import subprocess
import socket
from ipaddress import ip_network, ip_address
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
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

from ipaddress import ip_address, ip_network

from ipaddress import ip_network, ip_address

@app.route('/set_interface', methods=['POST'])
def set_interface():
    config = load_config()
    ip_address_input = request.form['ip_address'].strip()
    subnet_mask = request.form['subnet_mask'].strip()
    default_gateway = request.form['default_gateway'].strip()
    interface = 'eth0'

    raw_ip = ip_address_input.split('/')[0]
    subnet = '.'.join(raw_ip.split('.')[:3]) + '.0/24'

    try:
        net = ip_network(subnet, strict=False)
        if ip_address(default_gateway) not in net:
            flash('Default gateway must be in the same subnet as the IP address', 'error')
            return redirect(url_for('index'))
    except Exception as e:
        flash(f'Invalid subnet or gateway: {e}', 'error')
        return redirect(url_for('index'))

    config['interface'] = {
        'ip_address': ip_address_input,
        'subnet_mask': subnet_mask,
        'default_gateway': default_gateway,
        'interface': interface
    }
    save_config(config)

    try:
        container_name = socket.gethostname()

        # Find matching Docker network
        existing_network = None
        result = subprocess.run(['docker', 'network', 'ls', '--format', '{{.Name}}'], capture_output=True, text=True, check=True)
        network_names = result.stdout.strip().split('\n')

        for name in network_names:
            inspect = subprocess.run(['docker', 'network', 'inspect', name], capture_output=True, text=True)
            if subnet in inspect.stdout:
                existing_network = name
                break

        network_name = existing_network or f'net_{subnet.replace(".", "_").replace("/", "_")}'

        if not existing_network:
            subprocess.run([
                "docker", "network", "create",
                "--subnet", subnet,
                network_name
            ], check=True)

        # 🧠 Check if the requested IP is already used in that network
        inspect = subprocess.run(['docker', 'network', 'inspect', network_name], capture_output=True, text=True)
        if inspect.returncode == 0 and raw_ip in inspect.stdout:
            flash(f'IP address {raw_ip} is already in use on Docker network {network_name}', 'error')
            return redirect(url_for('index'))

        # Disconnect first (safety)
        subprocess.run([
            "docker", "network", "disconnect",
            network_name,
            container_name
        ], check=False)

        # Connect with the desired IP
        subprocess.run([
            "docker", "network", "connect",
            "--ip", raw_ip,
            network_name,
            container_name
        ], check=True)

        # Apply the default route
        subprocess.run([
            "docker", "exec", container_name,
            "ip", "route", "del", "default"
        ], check=False)

        subprocess.run([
            "docker", "exec", container_name,
            "ip", "route", "add", "default", "via", default_gateway
        ], check=True)

        flash(f'Interface {interface} configured via Docker network {network_name}!', 'success')

    except subprocess.CalledProcessError as e:
        flash(f'Docker error: {str(e)}', 'error')
    except Exception as ex:
        flash(f'Unexpected error: {str(ex)}', 'error')

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
            raw_ip = ip_address_input.split('/')[0]
            subnet = '.'.join(raw_ip.split('.')[:3]) + '.0/24'

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