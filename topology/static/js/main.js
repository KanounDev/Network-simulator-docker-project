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
let maxNodeId = 0; // Track highest node ID

const deviceImages = {
    Host: '/static/images/host.png',
    Router: '/static/images/router.png',
    Switch: '/static/images/switch.png'
};

function addDevice(type, x = 50, y = 50, nodeId = null) {
    return new Promise(resolve => {
        const id = nodeId !== null ? nodeId : maxNodeId + 1;
        maxNodeId = Math.max(maxNodeId, id);
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
            resolve();
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
            if (type !== "Switch") {
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
            }
        });
        // Handle right-click to delete
        group.on('contextmenu', (e) => {
            e.evt.preventDefault();
            // Create overlay
            const overlay = document.createElement('div');
            overlay.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50';

            // Create dialog
            const dialog = document.createElement('div');
            dialog.className = 'bg-white rounded-lg p-6 shadow-lg max-w-sm w-full';
            dialog.innerHTML = `
        <h3 class="text-lg font-semibold text-gray-800 mb-4">Delete ${type}-${id}?</h3>
        <div class="flex justify-end gap-3">
            <button id="cancelDelete" class="bg-gray-300 text-gray-800 px-4 py-2 rounded-lg hover:bg-gray-400 transition duration-200">Cancel</button>
            <button id="confirmDelete" class="bg-red-600 text-white px-4 py-2 rounded-lg hover:bg-red-700 transition duration-200">Confirm</button>
        </div>
    `;

            // Append dialog to overlay and overlay to body
            overlay.appendChild(dialog);
            document.body.appendChild(overlay);

            // Cancel button
            document.getElementById('cancelDelete').addEventListener('click', () => {
                document.body.removeChild(overlay);
            });

            // Confirm button
            document.getElementById('confirmDelete').addEventListener('click', () => {
                document.body.removeChild(overlay);
                fetch('/delete_node', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ type, id })
                })
                    .then(response => response.json())
                    .then(data => {
                        if (data.error) {
                            showMessage(data.error, 'error');
                            return;
                        }
                        nodes = nodes.filter(node => node.id !== id);
                        edges = edges.filter(edge => edge.source !== id && edge.target !== id);
                        group.destroy();
                        redrawEdges();
                        layer.draw();
                        showMessage(data.message, 'success');
                    })
                    .catch(() => showMessage('Error deleting node', 'error'));
            });
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
    const toast = document.createElement('div');
    toast.innerText = text;
    toast.className = `fixed bottom-6 left-1/2 transform -translate-x-1/2 
        px-4 py-2 rounded-lg shadow-lg z-50 transition-opacity duration-300 
        ${type === 'success' ? 'bg-green-600 text-white' : 'bg-red-600 text-white'}`;

    document.body.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('opacity-0');
        setTimeout(() => toast.remove(), 300); // Remove after fade-out
    }, 3000);
}



// Event Listeners
document.getElementById('addHost').addEventListener('click', () => addDevice('Host'));
document.getElementById('addRouter').addEventListener('click', () => addDevice('Router'));
document.getElementById('addSwitch').addEventListener('click', () => addDevice('Switch'));
document.getElementById('connectMode').addEventListener('click', toggleConnectMode);

document.getElementById('saveTopology').addEventListener('click', () => {
    const topology = { nodes, edges };
    fetch('/save_topology', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(topology)
    })
        .then(response => response.json())
        .then(data => {
            showMessage(data.message || data.error, data.error ? 'error' : 'success');
        })
        .catch(() => showMessage('Error saving topology', 'error'));
});

document.getElementById('loadTopology').addEventListener('click', async () => {
    try {
        const response = await fetch('/load_topology', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        const data = await response.json();
        if (data.error) {
            showMessage(data.error, 'error');
            return;
        }
        nodes = data.nodes || [];
        edges = data.edges || [];
        maxNodeId = Math.max(0, ...nodes.map(n => n.id));
        layer.destroyChildren();
        await Promise.all(nodes.map(node => addDevice(node.type, node.x, node.y, node.id)));
        redrawEdges();
        showMessage('Topology loaded successfully');
    } catch {
        showMessage('Error loading topology', 'error');
    }
});

document.getElementById('clearCanvas').addEventListener('click', () => {
    // Create overlay
    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50';

    // Create dialog
    const dialog = document.createElement('div');
    dialog.className = 'bg-white rounded-lg p-6 shadow-lg max-w-sm w-full';
    dialog.innerHTML = `
        <h3 class="text-lg font-semibold text-gray-800 mb-4">Clear the topology?</h3>
        <div class="flex justify-end gap-3">
            <button id="cancelClear" class="bg-gray-300 text-gray-800 px-4 py-2 rounded-lg hover:bg-gray-400 transition duration-200">Cancel</button>
            <button id="confirmClear" class="bg-red-600 text-white px-4 py-2 rounded-lg hover:bg-red-700 transition duration-200">Confirm</button>
        </div>
    `;

    // Append dialog to overlay and overlay to body
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);

    // Cancel button
    document.getElementById('cancelClear').addEventListener('click', () => {
        document.body.removeChild(overlay);
    });

    // Confirm button
    document.getElementById('confirmClear').addEventListener('click', () => {
        document.body.removeChild(overlay);
        nodes = [];
        edges = [];
        fetch('/clear_topology', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ nodes, edges })
        })
            .then(response => response.json())
            .then(data => {
                showMessage(data.message || data.error, data.error ? 'error' : 'success');
                maxNodeId = 0;
                layer.destroyChildren();
                layer.draw();
            })
            .catch(() => showMessage('Error clearing topology', 'error'));
    });
});

// Handle canvas resize
window.addEventListener('resize', () => {
    stage.width(document.getElementById('canvas-container').offsetWidth);
    stage.draw();
});