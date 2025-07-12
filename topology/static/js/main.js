const stage = new Konva.Stage({
    container: 'canvas-container',
    width: document.getElementById('canvas-container').offsetWidth,
    height: 500
});

const layer = new Konva.Layer();
stage.add(layer);

let nodes = [];
let edges = [];
let connectMode = false;
let selectedNode = null;

const deviceImages = {
    Host: '/static/images/host.png',
    Router: '/static/images/router.png',
    Switch: '/static/images/switch.png'
};

function addDevice(type, x = 50, y = 50, nodeId = null) {
    return new Promise(resolve => {
        const id = nodeId !== null ? nodeId : nodes.length + 1;
        const group = new Konva.Group({
            x: x,
            y: y,
            draggable: true,
            id: `node-${id}`
        });

        // Load image
        const img = new Image();
        img.src = deviceImages[type];
        img.onload = () => {
            const konvaImage = new Konva.Image({
                image: img,
                width: 32,
                height: 32,
                x: -16,
                y: -16
            });

            const label = new Konva.Text({
                text: `${type}-${id}`,
                fontSize: 12,
                fill: 'black',
                y: 20,
                align: 'center'
            });

            group.add(konvaImage, label);
            layer.add(group);
            layer.draw();

            // Only push to nodes if not already added
            if (!nodes.find(n => n.id === id)) {
                nodes.push({ id: id, type: type, x: x, y: y });
            }

            // Update node position on drag
            group.on('dragmove', () => {
                const node = nodes.find(n => n.id === id);
                if (node) {
                    node.x = group.x();
                    node.y = group.y();
                    redrawEdges();
                }
            });

            resolve();
        };
        img.onerror = () => {
            console.error(`Failed to load image for ${type}`);
            resolve(); // Proceed even if image fails
        };

        // Handle click for connections
        group.on('click', () => {
            if (connectMode) {
                console.log(`Clicked node: ${group.id()}`);
                if (!selectedNode) {
                    selectedNode = group;
                    showMessage(`Selected ${group.id()} as source`, 'success');
                } else if (selectedNode !== group) {
                    addEdge(selectedNode, group);
                    showMessage(`Connected ${selectedNode.id()} to ${group.id()}`, 'success');
                    selectedNode = null;
                    toggleConnectMode();
                }
            }
        });
        group.on('dblclick', () => {
            fetch('/launch_node', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id, type })
            })
                .then(response => response.json())
                .then(data => {
                    if (data.url) {
                        window.open(data.url, '_blank');
                    } else {
                        showMessage(data.error || 'Unknown error', 'error');
                    }
                })
                .catch(() => showMessage('Failed to open node UI', 'error'));
        });
        // Handle right-click to delete
        group.on('contextmenu', (e) => {
            e.evt.preventDefault();
            if (confirm(`Delete ${type}-${id}?`)) {
                nodes = nodes.filter(node => node.id !== id);
                edges = edges.filter(edge => edge.source !== id && edge.target !== id);
                group.destroy();
                redrawEdges();
                layer.draw();
            }
        });
    });
}

function addEdge(sourceGroup, targetGroup) {
    const sourceId = parseInt(sourceGroup.id().split('-')[1]);
    const targetId = parseInt(targetGroup.id().split('-')[1]);
    if (sourceId !== targetId) {
        edges.push({ source: sourceId, target: targetId });
        redrawEdges();
    }
}

function redrawEdges() {
    layer.find('.edge').forEach(edge => edge.destroy());
    edges.forEach(edge => {
        const sourceGroup = layer.findOne(`#node-${edge.source}`);
        const targetGroup = layer.findOne(`#node-${edge.target}`);
        if (sourceGroup && targetGroup) {
            const line = new Konva.Line({
                points: [sourceGroup.x(), sourceGroup.y(), targetGroup.x(), targetGroup.y()],
                stroke: 'black',
                strokeWidth: 2,
                name: 'edge'
            });
            layer.add(line);
            line.moveToBottom();
        }
    });
    layer.draw();
}

function toggleConnectMode() {
    connectMode = !connectMode;
    const button = document.getElementById('connectMode');
    button.className = connectMode ? 'bg-yellow-500 text-white p-2 rounded hover:bg-yellow-600' : 'bg-green-500 text-white p-2 rounded hover:bg-green-600';
    button.textContent = connectMode ? 'Cancel Connect' : 'Connect Devices';
    selectedNode = null;
}

function showMessage(text, type = 'success') {
    const messages = document.getElementById('messages');
    messages.innerHTML = `<div class="p-4 rounded ${type === 'success' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}">${text}</div>`;
    setTimeout(() => messages.innerHTML = '', 3000);
}

// Populate topology dropdown
function updateTopologyDropdown() {
    fetch('/list_topologies')
        .then(response => response.json())
        .then(data => {
            const select = document.getElementById('topologySelect');
            select.innerHTML = '<option value="">Select a topology</option>';
            data.topologies.forEach(name => {
                const option = document.createElement('option');
                option.value = name;
                option.textContent = name;
                select.appendChild(option);
            });
        })
        .catch(() => showMessage('Error fetching topologies', 'error'));
}

// Event Listeners
document.getElementById('addHost').addEventListener('click', () => addDevice('Host'));
document.getElementById('addRouter').addEventListener('click', () => addDevice('Router'));
document.getElementById('addSwitch').addEventListener('click', () => addDevice('Switch'));
document.getElementById('connectMode').addEventListener('click', toggleConnectMode);

document.getElementById('saveTopology').addEventListener('click', () => {
    const name = document.getElementById('topologyName').value.trim();
    if (!name) {
        showMessage('Please enter a topology name', 'error');
        return;
    }
    const topology = { name, nodes, edges };
    fetch('/save_topology', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(topology)
    })
        .then(response => response.json())
        .then(data => {
            showMessage(data.message || data.error, data.error ? 'error' : 'success');
            updateTopologyDropdown();
        })
        .catch(() => showMessage('Error saving topology', 'error'));
});

document.getElementById('loadTopology').addEventListener('click', async () => {
    const name = document.getElementById('topologySelect').value;
    if (!name) {
        showMessage('Please select a topology', 'error');
        return;
    }
    try {
        const response = await fetch('/load_topology', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });
        const data = await response.json();
        if (data.error) {
            showMessage(data.error, 'error');
            return;
        }
        nodes = data.nodes || [];
        edges = data.edges || [];
        layer.destroyChildren();
        // Load all nodes and wait for images
        await Promise.all(nodes.map(node => addDevice(node.type, node.x, node.y, node.id)));
        redrawEdges();
        showMessage('Topology loaded successfully');
    } catch {
        showMessage('Error loading topology', 'error');
    }
});

document.getElementById('clearCanvas').addEventListener('click', () => {
    if (confirm('Clear the canvas?')) {
        nodes = [];
        edges = [];
        layer.destroyChildren();
        layer.draw();
        showMessage('Canvas cleared');
    }
});

// Handle canvas resize
window.addEventListener('resize', () => {
    stage.width(document.getElementById('canvas-container').offsetWidth);
    stage.draw();
});

// Initialize topology dropdown
updateTopologyDropdown();