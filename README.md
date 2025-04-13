# AI Assistant - Focused Window Analysis

This Python-based application captures the currently focused window on your desktop, sends its contents to an LLM (Local Ollama or Cloud API), and displays the LLM's response in a dedicated output window. It is an IoT AI controlled via shorcuts on the numerical keypad, or by another IoT device, making it unobtrusive and efficient to use.

## Prerequisites
*   **Linux Desktop:** It uses Qt, but I only targeted and tested on Ubuntu 24.04 with Gnome Desktop.
*   **Python 3.x:**  Ensure you have Python 3 installed.
*   **MQTT Broker:** A Mosquitto MQTT or similar broker running on your network.
*   **Ollama Server:** Uses a local LLM, ensure your Ollama server is running and accessible. Cloud AI TBD.
*   **Dependencies:** Install the required Python libraries:

    ```bash
    pip install -r requirements.txt
    ```

## Installation

1.  **Clone the repository:**

    ```bash
    git clone <repository_url>
    cd <repository_directory>
    ```

2.  **Configuration:**
    *   Create a `config.ini` file in the project directory. Use the example provided below and adapt it to your setup.

    ```ini
    [DEFAULT]
    llm_type = Local Ollama
    ollama_model = mistralai/Mistral-7B-Instruct-v0.1
    ollama_server = http://localhost:11434
    cloud_api_key =
    output_screen = 0
    mqtt_broker = localhost
    mqtt_port = 1883
    mqtt_output_topic = ai_assistant/output
    mqtt_keypad_topic = ai_assistant/keypad
    ```

    *   **`llm_type`:**  Choose either `Local Ollama` or `Cloud API`.
    *   **`ollama_model`:**  The name of the Ollama model to use (e.g., `mistralai/Mistral-7B-Instruct-v0.1`).
    *   **`ollama_server`:**  The URL of your Ollama server (e.g., `http://localhost:11434`).
    *   **`cloud_api_key`:** Your API key for the cloud LLM provider (if using).
    *   **`output_screen`:** The screen number to display the output window (0 for the primary screen, 1 for the secondary screen, etc.).
    *   **`mqtt_broker`:**  The hostname or IP address of your MQTT broker.
    *   **`mqtt_port`:**  The port of your MQTT broker (usually 1883).
    *   **`mqtt_output_topic`:**  The MQTT topic to use for publishing LLM output.
    *   **`mqtt_keypad_topic`:**  The MQTT topic to use for publishing keypad commands.

3.  **Run the Application:**

    ```bash
    python MainApplication.py
    ```

## Usage

1.  **Settings Window:**
    *   The application will start with a settings window.
    *   Configure the settings according to your setup.
    *   Click "Save" to persist the settings.
    *   Click "Start" to launch the application.

2.  **Output Window:**
    *   A full-screen output window will appear on the specified screen.

3.  **Keypad Control:**
    *   Ensure that the keypad listener script (`keypad_listener.py`) is running in the background (see below).
    *   Use the following keys on the numeric keypad to control the application:
        *   `Enter`: Capture the focused window, send it to the LLM, and display the response in the output window.
        *   `4`, `6`, `8`, `2`, `Insert`, `Delete`, `Home`, `End`, `PageUp`, `PageDown` - (To be implemented)

## Concept: The SauronEye Assistant

SauronEye acts like an AI assistant "looking over your shoulder". It's designed to be non-intrusive:

*   **Focused Window Analysis:** It captures only the currently active window, not your entire desktop.
*   **Secondary Screen Output (Optional):** The analysis results can be displayed in a dedicated window, potentially on a secondary monitor, keeping your primary workspace clear.
*   **IoT AI:** Subscribe to the topic 'ai_assistant/output' from another device on your network, such as your smartphone for viewing and control.
*  **Keyboard Shortcuts:** It uses the numeric keypad for commands, allowing you to trigger analysis without disrupting your workflow.
*   **Non-Intrusive:** It doesn't interfere with your main applications. You can continue working while SauronEye captures and analyzes the focused window.
*   **Keypad Control:** It uses the numeric keypad for commands. This avoids interfering with standard keyboard shortcuts and mouse actions in your main applications. You can trigger analysis or control the output window without disrupting your primary task.
*   **Multimodal Power:** It sends the captured image to a multimodal LLM (like Llava via Ollama), which can understand both the text and the visual context (e.g., code structure, layout, diagrams) to provide more relevant assistance than simple OCR.

**Example Use Case:** Imagine you're chatting with coworkers and encounter a complex code snippet or a confusing error message. Instead of manually copying text or describing the problem, you simply ensure the chat window is active and press `Enter` on the numeric keypad. SauronEye captures the window, sends it to the LLM, and displays the explanation or solution in its dedicated output window (perhaps on your other monitor).

## Workflow

1.  **Prerequisites:** Ensure Python, required libraries (`pip install -r requirements.txt`), an MQTT broker (like Mosquitto), and Ollama (with a suitable multimodal model like `llava`) are installed and running. The `scrot` utility is also needed for `pyautogui` screenshots on Linux.
2.  **Run Keyboard Listener:** The listener requires root privileges to capture global key presses. Open a terminal and run:
    ```bash
    sudo python KeyboardListener.py
    ```
    This script listens for specific keys on the numeric keypad in the background and sends commands via MQTT.
3.  **Run Main Application:** Open another terminal and run the main GUI application:
    ```bash
    python MainApplication.py
    ```
4.  **Configure Settings (First Run):**
    *   The Settings window will appear.
    *   Configure Ollama (Server URL, Model, Prompt), MQTT (Broker, Port, Topics), and optionally the Output Screen index if you have multiple monitors.
    *   Click "Save & Start Application". Settings are saved to `config.ini`. The main application window will appear (this window primarily shows the latest analysis result).
5.  **Capture & Analyze:**
    *   Make the window you want to analyze the currently active/focused window on your desktop.
    *   Press the `Enter` key on the numeric keypad.
6.  **View Results:**
    *   The main application captures the focused window's content.
    *   It sends the image and your configured prompt to the Ollama LLM.
    *   The text analysis returned by Ollama appears in the main application's text area.
    *   *(Future Implementation)*: The analysis might also appear in a dedicated full-screen output window on the configured screen.
    *   The analysis text is also published to the configured output MQTT topic.
    *   A copy of the captured image is saved in the `captures/` directory.
7.  **Other Keypad Commands (Partially Implemented):**
    *   Other numeric keypad keys (`4`, `6`, `8`, `2`, `Insert`, `Delete`, etc.) send corresponding commands ("scroll\_left", "copy", etc.) via MQTT.
    *   These are intended to control the dedicated output window (scrolling, copying text) without affecting your main focused application. The handling of these commands in `MainApplication.py` needs further implementation.
8.  **TODO:**
    *   Chat/Text input to AI response window.
