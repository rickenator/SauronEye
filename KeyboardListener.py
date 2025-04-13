import keyboard
import paho.mqtt.client as mqtt
import time
import subprocess
import os
import uuid
from configparser import ConfigParser # Added

# --- Configuration Loading ---
CONFIG_PATH = "config.ini"
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "ai_assistant/keypad"

def load_config():
    global MQTT_BROKER, MQTT_PORT, MQTT_TOPIC
    if os.path.exists(CONFIG_PATH):
        config = ConfigParser()
        config.read(CONFIG_PATH)
        settings = config['DEFAULT']
        MQTT_BROKER = settings.get('mqtt_broker', MQTT_BROKER)
        MQTT_PORT = int(settings.get('mqtt_port', MQTT_PORT)) # Ensure port is integer
        MQTT_TOPIC = settings.get('mqtt_keypad_topic', MQTT_TOPIC) # Use keypad topic key
        print(f"Loaded config: Broker={MQTT_BROKER}, Port={MQTT_PORT}, Topic={MQTT_TOPIC}")
    else:
        print(f"Warning: {CONFIG_PATH} not found. Using default MQTT settings.")

load_config() # Load config on script start
# --- End Configuration Loading ---


CLIENT_ID = f"keypad_listener_{uuid.uuid4()}"
USE_SUDO = os.geteuid() != 0 # This check remains relevant for keyboard library

# --- Persistent MQTT Client ---
mqtt_client = mqtt.Client(client_id=CLIENT_ID)
is_mqtt_connected = False

def on_connect(client, userdata, flags, rc):
    global is_mqtt_connected
    if rc == 0:
        print("MQTT Client Connected.")
        is_mqtt_connected = True
    else:
        print(f"MQTT Connection Failed. Code: {rc}")
        is_mqtt_connected = False

def on_disconnect(client, userdata, rc):
    global is_mqtt_connected
    print("MQTT Client Disconnected.")
    is_mqtt_connected = False
    # Optional: Add reconnection logic here if desired

mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect

def connect_mqtt():
    global is_mqtt_connected
    if not is_mqtt_connected:
        try:
            print(f"Connecting to MQTT: {MQTT_BROKER}:{MQTT_PORT}")
            mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            mqtt_client.loop_start() # Start background thread for MQTT
        except Exception as e:
            print(f"Error connecting to MQTT: {e}")
            is_mqtt_connected = False

# --- End Persistent MQTT Client ---


def publish_message(topic, message):
  # client = mqtt.Client(client_id=CLIENT_ID) # No longer create client here
  # client.on_connect = on_connect # No longer needed here
  global is_mqtt_connected
  if not is_mqtt_connected:
      print("MQTT not connected. Attempting to reconnect...")
      connect_mqtt() # Try to connect if not connected
      time.sleep(1) # Give a moment to connect

  if is_mqtt_connected:
      try:
        # client.connect(MQTT_BROKER, MQTT_PORT, 60) # No longer connect here

        # Publish the message
        mqtt_client.publish(topic, payload=message, qos=0, retain=False)
        print(f"Published: Topic={topic}, Message={message}")
        # client.disconnect() # Do not disconnect here
      except Exception as e:
        print(f"Error publishing: {e}")
        is_mqtt_connected = False # Assume connection lost on error
  else:
      print("Failed to publish: MQTT not connected.")


def check_root_access():
  # Keep this check as the 'keyboard' library often needs root
  if os.geteuid() == 0:
    return True
  print("Warning: Script not running as root. Keyboard listening might fail.")
  # Optionally, attempt a keyboard operation to confirm, but a warning might suffice
  # try:
  #   keyboard.press('shift') # Example test
  #   keyboard.release('shift')
  #   return True
  # except Exception as e:
  #   print(f"Root permissions might be needed: {e}")
  #   return False
  return False # Assume failure if not root, rely on user running with sudo


# Define key mapping dictionary
KEY_MAP = {
    'enter': "capture",
    '4': "scroll_left",
    '6': "scroll_right",
    '8': "scroll_up",
    '2': "scroll_down",
    'insert': "copy",
    'delete': "clear",
    'home': "home",
    'end': "end",
    'page up': "page_up", # Note: keyboard library might use 'page up'
    'page down': "page_down" # Note: keyboard library might use 'page down'
}

def on_key_press(event):
  # Removed root check from here, rely on initial check or user running with sudo
  # if not check_root_access():
  #   print("Still no key press permissions")
  #   return

  # Use the key map
  if event.name in KEY_MAP:
      publish_message(MQTT_TOPIC, KEY_MAP[event.name])
  # else: # Optional: Log unmapped keys if needed
  #   print(f"Unmapped key pressed: {event.name}")


def start_keypad_listener():
  # Simplified logic - recommend running with sudo
  if not check_root_access():
      print("-----------------------------------------------------")
      print("WARNING: Not running as root.")
      print("Keyboard listening might fail without root privileges.")
      print("Please run this script using: sudo python KeyboardListener.py")
      print("-----------------------------------------------------")
      # Allow running without root, but keyboard hook might fail later
      # return # Uncomment this line to strictly enforce root

  connect_mqtt() # Initial MQTT connection attempt

  # Define keys based on the map keys for clarity
  keys_to_listen = list(KEY_MAP.keys())

  for key in keys_to_listen:
    # Use on_press_key for specific keys or on_press for broader handling
    # suppress=False allows key press to pass through to other applications if needed
    keyboard.on_press_key(key, on_key_press, suppress=False)

  print("Keypad listener started. Press keys on the numeric keypad.")
  print(f"Listening for keys: {', '.join(keys_to_listen)}")
  print(f"Publishing to MQTT topic: {MQTT_TOPIC} on {MQTT_BROKER}:{MQTT_PORT}")

  try:
      keyboard.wait() # Keep the script running
  except KeyboardInterrupt:
      print("\nStopping listener...")
  finally:
      if is_mqtt_connected:
          mqtt_client.loop_stop() # Stop the MQTT background thread
          mqtt_client.disconnect()
          print("MQTT client disconnected.")
      keyboard.unhook_all() # Clean up hooks
      print("Keyboard hooks removed.")


if __name__ == "__main__":
  start_keypad_listener()