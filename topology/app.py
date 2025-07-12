import os
import json
from flask import Flask, render_template, request, jsonify
import subprocess

app = Flask(__name__)

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
            subprocess.run([
                'docker', 'run', '-dit',
                '--name', container_name,
                '-p', f'{dynamic_port}:{base_port}',
                '--cap-add=NET_ADMIN',
                '-v', '/var/run/docker.sock:/var/run/docker.sock',
                image_name
            ], check=True)

        return jsonify({'url': f'http://localhost:{dynamic_port}'})
    except subprocess.CalledProcessError as e:
        return jsonify({'error': str(e)}), 500

# Initialize JSON file if it doesn't exist
def init_config_file():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'w') as f:
            json.dump({'topologies': []}, f, indent=4)

# Load topologies from JSON file
def load_config():
    try:
        init_config_file()
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            if 'topologies' not in config:
                config['topologies'] = []
            return config
    except json.JSONDecodeError:
        init_config_file()
        return {'topologies': []}

# Save topologies to JSON file
def save_config(config):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        return str(e)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/list_topologies', methods=['GET'])
def list_topologies():
    config = load_config()
    topology_names = [t['name'] for t in config['topologies']]
    return jsonify({'topologies': topology_names})

@app.route('/load_topology', methods=['POST'])
def load_topology():
    name = request.json.get('name')
    if not name:
        return jsonify({'error': 'Topology name required'}), 400
    config = load_config()
    topology = next((t for t in config['topologies'] if t['name'] == name), None)
    if topology:
        return jsonify(topology)
    return jsonify({'error': 'Topology not found'}), 404

@app.route('/save_topology', methods=['POST'])
def save_topology():
    data = request.get_json()
    name = data.get('name')
    if not name:
        return jsonify({'error': 'Topology name required'}), 400
    config = load_config()
    # Remove existing topology with same name
    config['topologies'] = [t for t in config['topologies'] if t['name'] != name]
    config['topologies'].append({'name': name, 'nodes': data['nodes'], 'edges': data['edges']})
    error = save_config(config)
    if error:
        return jsonify({'error': error}), 500
    return jsonify({'message': 'Topology saved successfully'})
if __name__ == '__main__':
    init_config_file()
    app.run(host='0.0.0.0', port=5000)