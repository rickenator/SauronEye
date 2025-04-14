import sys
import ollama
import io
import multiprocessing
import time
from SettingsWindow import SettingsWindow
from configparser import ConfigParser
import os
import threading
import signal
import uuid
import glob
from pydbus import SessionBus
# --- GStreamer/GObject Imports ---
try:
    import gi
    gi.require_version('Gst', '1.0')
    gi.require_version('GstBase', '1.0')
    from gi.repository import GLib, GObject, Gst
    # Initialize GStreamer here (or ensure ScreenCastHandler does)
    Gst.init(None)
    print("GStreamer initialized successfully.")
except ImportError:
    print("ERROR: Failed to import GObject/GStreamer bindings.")
    print("Please ensure PyGObject and GStreamer Python bindings are installed.")
    # Optionally exit or disable capture functionality
    sys.exit(1)
# --- End GStreamer/GObject Imports ---

from PyQt5.QtWidgets import (QApplication, QMainWindow, QTextEdit, QStatusBar,
                             QPushButton, QWidget, QVBoxLayout, QHBoxLayout, QDialog)
from PyQt5.QtCore import pyqtSignal, QObject, pyqtSlot, QTimer
import paho.mqtt.client as mqtt

# --- Import the new handler ---
from ScreenCastHandler import ScreenCastHandler
# ---

# --- Constants ---
SENDER_ID_MAIN = "[SauronEye-Main]"
SENDER_ID_INIT = "[SauronEye-Init]"
SENDER_ID_ANALYSIS = "[SauronEye-Analysis]"
SENDER_ID_USER = "[User]"
SENDER_ID_CHAT_RESPONSE = "[LLM-Chat]"

class MainApplication(QMainWindow):
    status_update_signal = pyqtSignal(str)
    output_message_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        # self.settings_window = None # Not needed if creating dialog fresh each time
        self.settings = {}
        self.config = ConfigParser()
        self.config_path = "config.ini"
        self.load_settings()
        self._update_attributes_from_settings()
        self.initial_check_done = False
        # self.start_application_callback = self.start_application # Not needed with QDialog flow

        self.setWindowTitle("SauronEye Chat")
        self.statusBar = QStatusBar(self)
        self.setStatusBar(self.statusBar)

        self.chat_display = QTextEdit(self)
        self.chat_display.setReadOnly(True)
        self.chat_input = QTextEdit(self)
        self.chat_input.setFixedHeight(60)
        self.send_button = QPushButton("Send", self)
        self.send_button.clicked.connect(self.handle_send_button)

        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        input_layout = QHBoxLayout()
        input_layout.addWidget(self.chat_input)
        input_layout.addWidget(self.send_button)
        main_layout.addWidget(self.chat_display)
        main_layout.addLayout(input_layout)
        self.setCentralWidget(central_widget)

        self.status_update_signal.connect(self.update_status_bar)
        self.output_message_signal.connect(self.display_output_message)

        # --- Initialize ScreenCastHandler ---
        self.screen_cast_handler = ScreenCastHandler(self)
        self.screen_cast_handler.capture_successful.connect(self.on_capture_successful)
        self.screen_cast_handler.capture_failed.connect(self.on_capture_failed)
        # ---

        self.mqtt_client = None
        self.is_mqtt_connected = False
        self.mqtt_timer = QTimer(self)
        self.mqtt_timer.timeout.connect(self.mqtt_loop_check)
        # Don't setup MQTT until settings are confirmed
        # self.setup_mqtt()

        print("MainApplication __init__ finished.") # DEBUG

    def show_settings_window(self):
        """Creates and executes the modal settings dialog."""
        print("--- show_settings_window called ---") # DEBUG
        print("Creating SettingsWindow (QDialog)...") # DEBUG
        try:
            # Pass only parent and current settings
            settings_dialog = SettingsWindow(self, self.settings)
            print("SettingsWindow created.") # DEBUG

            print("Calling SettingsWindow.exec_()...") # DEBUG
            # Execute modally
            result = settings_dialog.exec_()
            print(f"SettingsWindow.exec_() finished with result: {result}") # DEBUG

            # Check if user clicked Save (Accepted)
            if result == QDialog.Accepted:
                print("Settings dialog accepted.") # DEBUG
                # Retrieve settings from the dialog's attribute
                new_settings = settings_dialog.updated_settings
                if new_settings:
                    print("Applying updated settings...") # DEBUG
                    self.settings = new_settings # Apply the retrieved settings
                    self.save_settings()
                    self._update_attributes_from_settings()
                    self.setup_mqtt() # Setup/Reconnect MQTT *after* settings are confirmed

                    # Show the main window AFTER settings are accepted
                    print("Settings accepted, showing main application window...") # DEBUG
                    self.show() # Show the main QMainWindow

                    # Trigger initial check AFTER showing main window and setting up MQTT
                    # Use a short delay to ensure MQTT has a chance to connect
                    QTimer.singleShot(500, self.trigger_initial_check)

                else:
                     print("WARNING: Settings dialog accepted but no updated_settings found.") # DEBUG
            else:
                print("Settings dialog rejected or closed.") # DEBUG
                # Close the main application window, terminating the app.
                self.close()

        except Exception as e:
            print(f"ERROR during settings dialog execution: {e}") # DEBUG
            import traceback
            traceback.print_exc() # Print full traceback

    def trigger_initial_check(self):
        """Checks MQTT connection and starts Ollama check if ready."""
        if not self.initial_check_done and self.is_mqtt_connected:
            print("Starting initial Ollama check thread after settings accept...") # DEBUG
            threading.Thread(target=self.send_initial_ollama_message, daemon=True).start()
            self.initial_check_done = True
        elif not self.is_mqtt_connected:
             print("MQTT not connected after settings accept, skipping initial check.") # DEBUG


    @pyqtSlot(str)
    def update_status_bar(self, message):
        if hasattr(self, 'statusBar'):
            self.statusBar.showMessage(message, 5000)

    def load_settings(self):
        """Loads settings from the config file."""
        self.config.read(self.config_path)
        # Prioritize [Settings] section if it exists
        if 'Settings' in self.config:
            self.settings = dict(self.config['Settings'])
            print(f"Loaded settings from [Settings] section in {self.config_path}")
        # Otherwise, try to use [DEFAULT]
        elif 'DEFAULT' in self.config:
             # Read keys directly from the DEFAULT section proxy
             default_settings = {}
             for key in self.config['DEFAULT']:
                 default_settings[key] = self.config['DEFAULT'][key]
             self.settings = default_settings
             print(f"Loaded settings from [DEFAULT] section in {self.config_path}")
        # Fallback if neither section exists
        else:
            print(f"Warning: No [Settings] or [DEFAULT] section found in {self.config_path}. Using hardcoded defaults.")
            self.settings = {
                'mqtt_broker': 'localhost',
                'mqtt_port': '1883',
                'mqtt_output_topic': 'ai_assistant/output',
                'mqtt_keypad_topic': 'ai_assistant/keypad',
                'ollama_model': '',
                'ollama_server': '',
                'ollama_prompt': 'Describe this image.',
                'llm_type': 'Local Ollama' # Add any other expected keys
            }
            # Optionally create the file with defaults
            # self.config['Settings'] = self.settings
            # self.save_settings()

    def save_settings(self):
        """Saves current settings to the config file."""
        try:
            # Ensure the [Settings] section exists before assigning
            if 'Settings' not in self.config:
                self.config.add_section('Settings')
            # Update the [Settings] section (overwrites if exists)
            self.config['Settings'] = self.settings
            with open(self.config_path, 'w') as configfile:
                self.config.write(configfile)
            self.update_status(f"Settings saved to {self.config_path}")
        except Exception as e:
            self.update_status(f"Error saving settings: {e}")

    # REMOVED on_settings_saved method as it's not used with QDialog.exec_()

    # start_application method is effectively replaced by the logic within show_settings_window after QDialog.Accepted

    def send_initial_ollama_message(self):
        """Sends an initial availability message via Ollama."""
        if not self.ollama_model or not self.ollama_server:
            self.update_status("Ollama not configured for initial check.")
            return

        self.update_status(f"Sending initial check to Ollama ({self.ollama_model})...")
        try:
            client = ollama.Client(host=self.ollama_server)
            # Simple prompt to confirm Ollama is working
            init_prompt = "You are SauronEye, an AI assistant integrated into a desktop application. Respond with a brief greeting confirming you are ready."
            messages = [{'role': 'user', 'content': init_prompt}]
            response = client.chat(model=self.ollama_model, messages=messages)
            response_text = response['message']['content'].strip()
            # Publish the greeting
            self.publish_output_message(SENDER_ID_INIT, response_text)
            self.update_status("Ollama initial check successful.")
        except Exception as e:
            self.update_status(f"Error during Ollama initial check: {e}")
            self.publish_output_message(SENDER_ID_INIT, f"Error contacting Ollama: {e}")

    def publish_output_message(self, sender_id, message):
        """Publishes a formatted message to the MQTT output topic."""
        if self.mqtt_client and self.is_mqtt_connected:
            full_message = f"{sender_id}: {message}"
            try:
                self.mqtt_client.publish(self.mqtt_output_topic, full_message)
                # Also display locally via signal for safety
                self.output_message_signal.emit(full_message)
            except Exception as e:
                self.update_status(f"Error publishing MQTT message: {e}")
        else:
            self.update_status("Cannot publish MQTT message: Not connected.")
            # Display locally even if not connected
            self.output_message_signal.emit(f"{sender_id} (MQTT disconnected): {message}")

    @pyqtSlot(str)
    def display_output_message(self, message):
        if hasattr(self, 'chat_display'):
            self.chat_display.append(message)
        else:
            print(f"Debug: chat_display widget not found. Message: {message}")

    @pyqtSlot()
    def handle_send_button(self):
        user_message = self.chat_input.toPlainText().strip()
        if not user_message:
            return
        self.chat_input.clear()
        self.publish_output_message(SENDER_ID_USER, user_message)
        threading.Thread(target=self.send_chat_message_to_ollama, args=(user_message,), daemon=True).start()

    def send_chat_message_to_ollama(self, user_message):
        if not self.ollama_model or not self.ollama_server:
            self.update_status("Ollama not configured for chat.")
            self.publish_output_message(SENDER_ID_CHAT_RESPONSE, "Error: Ollama not configured.")
            return

        self.update_status(f"Sending chat message to Ollama ({self.ollama_model})...")
        try:
            client = ollama.Client(host=self.ollama_server)
            messages = [{'role': 'user', 'content': user_message}]
            response = client.chat(model=self.ollama_model, messages=messages)
            response_text = response['message']['content'].strip()
            self.update_status("Ollama chat response received.")
            self.publish_output_message(SENDER_ID_CHAT_RESPONSE, response_text)
        except Exception as e:
            self.update_status(f"Error during Ollama chat: {e}")
            self.publish_output_message(SENDER_ID_CHAT_RESPONSE, f"Error processing chat: {e}")

    def _update_attributes_from_settings(self):
        self.mqtt_broker = self.settings.get('mqtt_broker', "localhost")
        # Handle potential errors converting port
        try:
            self.mqtt_port = int(self.settings.get('mqtt_port', 1883))
        except (ValueError, TypeError):
            self.mqtt_port = 1883 # Default if conversion fails
        self.mqtt_output_topic = self.settings.get('mqtt_output_topic', "ai_assistant/output")
        self.mqtt_keypad_topic = self.settings.get('mqtt_keypad_topic', "ai_assistant/keypad")
        self.ollama_model = self.settings.get('ollama_model', '') # Use empty string default
        self.ollama_server = self.settings.get('ollama_server', '') # Use empty string default
        self.ollama_prompt = self.settings.get('ollama_prompt', 'Describe this image.')
        print("--- Attributes updated from settings ---") # DEBUG
        print(f"  MQTT Broker: {self.mqtt_broker}")      # DEBUG
        print(f"  MQTT Port: {self.mqtt_port}")          # DEBUG
        print(f"  Ollama Server: '{self.ollama_server}'") # DEBUG
        print(f"  Ollama Model: '{self.ollama_model}'")   # DEBUG
        print(f"  Ollama Prompt: {self.ollama_prompt}")   # DEBUG
        print("--------------------------------------") # DEBUG

    def setup_mqtt(self):
        from paho.mqtt.client import CallbackAPIVersion
        if self.mqtt_client:
            try:
                self.mqtt_timer.stop()
                self.mqtt_client.disconnect()
                self.mqtt_client.loop_stop() # Ensure loop stops if running
            except Exception as e:
                print(f"Error disconnecting previous MQTT client: {e}")
        self.client_id = f"main_app_{os.getpid()}_{uuid.uuid4()}" # More unique client ID
        try:
            self.mqtt_client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=self.client_id)
            print("Using Paho MQTT Callback API V2") # DEBUG
        except AttributeError:
            self.mqtt_client = mqtt.Client(client_id=self.client_id)
            print("Using Paho MQTT Callback API V1 (legacy)") # DEBUG
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_disconnect = self.on_disconnect
        self.mqtt_client.on_message = self.on_mqtt_message
        try:
            print(f"Connecting to MQTT: {self.mqtt_broker}:{self.mqtt_port}")
            self.mqtt_client.connect_async(self.mqtt_broker, self.mqtt_port, 60) # Use connect_async
            self.mqtt_client.loop_start() # Start network loop in background thread
            self.mqtt_timer.start(100) # Keep timer for other checks if needed, but loop_start handles network
        except Exception as e:
            self.update_status(f"Error connecting to MQTT: {e}")

    def mqtt_loop_check(self):
        # This might not be strictly necessary if using loop_start()
        # but can be used for checking connection status or other periodic tasks
        if self.mqtt_client and not self.is_mqtt_connected:
            # Optionally attempt reconnect here if loop_start isn't handling it
            print("MQTT loop check: Client exists but not connected.")
            pass
        elif not self.mqtt_client:
            print("MQTT loop check: Client does not exist.")

    def on_connect(self, client, userdata, flags, rc, properties=None):
        connect_successful = False
        reason_string = str(rc)
        if isinstance(rc, int): # V1 API
            connect_successful = (rc == 0)
            reason_string = mqtt.connack_string(rc)
        else: # V2 API
            if hasattr(rc, 'is_success'):
                connect_successful = rc.is_success
            else:
                connect_successful = (rc == 0)

        self.is_mqtt_connected = connect_successful

        if self.is_mqtt_connected:
            status = f"Connected to MQTT Broker! Subscribing to {self.mqtt_keypad_topic} and {self.mqtt_output_topic}"
            self.update_status(status)
            # Subscribe with error handling
            try:
                res_keypad = client.subscribe(self.mqtt_keypad_topic)
                res_output = client.subscribe(self.mqtt_output_topic)
                if res_keypad[0] != mqtt.MQTT_ERR_SUCCESS:
                    print(f"Warning: Failed to subscribe to {self.mqtt_keypad_topic}, rc={res_keypad[0]}")
                if res_output[0] != mqtt.MQTT_ERR_SUCCESS:
                    print(f"Warning: Failed to subscribe to {self.mqtt_output_topic}, rc={res_output[0]}")
            except Exception as e:
                print(f"Error during MQTT subscribe: {e}")

            # Initial check is now triggered by trigger_initial_check after dialog closes
            # if not self.initial_check_done: ...
        else:
            self.update_status(f"Failed to connect to MQTT Broker ({reason_string}).")

    def on_disconnect(self, client, userdata, rc, properties=None):
        reason_string = str(rc)
        if isinstance(rc, int): # V1 API
             reason_string = f"rc={rc}"

        self.is_mqtt_connected = False
        # Only update status if rc indicates an unexpected disconnect (rc != 0)
        # Normal disconnect (rc=0) happens during shutdown.
        if rc != 0:
            self.update_status(f"Unexpectedly disconnected from MQTT Broker ({reason_string}).")
        else:
            print("Disconnected from MQTT Broker normally.")

    def on_mqtt_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = msg.payload.decode()
            print(f"MQTT Message Received: Topic='{topic}', Payload='{payload}'") # DEBUG
            if topic == self.mqtt_keypad_topic and payload == "capture":
                print("Capture command received via MQTT.") # DEBUG
                # Use QTimer.singleShot to ensure capture runs in main thread
                QTimer.singleShot(0, self.capture_and_process)
            elif topic == self.mqtt_output_topic:
                # Use signal to safely update GUI from MQTT thread
                self.output_message_signal.emit(payload)
        except Exception as e:
            print(f"Error processing MQTT message on topic {topic}: {e}")


    def capture_and_process(self):
        """Initiates screen capture. Runs in the main thread."""
        self.update_status("Initiating window capture via ScreenCast portal...")
        self.screen_cast_handler.start_capture()

    @pyqtSlot(object) # Receives PIL Image
    def on_capture_successful(self, image):
        """Handles successful capture. Runs in the main thread."""
        self.update_status("Window capture successful.")
        try:
            # Save a copy asynchronously
            self.save_captured_image_async(image.copy())
            self.update_status("Analyzing captured image...")
            # Move analysis to background thread
            threading.Thread(target=self.run_analysis, args=(image,), daemon=True).start()
        except Exception as e:
            self.update_status(f"Error processing captured image: {e}")
            import traceback
            traceback.print_exc()

    @pyqtSlot(str)
    def on_capture_failed(self, error_message):
        """Handles failed capture. Runs in the main thread."""
        self.update_status(f"Capture failed: {error_message}")

    def run_analysis(self, image):
        """Performs image analysis in a background thread."""
        try:
            result = self.analyze_image(image)
            if result:
                self.update_status("Analysis complete. Publishing...")
                self.publish_output_message(SENDER_ID_ANALYSIS, result)
            else:
                 self.update_status("Analysis failed or produced no result.")
        except Exception as e:
             self.update_status(f"Error during analysis thread: {e}")
             import traceback
             traceback.print_exc()

    def analyze_image(self, img):
        """Sends image to Ollama for analysis."""
        if not self.ollama_model or not self.ollama_server:
            self.update_status("Ollama model or server not configured.")
            return None
        try:
            img_byte_arr = io.BytesIO()
            if img.mode != 'RGB':
                 img = img.convert('RGB')
            img.save(img_byte_arr, format='PNG')
            img_bytes = img_byte_arr.getvalue()
            client = ollama.Client(host=self.ollama_server)
            response = client.chat(model=self.ollama_model, messages=[{'role': 'user', 'content': self.ollama_prompt, 'images': [img_bytes]}])
            return response['message']['content'].strip()
        except Exception as e:
            self.update_status(f"Error during image analysis: {e}")
            import traceback
            traceback.print_exc()
            return None

    def save_captured_image_async(self, image):
        threading.Thread(target=self._save_image_sync, args=(image,), daemon=True).start()

    def _save_image_sync(self, image):
        """Synchronous part of saving the image."""
        try:
            os.makedirs("captures", exist_ok=True)
            timestamp = time.strftime('%Y%m%d-%H%M%S')
            capture_files = sorted(glob.glob(os.path.join("captures", "capture-*.png")))
            while len(capture_files) >= 5:
                os.remove(capture_files.pop(0))
            filename = f"capture-{timestamp}.png"
            filepath = os.path.join("captures", filename)
            image.save(filepath)
            print(f"Saved captured image to {filepath}") # DEBUG
        except Exception as e:
            print(f"Error saving captured image: {e}")
            import traceback
            traceback.print_exc()

    def update_status(self, message):
        print(f"Status: {message}")
        self.status_update_signal.emit(message)

    def closeEvent(self, event):
        print("Closing application...")
        if hasattr(self, 'screen_cast_handler') and self.screen_cast_handler:
            self.screen_cast_handler.cleanup()
        if hasattr(self, 'mqtt_timer') and self.mqtt_timer.isActive():
            self.mqtt_timer.stop()
        if hasattr(self, 'mqtt_client') and self.mqtt_client:
            # Stop the background loop first
            self.mqtt_client.loop_stop()
            # Disconnect might take a moment, loop_stop helps ensure clean shutdown
            try:
                # No need to check is_mqtt_connected, just attempt disconnect
                self.mqtt_client.disconnect()
                print("MQTT client disconnect requested.")
            except Exception as e:
                print(f"Error during MQTT disconnect: {e}")
        # No need to close settings_window explicitly if using QDialog.exec_()
        # if hasattr(self, 'settings_window') and self.settings_window:
        #     self.settings_window.close()
        event.accept()


# --- Corrected if __name__ == "__main__": block ---
if __name__ == "__main__":
    multiprocessing.freeze_support()
    print("Creating QApplication...") # DEBUG
    q_app = QApplication(sys.argv)

    # --- Add SIGINT Handler (KEEP THIS) ---
    def sigint_handler(*args):
        """Handler for the SIGINT signal."""
        print("\nCtrl+C detected. Shutting down...")
        QApplication.quit() # Triggers closeEvent

    signal.signal(signal.SIGINT, sigint_handler)
    # --- End SIGINT Handler ---

    # --- GLib Main Loop Integration (KEEP/ADD THIS) ---
    # Use a timer to periodically run the GLib default main context iteration.
    # This allows DBus signals and GStreamer messages to be processed
    # without blocking the Qt event loop or needing a separate GLib loop thread.
    glib_loop_timer = QTimer()
    glib_loop_timer.timeout.connect(lambda: GLib.MainContext.default().iteration(may_block=False))
    glib_loop_timer.start(50) # Check every 50ms
    # --- End GLib Main Loop Integration ---

    print("Creating MainApplication...") # DEBUG
    main_app = MainApplication() # Create instance (it's hidden by default)

    # --- Delay showing settings window until event loop starts ---
    print("Scheduling main_app.show_settings_window() via QTimer...") # DEBUG
    QTimer.singleShot(0, main_app.show_settings_window) # Delay = 0ms, runs ASAP after loop starts
    # ---

    print("Starting QApplication event loop (q_app.exec_())...") # DEBUG
    exit_code = q_app.exec_()
    print(f"QApplication event loop finished with exit code: {exit_code}") # DEBUG
    sys.exit(exit_code)
# --- End of file ---