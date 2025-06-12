# flask-app/app.py (Flask Application)
import os
import time
import psycopg2
from flask import Flask, jsonify, render_template_string, request, redirect, url_for
from kubernetes import client, config
from threading import Thread

app = Flask(__name__)

# Database connection details from Kubernetes environment variables
DB_HOST = os.getenv('POSTGRES_HOST', 'my-postgres-cluster') # Operator creates a service named after the cluster
DB_NAME = os.getenv('POSTGRES_DB', 'mydatabase')
DB_USER = os.getenv('POSTGRES_USER', 'myapp') # User defined in postgres-cluster.yaml
DB_PASSWORD = os.getenv('POSTGRES_PASSWORD')

# Global variable for DB connection
conn = None

def get_db_connection():
    """Establishes and returns a database connection."""
    global conn
    # Check if connection exists and is still open
    if conn:
        try:
            # Attempt a dummy query to check if connection is still valid
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
            return conn # Connection is good
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            # Connection was lost, try to re-establish
            conn = None
            print("Existing DB connection lost, attempting to reconnect...")
    
    retries = 15 # Increased retries for robustness in a K8s environment
    for i in range(retries):
        try:
            conn = psycopg2.connect(
                host=DB_HOST,
                database=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD
            )
            conn.autocommit = True # For simplicity in this example, commit immediately
            print("Successfully connected to PostgreSQL.")
            return conn
        except psycopg2.OperationalError as e:
            print(f"Attempt {i+1}/{retries}: Could not connect to database at {DB_HOST}: {e}")
            time.sleep(min(2**(i+1), 30)) # Exponential backoff, max 30 seconds
    print("Failed to connect to database after several retries.")
    return None

def init_db():
    """Initializes the database by creating a table if it doesn't exist."""
    db_conn = get_db_connection()
    if db_conn:
        try:
            cur = db_conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    content VARCHAR(255) NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # No explicit commit needed if autocommit is True
            print("Database table 'messages' initialized.")
            
            # Check if table is empty and add a default message if not already there
            cur.execute("SELECT COUNT(*) FROM messages;")
            if cur.fetchone()[0] == 0:
                cur.execute("INSERT INTO messages (content) VALUES ('Hello from Flask on Kubernetes with Zalando Postgres Operator!');")
                print("Default message added to 'messages' table.")
            cur.close()
        except Exception as e:
            print(f"Error initializing database: {e}")
            # If autocommit is False, you'd need db_conn.rollback() here
    else:
        print("Could not initialize database: No connection.")

# Run database initialization in a separate thread to not block app startup
Thread(target=init_db).start()

# Initialize Kubernetes client
try:
    config.load_incluster_config() # For running inside Kubernetes
    v1 = client.CoreV1Api()
    app_v1 = client.AppsV1Api()
    print("Kubernetes in-cluster config loaded.")
except Exception as e:
    print(f"Could not load in-cluster Kubernetes config, falling back to KUBECONFIG: {e}")
    try:
        config.load_kube_config() # For local testing (ensure KUBECONFIG is set)
        v1 = client.CoreV1Api()
        app_v1 = client.AppsV1Api()
        print("Kubernetes kubeconfig loaded (for local testing).")
    except Exception as e:
        print(f"Could not load Kubernetes kubeconfig: {e}. Kubernetes API access will be unavailable.")
        v1 = None
        app_v1 = None


@app.route('/')
def home():
    """Home route displaying messages, and forms for CRUD operations."""
    db_status = "Not connected"
    messages = []
    
    db_conn = get_db_connection()
    if db_conn:
        try:
            cur = db_conn.cursor()
            cur.execute("SELECT id, content, timestamp FROM messages ORDER BY timestamp DESC;")
            messages = cur.fetchall()
            cur.close()
            db_status = "Connected and data retrieved"
        except Exception as e:
            db_status = f"Connected, but error retrieving data: {e}"
            print(db_status)
    
    # HTML for displaying messages and CRUD forms
    message_list_html = ""
    if messages:
        message_list_html += "<ul class='list-disc pl-5 space-y-4'>"
        for msg_id, content, ts in messages:
            message_list_html += f"""
            <li class="p-3 bg-gray-50 rounded-md shadow-sm flex justify-between items-center">
                <div>
                    <span class="font-medium text-gray-800">{content}</span>
                    <span class="text-sm text-gray-500 block"> (Added: {ts.strftime('%Y-%m-%d %H:%M:%S')})</span>
                </div>
                <div class="flex space-x-2">
                    <a href="{url_for('edit_message', message_id=msg_id)}" class="bg-yellow-500 hover:bg-yellow-600 text-white font-bold py-1 px-3 rounded-md text-sm">Edit</a>
                    <form action="{url_for('delete_message', message_id=msg_id)}" method="post" onsubmit="return confirm('Are you sure you want to delete this message?');">
                        <button type="submit" class="bg-red-500 hover:bg-red-600 text-white font-bold py-1 px-3 rounded-md text-sm">Delete</button>
                    </form>
                </div>
            </li>
            """
        message_list_html += "</ul>"
    else:
        message_list_html = "<p class='text-gray-600'>No messages yet. Add one below!</p>"


    return render_template_string("""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Flask App on Kubernetes - CRUD</title>
            <script src="https://cdn.tailwindcss.com"></script>
            <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap" rel="stylesheet">
            <style>
                body {
                    font-family: 'Inter', sans-serif;
                    background-color: #f3f4f6;
                    color: #333;
                }
                .container {
                    max-width: 768px; /* md:max-w-xl from tailwind */
                }
            </style>
        </head>
        <body class="bg-gray-100 flex items-center justify-center min-h-screen p-4">
            <div class="bg-white p-8 rounded-lg shadow-xl container w-full text-center">
                <h1 class="text-3xl font-bold mb-4 text-blue-600">Flask App with PostgreSQL CRUD</h1>
                <p class="text-lg text-gray-700 mb-6">Database Status: <span class="font-semibold">{{ db_status }}</span></p>
                
                <div class="mb-8 text-left">
                    <h2 class="text-2xl font-semibold mb-4 text-gray-800">Messages:</h2>
                    {{ message_list_html | safe }}
                </div>

                <div class="mb-8 text-left">
                    <h2 class="text-2xl font-semibold mb-4 text-gray-800">Add New Message:</h2>
                    <form action="{{ url_for('add_message') }}" method="post" class="space-y-4">
                        <input type="text" name="content" placeholder="Enter your message" required
                               class="w-full p-3 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
                        <button type="submit"
                                class="w-full bg-blue-500 hover:bg-blue-600 text-white font-bold py-2 px-4 rounded-md transition duration-300">
                            Add Message
                        </button>
                    </form>
                </div>
                
                <p class="text-sm text-gray-500 mt-4">This application is running in a Kubernetes cluster.</p>
                <p class="mt-4"><a href="{{ url_for('k8s_info') }}" class="text-blue-500 hover:text-blue-700 font-medium">Click here to see Kubernetes resources in this namespace</a></p>
            </div>
        </body>
        </html>
    """, db_status=db_status, message_list_html=message_list_html)

@app.route('/add_message', methods=['POST'])
def add_message():
    """Route to handle adding a new message."""
    content = request.form['content']
    if not content:
        # In a real app, you might render a message or redirect with an error
        return redirect(url_for('home'))

    db_conn = get_db_connection()
    if db_conn:
        try:
            cur = db_conn.cursor()
            cur.execute("INSERT INTO messages (content) VALUES (%s);", (content,))
            cur.close()
        except Exception as e:
            print(f"Error adding message: {e}")
    return redirect(url_for('home'))

@app.route('/edit_message/<int:message_id>', methods=['GET', 'POST'])
def edit_message(message_id):
    """Route to display and handle editing an existing message."""
    db_conn = get_db_connection()
    message = None
    if db_conn:
        try:
            cur = db_conn.cursor()
            cur.execute("SELECT id, content FROM messages WHERE id = %s;", (message_id,))
            message = cur.fetchone()
            cur.close()
        except Exception as e:
            print(f"Error fetching message for edit: {e}")

    if request.method == 'POST':
        if message: # Only update if message exists
            new_content = request.form['content']
            if new_content:
                if db_conn:
                    try:
                        cur = db_conn.cursor()
                        cur.execute("UPDATE messages SET content = %s WHERE id = %s;", (new_content, message_id))
                        cur.close()
                    except Exception as e:
                        print(f"Error updating message: {e}")
            return redirect(url_for('home'))
        else:
            # Handle case where message is not found for update
            print(f"Attempted to update non-existent message ID: {message_id}")
            return redirect(url_for('home'))

    # GET request: display the edit form
    if message:
        return render_template_string("""
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Edit Message</title>
                <script src="https://cdn.tailwindcss.com"></script>
                <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap" rel="stylesheet">
                <style>
                    body {
                        font-family: 'Inter', sans-serif;
                        background-color: #f3f4f6;
                        color: #333;
                    }
                    .container {
                        max-width: 500px;
                    }
                </style>
            </head>
            <body class="bg-gray-100 flex items-center justify-center min-h-screen p-4">
                <div class="bg-white p-8 rounded-lg shadow-xl container w-full text-center">
                    <h1 class="text-3xl font-bold mb-6 text-blue-600">Edit Message (ID: {{ message[0] }})</h1>
                    <form action="{{ url_for('edit_message', message_id=message[0]) }}" method="post" class="space-y-4">
                        <input type="text" name="content" value="{{ message[1] }}" required
                               class="w-full p-3 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
                        <button type="submit"
                                class="w-full bg-green-500 hover:bg-green-600 text-white font-bold py-2 px-4 rounded-md transition duration-300">
                            Update Message
                        </button>
                    </form>
                    <p class="mt-4"><a href="{{ url_for('home') }}" class="text-blue-500 hover:text-blue-700 font-medium">Back to Home</a></p>
                </div>
            </body>
            </html>
        """, message=message)
    else:
        return redirect(url_for('home')) # Redirect if message not found

@app.route('/delete_message/<int:message_id>', methods=['POST'])
def delete_message(message_id):
    """Route to handle deleting a message."""
    db_conn = get_db_connection()
    if db_conn:
        try:
            cur = db_conn.cursor()
            cur.execute("DELETE FROM messages WHERE id = %s;", (message_id,))
            cur.close()
        except Exception as e:
            print(f"Error deleting message: {e}")
    return redirect(url_for('home'))

@app.route('/k8s-info')
def k8s_info():
    """Route to list Kubernetes pods and deployments in the current namespace."""
    namespace = os.getenv('KUBERNETES_NAMESPACE', 'default') # Get current namespace from env var
    
    if not v1 or not app_v1:
        return jsonify({"error": "Kubernetes client not initialized. Check logs for details."}), 500

    pods_info = []
    deployments_info = []

    try:
        # List pods in the current namespace
        pods = v1.list_namespaced_pod(namespace=namespace)
        for pod in pods.items:
            pods_info.append({
                "name": pod.metadata.name,
                "status": pod.status.phase,
                "ip": pod.status.pod_ip,
                "node": pod.spec.node_name
            })

        # List deployments in the current namespace
        deployments = app_v1.list_namespaced_deployment(namespace=namespace)
        for deploy in deployments.items:
            deployments_info.append({
                "name": deploy.metadata.name,
                "replicas": deploy.spec.replicas,
                "available_replicas": deploy.status.available_replicas
            })

    except client.ApiException as e:
        if e.status == 403:
            return jsonify({
                "error": "Permission denied to access Kubernetes API. Check ServiceAccount and RoleBinding.",
                "details": str(e)
            }), 403
        else:
            return jsonify({
                "error": f"Error accessing Kubernetes API: {e}",
                "details": str(e)
            }), 500
    except Exception as e:
        return jsonify({"error": f"An unexpected error occurred: {e}"}), 500

    return render_template_string("""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Kubernetes Resources</title>
            <script src="https://cdn.tailwindcss.com"></script>
            <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap" rel="stylesheet">
            <style>
                body {
                    font-family: 'Inter', sans-serif;
                    background-color: #f3f4f6;
                    color: #333;
                }
            </style>
        </head>
        <body class="bg-gray-100 flex items-center justify-center min-h-screen p-4">
            <div class="bg-white p-8 rounded-lg shadow-xl max-w-3xl w-full text-left">
                <h1 class="text-3xl font-bold mb-6 text-blue-600 text-center">Kubernetes Resources in Namespace: {{ namespace }}</h1>
                
                <h2 class="text-2xl font-semibold mb-4 text-gray-800">Pods:</h2>
                {% if pods_info %}
                    <ul class="list-disc pl-5 mb-6">
                        {% for pod in pods_info %}
                            <li class="mb-2">
                                <span class="font-medium text-gray-700">Name:</span> {{ pod.name }}<br>
                                <span class="font-medium text-gray-700">Status:</span> {{ pod.status }}<br>
                                <span class="font-medium text-gray-700">IP:</span> {{ pod.ip }}<br>
                                <span class="font-medium text-gray-700">Node:</span> {{ pod.node }}
                            </li>
                        {% endfor %}
                    </ul>
                {% else %}
                    <p class="text-gray-600 mb-6">No pods found in this namespace.</p>
                {% endif %}

                <h2 class="text-2xl font-semibold mb-4 text-gray-800">Deployments:</h2>
                {% if deployments_info %}
                    <ul class="list-disc pl-5 mb-6">
                        {% for deploy in deployments_info %}
                            <li class="mb-2">
                                <span class="font-medium text-gray-700">Name:</span> {{ deploy.name }}<br>
                                <span class="font-medium text-gray-700">Replicas:</span> {{ deploy.replicas }}<br>
                                <span class="font-medium text-gray-700">Available:</span> {{ deploy.available_replicas }}
                            </li>
                        {% endfor %}
                    </ul>
                {% else %}
                    <p class="text-gray-600 mb-6">No deployments found in this namespace.</p>
                {% endif %}

                <p class="mt-8 text-center"><a href="{{ url_for('home') }}" class="text-blue-500 hover:text-blue-700 font-medium">Back to Home</a></p>
            </div>
        </body>
        </html>
    """, pods_info=pods_info, deployments_info=deployments_info, namespace=namespace)


if __name__ == '__main__':
    # Flask app will run on port 5000 inside the container
    app.run(debug=True, host='0.0.0.0', port=5000)

