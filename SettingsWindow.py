from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QComboBox, QSpinBox, QDialogButtonBox, QDialog) # Add QDialog
from PyQt5.QtCore import pyqtSlot, QTimer

class SettingsWindow(QDialog):
    def __init__(self, parent, current_settings):
        print("--- SettingsWindow (QDialog) __init__ started ---") # DEBUG
        super().__init__(parent)
        self.parent = parent
        self.current_settings = current_settings
        self.initial_settings = current_settings.copy()

        # --- Add attribute to store gathered settings ---
        self.updated_settings = None
        # ---

        try:
            self.initUI()
            print("SettingsWindow initUI finished.") # DEBUG
            # Keep timer for debugging visibility if needed
            # QTimer.singleShot(100, self.check_visibility)
        except Exception as e:
            print(f"ERROR during SettingsWindow initUI: {e}") # DEBUG
            import traceback
            traceback.print_exc() # Print full traceback
        print("--- SettingsWindow __init__ finished ---") # DEBUG

    def initUI(self):
        layout = QVBoxLayout(self)

        # --- UI setup code for fields ---
        # MQTT Broker
        self.mqtt_broker_label = QLabel("MQTT Broker:")
        self.mqtt_broker_input = QLineEdit()
        layout.addWidget(self.mqtt_broker_label)
        layout.addWidget(self.mqtt_broker_input)

        # MQTT Port
        self.mqtt_port_label = QLabel("MQTT Port:")
        self.mqtt_port_input = QSpinBox()
        self.mqtt_port_input.setRange(1, 65535)
        layout.addWidget(self.mqtt_port_label)
        layout.addWidget(self.mqtt_port_input)

        # Ollama Server
        self.ollama_server_label = QLabel("Ollama Server URL:")
        self.ollama_server_input = QLineEdit()
        layout.addWidget(self.ollama_server_label)
        layout.addWidget(self.ollama_server_input)

        # Ollama Model
        self.ollama_model_label = QLabel("Ollama Model:")
        self.ollama_model_input = QLineEdit()
        layout.addWidget(self.ollama_model_label)
        layout.addWidget(self.ollama_model_input)

        # Ollama Prompt
        self.ollama_prompt_label = QLabel("Default Analysis Prompt:")
        self.ollama_prompt_input = QLineEdit()
        layout.addWidget(self.ollama_prompt_label)
        layout.addWidget(self.ollama_prompt_input)

        # LLM Type
        self.llm_type_label = QLabel("LLM Type:")
        self.llm_type_combo = QComboBox()
        self.llm_type_combo.addItems(["Local Ollama", "Other Option"]) # Add relevant options
        layout.addWidget(self.llm_type_label)
        layout.addWidget(self.llm_type_combo)
        # --- End of field setup ---

        # --- Add a single QPushButton ---
        self.save_start_button = QPushButton("Save and Start")
        self.save_start_button.clicked.connect(self.accept_settings) # Connect to the accept slot
        layout.addWidget(self.save_start_button)
        # ---

        self.setLayout(layout)
        self.setWindowTitle("Settings")
        self.load_initial_settings() # Load settings into fields
        print(f"--- SettingsWindow: Initial sizeHint: {self.sizeHint()} ---") # DEBUG
        print(f"--- SettingsWindow: Initial minimumSizeHint: {self.minimumSizeHint()} ---") # DEBUG

    def load_initial_settings(self):
        """Load current settings into the input fields."""
        self.mqtt_broker_input.setText(self.current_settings.get('mqtt_broker', 'localhost'))
        # Ensure port is loaded as int for QSpinBox
        try:
            port = int(self.current_settings.get('mqtt_port', 1883))
        except (ValueError, TypeError):
            port = 1883 # Default if conversion fails
        self.mqtt_port_input.setValue(port)
        self.ollama_server_input.setText(self.current_settings.get('ollama_server', ''))
        self.ollama_model_input.setText(self.current_settings.get('ollama_model', ''))
        self.ollama_prompt_input.setText(self.current_settings.get('ollama_prompt', 'Describe this image.'))
        self.llm_type_combo.setCurrentText(self.current_settings.get('llm_type', 'Local Ollama'))

    @pyqtSlot()
    def accept_settings(self):
        """Gather settings from fields and then accept the dialog."""
        print("--- SettingsWindow accept_settings called ---") # DEBUG
        self.updated_settings = { # Store gathered settings
            'mqtt_broker': self.mqtt_broker_input.text(),
            'mqtt_port': str(self.mqtt_port_input.value()), # Convert port back to string for saving
            'ollama_server': self.ollama_server_input.text(),
            'ollama_model': self.ollama_model_input.text(),
            'ollama_prompt': self.ollama_prompt_input.text(),
            'llm_type': self.llm_type_combo.currentText()
        }
        print("Gathered settings:", self.updated_settings) # DEBUG
        # Call QDialog's accept() method to close the dialog with Accepted status
        self.accept()

    # Optional: Keep for debugging visibility issues if they reappear
    @pyqtSlot()
    def check_visibility(self):
        print("--- SettingsWindow: check_visibility Timer Fired ---") # DEBUG
        print(f"  isVisible(): {self.isVisible()}") # DEBUG
        print(f"  geometry(): {self.geometry()}") # DEBUG
        print(f"  size(): {self.size()}") # DEBUG
        print(f"  windowState(): {self.windowState()}") # DEBUG
        if self.parent:
             print(f"  parent.isVisible(): {self.parent.isVisible()}") # DEBUG
