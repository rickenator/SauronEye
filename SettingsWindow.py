from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QComboBox, QLineEdit,
                             QPushButton, QLabel, QSpinBox, QGroupBox) # Added QGroupBox
from PyQt5.QtCore import Qt

class SettingsWindow(QWidget):
    # Add 'parent' argument to __init__
    def __init__(self, parent, start_callback, current_settings):
        super().__init__()
        self.parent = parent # Store the MainApplication instance
        self.start_callback = start_callback
        self.current_settings = current_settings
        self.initUI()

    def initUI(self):
        # --- LLM Settings ---
        llm_group_box = QGroupBox("LLM Configuration")
        llm_layout = QFormLayout()

        self.llm_type_combo = QComboBox()
        self.llm_type_combo.addItems(["Local Ollama", "Cloud API"])
        self.llm_type_combo.currentTextChanged.connect(self.update_llm_fields)
        llm_layout.addRow("LLM Type:", self.llm_type_combo)

        self.ollama_model_input = QLineEdit()
        llm_layout.addRow("Ollama Model:", self.ollama_model_input)

        self.ollama_server_input = QLineEdit()
        llm_layout.addRow("Ollama Server URL:", self.ollama_server_input)

        # Add Ollama Prompt field
        self.ollama_prompt_input = QLineEdit()
        llm_layout.addRow("Ollama Prompt:", self.ollama_prompt_input)


        self.cloud_api_key_input = QLineEdit()
        self.cloud_api_key_input.setEchoMode(QLineEdit.Password)
        llm_layout.addRow("Cloud API Key:", self.cloud_api_key_input)

        llm_group_box.setLayout(llm_layout)

        # --- MQTT Settings ---
        mqtt_group_box = QGroupBox("MQTT Configuration")
        mqtt_layout = QFormLayout()

        self.mqtt_broker_input = QLineEdit()
        mqtt_layout.addRow("Broker Address:", self.mqtt_broker_input)

        self.mqtt_port_input = QLineEdit()
        # Consider using QSpinBox for port if validation is desired
        # self.mqtt_port_input = QSpinBox()
        # self.mqtt_port_input.setRange(1, 65535)
        mqtt_layout.addRow("Broker Port:", self.mqtt_port_input)

        self.mqtt_output_topic_input = QLineEdit()
        mqtt_layout.addRow("Output Topic:", self.mqtt_output_topic_input)

        self.mqtt_keypad_topic_input = QLineEdit()
        mqtt_layout.addRow("Keypad Topic:", self.mqtt_keypad_topic_input)

        mqtt_group_box.setLayout(mqtt_layout)


        # --- Other Settings ---
        other_group_box = QGroupBox("Other Settings")
        other_layout = QFormLayout()
        self.output_screen_spinbox = QSpinBox()
        self.output_screen_spinbox.setRange(0, 10) # Adjust range as needed
        other_layout.addRow("Output Screen Index:", self.output_screen_spinbox)
        other_group_box.setLayout(other_layout)


        # --- Buttons ---
        self.save_button = QPushButton("Save & Start Application")
        self.save_button.clicked.connect(self.save_and_start) # Connect to the combined method

        # --- Layout ---
        main_layout = QVBoxLayout()
        main_layout.addWidget(llm_group_box)
        main_layout.addWidget(mqtt_group_box)
        main_layout.addWidget(other_group_box)
        main_layout.addWidget(self.save_button)
        self.setLayout(main_layout)

        self.setWindowTitle("SauronEye Settings")
        self.load_initial_settings() # Load settings into fields
        self.update_llm_fields(self.llm_type_combo.currentText()) # Set initial field visibility


    def load_initial_settings(self):
        """Loads current settings into the input fields."""
        self.llm_type_combo.setCurrentText(self.current_settings.get('llm_type', 'Local Ollama'))
        self.ollama_model_input.setText(self.current_settings.get('ollama_model', ''))
        self.ollama_server_input.setText(self.current_settings.get('ollama_server', 'http://localhost:11434'))
        self.ollama_prompt_input.setText(self.current_settings.get('ollama_prompt', 'Describe this image concisely.')) # Load prompt
        self.cloud_api_key_input.setText(self.current_settings.get('cloud_api_key', ''))
        self.output_screen_spinbox.setValue(int(self.current_settings.get('output_screen', 0)))
        self.mqtt_broker_input.setText(self.current_settings.get('mqtt_broker', 'localhost'))
        self.mqtt_port_input.setText(self.current_settings.get('mqtt_port', '1883'))
        self.mqtt_output_topic_input.setText(self.current_settings.get('mqtt_output_topic', 'ai_assistant/output'))
        self.mqtt_keypad_topic_input.setText(self.current_settings.get('mqtt_keypad_topic', 'ai_assistant/keypad'))


    def update_llm_fields(self, llm_type):
        """Shows/hides fields based on selected LLM type."""
        is_ollama = (llm_type == "Local Ollama") # Correct variable name
        self.ollama_model_input.setVisible(is_ollama) # Use is_ollama
        self.ollama_server_input.setVisible(is_ollama) # Use is_ollama
        self.ollama_prompt_input.setVisible(is_ollama) # Use is_ollama
        # Find the labels associated with the inputs to hide them too
        # Ensure layout() and labelForField() work as expected in your setup
        if self.layout() and hasattr(self.layout(), 'labelForField'):
             label_model = self.layout().labelForField(self.ollama_model_input)
             if label_model: label_model.setVisible(is_ollama) # Use is_ollama
             label_server = self.layout().labelForField(self.ollama_server_input)
             if label_server: label_server.setVisible(is_ollama) # Use is_ollama
             label_prompt = self.layout().labelForField(self.ollama_prompt_input)
             if label_prompt: label_prompt.setVisible(is_ollama) # Use is_ollama

        is_cloud = (llm_type == "Cloud API")
        self.cloud_api_key_input.setVisible(is_cloud)
        if self.layout() and hasattr(self.layout(), 'labelForField'):
            label_api_key = self.layout().labelForField(self.cloud_api_key_input)
            if label_api_key: label_api_key.setVisible(is_cloud)


    # This method is called when the button is clicked
    def save_and_start(self):
        # Call the parent's (MainApplication) save_settings method FIRST
        self.parent.save_settings()
        # Then call the original start callback (MainApplication.start_application)
        if self.start_callback:
            self.start_callback()
        self.close() # Close the settings window after saving/starting


    # Remove the empty save_settings method
    # def save_settings(self):
    #     # Not needed now, saving is handled by MainApplication
    #     pass

    # Add methods to get current values from fields (used by MainApplication.save_settings)
    def get_settings_values(self):
        return {
            'llm_type': self.llm_type_combo.currentText(),
            'ollama_model': self.ollama_model_input.text(),
            'ollama_server': self.ollama_server_input.text(),
            'ollama_prompt': self.ollama_prompt_input.text(), # Get prompt value
            'cloud_api_key': self.cloud_api_key_input.text(),
            'output_screen': str(self.output_screen_spinbox.value()),
            'mqtt_broker': self.mqtt_broker_input.text(),
            'mqtt_port': self.mqtt_port_input.text(), # Port is usually saved as string in ini
            'mqtt_output_topic': self.mqtt_output_topic_input.text(),
            'mqtt_keypad_topic': self.mqtt_keypad_topic_input.text()
        }