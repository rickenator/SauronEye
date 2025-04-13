import sys
import ollama
import io
import multiprocessing
import time
from SettingsWindow import SettingsWindow
from configparser import ConfigParser
import os
import pyautogui
import Xlib.display
import paho.mqtt.client as mqtt
from PIL import Image
import threading
# Import necessary widgets and layouts
from PyQt5.QtWidgets import (QApplication, QMainWindow, QTextEdit, QStatusBar,
                             QPushButton, QWidget, QVBoxLayout, QHBoxLayout)
from PyQt5.QtCore import pyqtSignal, QObject, pyqtSlot, QTimer

# --- Constants ---
SENDER_ID_MAIN = "[SauronEye-Main]"
SENDER_ID_INIT = "[SauronEye-Init]"
SENDER_ID_ANALYSIS = "[SauronEye-Analysis]"
SENDER_ID_USER = "[User]" 
SENDER_ID_CHAT_RESPONSE = "[LLM-Chat]"

# --- Main Application Class (using PyQt) ---
class MainApplication(QMainWindow):
    status_update_signal = pyqtSignal(str)
    output_message_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()

        # ... (Core Attributes, Settings Loading, Attribute Update) ...
        self.settings_window = None
        self.settings = {}
        self.config = ConfigParser()
        self.config_path = "config.ini"
        self.load_settings()
        self._update_attributes_from_settings()
        self.initial_check_done = False

        # --- Setup PyQt UI ---
        self.setWindowTitle("SauronEye Chat") # Changed title
        self.statusBar = QStatusBar(self)
        self.setStatusBar(self.statusBar)

        # --- Create Chat Widgets ---
        self.chat_display = QTextEdit(self) # Renamed for clarity
        self.chat_display.setReadOnly(True)

        self.chat_input = QTextEdit(self) # Input area (allows newlines)
        self.chat_input.setFixedHeight(60) # Set a reasonable initial height

        self.send_button = QPushButton("Send", self)
        self.send_button.clicked.connect(self.handle_send_button) # Connect button click

        # --- Layout ---
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget) # Main vertical layout

        input_layout = QHBoxLayout() # Horizontal layout for input + button
        input_layout.addWidget(self.chat_input)
        input_layout.addWidget(self.send_button)

        main_layout.addWidget(self.chat_display) # Add chat display area
        main_layout.addLayout(input_layout) # Add input layout below display

        self.setCentralWidget(central_widget) # Set the layout

        # --- Connect signals to UI update slots ---
        self.status_update_signal.connect(self.update_status_bar)
        self.output_message_signal.connect(self.append_output_text)

        # --- MQTT Client Setup ---
        self.mqtt_client = None
        self.is_mqtt_connected = False
        self.mqtt_timer = QTimer(self)
        self.mqtt_timer.timeout.connect(self.mqtt_loop_check)
        self.setup_mqtt()

    # ... (Slots: update_status_bar, append_output_text) ...
    @pyqtSlot(str)
    def update_status_bar(self, message):
        if hasattr(self, 'statusBar'):
            self.statusBar.showMessage(message, 5000)

    @pyqtSlot(str)
    def append_output_text(self, text):
        """Appends text to the chat display area."""
        if hasattr(self, 'chat_display'):
            self.chat_display.append(text)

    # --- Handle Send Button Click ---
    @pyqtSlot()
    def handle_send_button(self):
        """Handles the Send button click event."""
        user_message = self.chat_input.toPlainText().strip()
        if not user_message:
            return # Don't send empty messages

        # Clear the input field
        self.chat_input.clear()

        # Publish user message to MQTT (so it appears in the chat display)
        self.publish_output_message(SENDER_ID_USER, user_message)

        # Send the message to Ollama in a background thread
        threading.Thread(target=self.send_chat_message_to_ollama,
                         args=(user_message,), daemon=True).start()

    # --- Method to send chat message to Ollama ---
    def send_chat_message_to_ollama(self, user_message):
        """Sends a text-only chat message to Ollama."""
        if not self.ollama_model or not self.ollama_server:
            self.update_status("Ollama not configured for chat.")
            self.publish_output_message(SENDER_ID_CHAT_RESPONSE, "Error: Ollama not configured.")
            return

        self.update_status(f"Sending chat message to Ollama ({self.ollama_model})...")

        try:
            client = ollama.Client(host=self.ollama_server)
            # Note: This is a stateless chat for now. For context, you'd need to manage message history.
            messages = [{'role': 'user', 'content': user_message}]

            response = client.chat(model=self.ollama_model, messages=messages)
            response_text = response['message']['content'].strip()

            self.update_status("Ollama chat response received.")
            # Publish the LLM's response to MQTT output topic
            self.publish_output_message(SENDER_ID_CHAT_RESPONSE, response_text)

        except Exception as e:
            error_message = f"Error during Ollama chat: {e}"
            self.update_status(error_message)
            print(error_message)
            # Publish error message to MQTT output topic
            self.publish_output_message(SENDER_ID_CHAT_RESPONSE, f"Error processing chat: {e}")


    # ... (_update_attributes_from_settings, setup_mqtt, mqtt_loop_check, on_connect, on_disconnect, on_mqtt_message) ...
    def _update_attributes_from_settings(self):
        self.mqtt_broker = self.settings.get('mqtt_broker', "localhost")
        self.mqtt_port = int(self.settings.get('mqtt_port', 1883))
        self.mqtt_output_topic = self.settings.get('mqtt_output_topic', "ai_assistant/output")
        self.mqtt_keypad_topic = self.settings.get('mqtt_keypad_topic', "ai_assistant/keypad")
        self.ollama_model = self.settings.get('ollama_model', None)
        self.ollama_server = self.settings.get('ollama_server', None)
        self.ollama_prompt = self.settings.get('ollama_prompt', 'Describe this image.')
        print("Attributes updated from settings.")

    def setup_mqtt(self):
        if self.mqtt_client:
             try:
                 self.mqtt_timer.stop()
                 self.mqtt_client.disconnect()
             except Exception as e:
                 print(f"Error disconnecting previous MQTT client: {e}")

        self.client_id = f"main_app_{os.getpid()}"
        try:
            self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id)
        except AttributeError:
             print("Warning: paho-mqtt version might be old. Using default Callback API.")
             self.mqtt_client = mqtt.Client(client_id=self.client_id)

        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_disconnect = self.on_disconnect
        self.mqtt_client.on_message = self.on_mqtt_message
        self.is_mqtt_connected = False

        try:
            print(f"Connecting to MQTT: {self.mqtt_broker}:{self.mqtt_port}")
            self.mqtt_client.connect(self.mqtt_broker, self.mqtt_port, 60)
            self.mqtt_timer.start(100)
        except Exception as e:
            self.update_status(f"Error connecting to MQTT: {e}")
            print(f"Error connecting to MQTT Broker: {e}")

    def mqtt_loop_check(self):
        if self.mqtt_client:
            try:
                self.mqtt_client.loop()
            except Exception as e:
                print(f"Error in MQTT loop check: {e}")

    def on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self.is_mqtt_connected = True
            status = f"Connected to MQTT Broker! Subscribing to {self.mqtt_keypad_topic} and {self.mqtt_output_topic}"
            print(status)
            self.update_status(status)
            client.subscribe(self.mqtt_keypad_topic)
            client.subscribe(self.mqtt_output_topic)

            if not self.initial_check_done:
                print("First connection: Triggering initial Ollama check.")
                threading.Thread(target=self.send_initial_ollama_message, daemon=True).start()
                self.initial_check_done = True
            else:
                print("Reconnected to MQTT. Skipping initial Ollama check.")

        else:
            self.is_mqtt_connected = False
            status = f"Failed to connect to MQTT, return code {rc}"
            print(status)
            self.update_status(status)

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties=None):
        self.is_mqtt_connected = False
        status = f"Disconnected from MQTT Broker (rc={str(reason_code)})."
        print(status)
        self.update_status(status)

    def on_mqtt_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode()
        print(f"Received '{payload}' on topic '{topic}'")

        if topic == self.mqtt_keypad_topic:
            if payload == "capture":
                threading.Thread(target=self.capture_and_process, daemon=True).start()
            else:
                print(f"Unhandled command '{payload}' on topic {topic}")
        elif topic == self.mqtt_output_topic:
            # Append any message from the output topic to the chat display
            self.output_message_signal.emit(payload)

    # ... (publish_output_message, send_initial_ollama_message, load_settings, save_settings, show_settings_window, start_application) ...
    def publish_output_message(self, sender_id, message):
        if self.is_mqtt_connected:
            full_message = f"{sender_id}: {message}"
            try:
                self.mqtt_client.publish(self.mqtt_output_topic, full_message, qos=0)
                print(f"Published to {self.mqtt_output_topic}: {full_message}")
            except Exception as e:
                error_msg = f"Error publishing message via MQTT: {e}"
                print(error_msg)
                self.update_status(error_msg)
        else:
            print(f"Cannot publish message, MQTT not connected: {message}")
            self.update_status("Cannot publish message, MQTT not connected.")

    def send_initial_ollama_message(self):
        if not self.ollama_model or not self.ollama_server:
            self.update_status("Ollama not configured, skipping initial check.")
            return

        self.update_status(f"Sending initial check to Ollama ({self.ollama_model})...")
        initial_prompt = "Hello! Briefly confirm you are ready."

        try:
            client = ollama.Client(host=self.ollama_server)
            messages = [{'role': 'user', 'content': initial_prompt}]
            response = client.chat(model=self.ollama_model, messages=messages)
            response_text = response['message']['content'].strip()
            self.update_status("Ollama initial check successful.")
            self.publish_output_message(SENDER_ID_INIT, response_text)
        except Exception as e:
            error_message = f"Error during Ollama initial check: {e}"
            self.update_status(error_message)
            print(error_message)
            self.publish_output_message(SENDER_ID_INIT, f"Error connecting: {e}")

    def load_settings(self):
        if os.path.exists(self.config_path):
            self.config.read(self.config_path)
            if 'DEFAULT' not in self.config:
                 self.config['DEFAULT'] = {}
            self.settings = dict(self.config['DEFAULT'])
            print(f"Loaded settings from {self.config_path}")
        else:
            print(f"Config file {self.config_path} not found. Using default settings.")
            self.settings = {
                'llm_type': 'Local Ollama', 'ollama_model': 'llava:latest',
                'ollama_server': 'http://localhost:11434', 'ollama_prompt': 'Describe this image concisely.',
                'cloud_api_key': '', 'output_screen': '0', 'mqtt_broker': 'localhost',
                'mqtt_port': '1883', 'mqtt_output_topic': "ai_assistant/output",
                'mqtt_keypad_topic': "ai_assistant/keypad"
            }

    def save_settings(self):
        if not self.settings_window:
            print("Error: Settings window not available to save from.")
            self.update_status("Error: Settings window not open.")
            return

        new_settings = self.settings_window.get_settings_values()
        self.config['DEFAULT'] = new_settings

        try:
            with open(self.config_path, 'w') as configfile:
                self.config.write(configfile)
            self.update_status("Settings saved successfully.")
            print("Settings saved.")
            self.load_settings()
            self._update_attributes_from_settings()
            self.setup_mqtt()
        except IOError as e:
            error_msg = f"Error saving settings to {self.config_path}: {e}"
            self.update_status(error_msg)
            print(error_msg)

    def show_settings_window(self):
        if self.settings_window and self.settings_window.isVisible():
            self.settings_window.activateWindow()
            self.settings_window.raise_()
        else:
            self.settings_window = SettingsWindow(self, self.start_application, self.settings)
            self.settings_window.show()

    def start_application(self):
        self.update_status("Application settings applied.")
        print("Start application callback executed.")
        self.show()

    # ... (capture_and_process, get_active_window_geometry, capture_focused_window, analyze_image, save_captured_image_async, update_status, closeEvent) ...
    def capture_and_process(self):
        self.update_status("Capturing window...")
        image = self.capture_focused_window()
        if image is None:
            self.update_status("Capture failed.")
            return

        self.save_captured_image_async(image.copy())

        self.update_status("Analyzing image...")
        analysis_result = self.analyze_image(image) # This still uses the multimodal model

        if analysis_result:
            self.update_status("Analysis complete. Publishing...")
            # Publish analysis result with its specific sender ID
            self.publish_output_message(SENDER_ID_ANALYSIS, analysis_result)
        else:
            print("Analysis did not return a result.")

    @staticmethod
    def get_active_window_geometry():
        try:
            display = Xlib.display.Display()
            root = display.screen().root
            window_id_prop = root.get_full_property(display.intern_atom('_NET_ACTIVE_WINDOW'), Xlib.X.AnyPropertyType)
            if window_id_prop is None or not window_id_prop.value:
                 print("Error: Could not get active window ID.")
                 return 0, 0, 800, 600 # Fallback
            window_id = window_id_prop.value[0]
            window = display.create_resource_object('window', window_id)
            geometry = window.get_geometry()
            coords = window.translate_coords(root, 0, 0)
            display.close()
            margin = 1
            x = max(0, coords.x - margin)
            y = max(0, coords.y - margin)
            width = geometry.width + 2 * margin
            height = geometry.height + 2 * margin
            print(f"Active window geometry: x={x}, y={y}, w={width}, h={height}")
            return x, y, width, height
        except Exception as e:
            print(f"Error getting active window geometry: {e}")
            return 0, 0, 800, 600 # Fallback

    def capture_focused_window(self):
        x, y, width, height = MainApplication.get_active_window_geometry()
        if width <= 1 or height <= 1:
             print(f"Error: Invalid window geometry for capture ({width}x{height}).")
             self.update_status("Error: Invalid window geometry.")
             return None
        try:
            region_tuple = (int(x), int(y), int(width), int(height))
            print(f"Capturing region: {region_tuple}")
            screenshot = pyautogui.screenshot(region=region_tuple)
            print("Screenshot captured successfully.")
            return screenshot
        except Exception as e:
            error_msg = f"Error capturing screenshot: {e}"
            print(error_msg)
            self.update_status(error_msg)
            return None

    def analyze_image(self, img):
        if not self.ollama_model or not self.ollama_server:
            msg = "Ollama model or server not configured."
            self.update_status(msg)
            self.publish_output_message(SENDER_ID_ANALYSIS, f"Error: {msg}")
            return None
        if img is None:
            msg = "Cannot analyze null image."
            self.update_status(msg)
            self.publish_output_message(SENDER_ID_ANALYSIS, f"Error: {msg}")
            return None

        status_msg = f"Analyzing with Ollama ({self.ollama_model})..."
        print(status_msg)
        self.update_status(status_msg)

        try:
            img_byte_arr = io.BytesIO()
            img_format = img.format if img.format else 'PNG'
            img.save(img_byte_arr, format=img_format)
            img_bytes = img_byte_arr.getvalue()

            client = ollama.Client(host=self.ollama_server)
            messages = [{'role': 'user', 'content': self.ollama_prompt, 'images': [img_bytes]}]

            print("Sending request to Ollama...")
            response = client.chat(model=self.ollama_model, messages=messages)
            print("Received response from Ollama.")

            analysis_result = response['message']['content'].strip()
            return analysis_result

        except ImportError:
             error_msg = "Error: 'ollama' library not installed. Run 'pip install ollama'."
             self.update_status(error_msg)
             print(error_msg)
             self.publish_output_message(SENDER_ID_ANALYSIS, error_msg)
             return None
        except Exception as e:
            error_message = f"Error during Ollama analysis: {e}"
            self.update_status(error_message)
            print(error_message)
            self.publish_output_message(SENDER_ID_ANALYSIS, f"Analysis failed: {e}")
            return None

    def save_captured_image_async(self, image):
        if image is None:
            return
        try:
            captures_dir = "captures"
            os.makedirs(captures_dir, exist_ok=True)
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            filename = os.path.join(captures_dir, f"capture-{timestamp}.png")
            image.save(filename)
            print(f"Saved captured image to {filename}")
        except Exception as e:
            print(f"Error saving captured image: {e}")

    def update_status(self, message):
        print(f"Status: {message}")
        self.status_update_signal.emit(message)

    def closeEvent(self, event):
        print("Closing application...")
        self.mqtt_timer.stop()
        print("MQTT timer stopped.")
        if self.mqtt_client and self.is_mqtt_connected:
            try:
                self.mqtt_client.disconnect()
                print("MQTT client disconnected.")
            except Exception as e:
                print(f"Error during MQTT disconnect: {e}")
        if self.settings_window:
            self.settings_window.close()
        event.accept()

# --- Application Entry Point ---
if __name__ == "__main__":
    multiprocessing.freeze_support()

    q_app = QApplication(sys.argv)
    main_app = MainApplication()
    main_app.show_settings_window()

    sys.exit(q_app.exec_())