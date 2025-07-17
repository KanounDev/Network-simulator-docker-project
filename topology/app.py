import os
import json
from flask import Flask, render_template, request, jsonify
import subprocess

app = Flask(__name__)
app.secret_key = 'supersecretkey123'

CONFIG_FILE = 'topologies.json'

@app.route('/launch_node', methods=['POST'])
def launch_node():
    data = request.get_json()
    node_type = data.get('type')
    node_id = data.get('id')

    if not node_type or not node_id:
        return jsonify({'error': 'Missing node type or id'}), 400

    container_name = f"{node_type.lower()}{node_id}"
    image_name = node_type.lower()

    base_port = {
        'router': 5002,
        'host': 5003
    }.get(image_name, 5000)

    dynamic_port = base_port + 10 * int(node_id)

    try:
        # Build image if it doesn't exist
        images = subprocess.check_output(['docker', 'images', '-q', image_name]).decode().strip()
        if not images:
            subprocess.run(['docker', 'build', '-t', image_name, f'../{image_name}'], check=True)

        # Check if container already exists
        containers = subprocess.check_output(['docker', 'ps', '-a', '--format', '{{.Names}}']).decode().splitlines()
        if container_name not in containers:
            local_folder = os.path.abspath(f"../{image_name}")
            subprocess.run([
                'docker', 'run', '-dit',
                '--name', container_name,
                '-p', f'{dynamic_port}:{base_port}',
                '--cap-add=NET_ADMIN',
                '-v', '/var/run/docker.sock:/var/run/docker.sock',
                '-v', f'{local_folder}/templates:/app/templates',
                '-v', f'{local_folder}/static:/app/static',
                '-v', f'{local_folder}/app.py:/app/app.py',
                image_name
            ], check=True)

        return jsonify({'url': f'http://localhost:{dynamic_port}'})
    except subprocess.CalledProcessError as e:
        return jsonify({'error': str(e)}), 500

# Initialize JSON file if it doesn't exist
def init_config_file():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'w') as f:
            json.dump({'nodes': [], 'edges': []}, f, indent=4)

# Load topology from JSON file
def load_config():
    try:
        init_config_file()
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            if 'nodes' not in config or 'edges' not in config:
                config = {'nodes': [], 'edges': []}
                save_config(config)
            return config
    except json.JSONDecodeError:
        init_config_file()
        return {'nodes': [], 'edges': []}

# Save topology to JSON file
def save_config(config):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        return str(e)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/load_topology', methods=['POST'])
def load_topology():
    config = load_config()
    return jsonify({'nodes': config['nodes'], 'edges': config['edges']})

@app.route('/save_topology', methods=['POST'])
def save_topology():
    data = request.get_json()
    if not data or 'nodes' not in data or 'edges' not in data:
        return jsonify({'error': 'Invalid topology data'}), 400
    config = {'nodes': data['nodes'], 'edges': data['edges']}
    error = save_config(config)
    if error:
        return jsonify({'error': error}), 500
    return jsonify({'message': 'Topology saved successfully'})

@app.route('/clear_topology', methods=['POST'])
def clear_topology():
    try:
        # Clear topology.json
        config = {'nodes': [], 'edges': []}
        error = save_config(config)
        if error:
            return jsonify({'error': f'Failed to clear topology: {error}'}), 500

        # Delete Docker networks starting with "net"
        networks = subprocess.check_output(['docker', 'network', 'ls', '--format', '{{.Name}}']).decode().splitlines()
        for network in networks:
            if network.startswith('net'):
                subprocess.run(['docker', 'network', 'rm', network], check=False, capture_output=True)

        # Delete Docker containers starting with "host" or "router"
        containers = subprocess.check_output(['docker', 'ps', '-a', '--format', '{{.Names}}']).decode().splitlines()
        for container in containers:
            if container.startswith('host') or container.startswith('router'):
                subprocess.run(['docker', 'rm', '-f', container], check=False, capture_output=True)

        return jsonify({'message': 'Topology cleared successfully'})
    except subprocess.CalledProcessError as e:
        return jsonify({'error': f'Docker cleanup failed: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'Failed to clear topology: {str(e)}'}), 500
@app.route('/delete_node', methods=['POST'])
def delete_node():
    try:
        data = request.get_json()
        node_type = data.get('type')
        node_id = data.get('id')
        
        if not node_type or not node_id:
            return jsonify({'error': 'Missing node type or id'}), 400
            
        container_name = f"{node_type.lower()}{node_id}"
        
        # Delete Docker container
        containers = subprocess.check_output(['docker', 'ps', '-a', '--format', '{{.Names}}']).decode().splitlines()
        if container_name in containers:
            subprocess.run(['docker', 'rm', '-f', container_name], check=False, capture_output=True)
        
        # Update topology.json
        config = load_config()
        config['nodes'] = [node for node in config['nodes'] if node['id'] != node_id]
        config['edges'] = [edge for edge in config['edges'] if edge['source'] != node_id and edge['target'] != node_id]
        error = save_config(config)
        if error:
            return jsonify({'error': f'Failed to update topology: {error}'}), 500
            
        return jsonify({'message': f'Node {node_type}-{node_id} deleted successfully'})
    except subprocess.CalledProcessError as e:
        return jsonify({'error': f'Docker cleanup failed: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'Failed to delete node: {str(e)}'}), 500

if __name__ == '__main__':
    init_config_file()
    app.run(debug=True,host='0.0.0.0', port=5000)