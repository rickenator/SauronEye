#!/usr/bin/env python3

import evdev
from evdev import ecodes
import uinput
import paho.mqtt.client as mqtt
import time
import os
import uuid
from configparser import ConfigParser
import subprocess

CONFIG_PATH = "config.ini"
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "ai_assistant/keypad"

def ensure_uinput_loaded():
    if not os.path.exists("/dev/uinput"):
        print("uinput module not loaded. Attempting to load...")
        try:
            subprocess.run(["modprobe", "uinput"], check=True)
            print("uinput module loaded.")
        except Exception as e:
            print(f"Failed to load uinput module: {e}")
            raise SystemExit("Cannot continue without uinput.")

def load_config():
    global MQTT_BROKER, MQTT_PORT, MQTT_TOPIC
    if os.path.exists(CONFIG_PATH):
        config = ConfigParser()
        config.read(CONFIG_PATH)
        settings = config['DEFAULT']
        MQTT_BROKER = settings.get('mqtt_broker', MQTT_BROKER)
        MQTT_PORT = int(settings.get('mqtt_port', MQTT_PORT))
        MQTT_TOPIC = settings.get('mqtt_keypad_topic', MQTT_TOPIC)

load_config()

CLIENT_ID = f"keypad_listener_{uuid.uuid4()}"
mqtt_client = mqtt.Client(client_id=CLIENT_ID)
mqtt_connected = False

def on_connect(client, userdata, flags, rc):
    global mqtt_connected
    mqtt_connected = (rc == 0)
    print("MQTT connected" if mqtt_connected else f"MQTT failed with code {rc}")

def on_disconnect(client, userdata, rc):
    global mqtt_connected
    mqtt_connected = False
    print("MQTT disconnected")

mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect

def connect_mqtt():
    if not mqtt_connected:
        try:
            mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            mqtt_client.loop_start()
        except Exception as e:
            print(f"MQTT connect error: {e}")

def publish_message(topic, message):
    if not mqtt_connected:
        connect_mqtt()
        time.sleep(0.25)
    if mqtt_connected:
        mqtt_client.publish(topic, payload=message)
        print(f"Published: {message}")

# Only intercept these keypad keys
INTERCEPT = {
    ecodes.KEY_KPENTER: "capture",
    ecodes.KEY_KP4: "scroll_left",
    ecodes.KEY_KP6: "scroll_right",
    ecodes.KEY_KP8: "scroll_up",
    ecodes.KEY_KP2: "scroll_down",
    ecodes.KEY_INSERT: "insert",
    ecodes.KEY_DELETE: "clear",
    ecodes.KEY_HOME: "home",
    ecodes.KEY_END: "end",
    ecodes.KEY_PAGEUP: "page_up",
    ecodes.KEY_PAGEDOWN: "page_down"
}

def find_keyboard():
    # Choose a device with "keyboard" or "kbd" in its name.
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        if ecodes.EV_KEY in dev.capabilities():
            if "keyboard" in dev.name.lower() or "kbd" in dev.name.lower():
                print(f"Using input: {dev.path} ({dev.name})")
                return dev
    raise RuntimeError("No keyboard device found.")

def main():
    if os.geteuid() != 0:
        raise SystemExit("Must run as root.")

    ensure_uinput_loaded()
    connect_mqtt()
    src = find_keyboard()
    src.grab()

    # Setup passthrough devices
    keyboard_passthrough = []
    for code, name in ecodes.keys.items():
        if code in INTERCEPT:
            continue
        if isinstance(name, tuple):
            name = name[0]
        if name.startswith("BTN_"):
            continue
        keyboard_passthrough.append(code)

    keyboard_virtual = uinput.Device([(ecodes.EV_KEY, code) for code in keyboard_passthrough])
    mouse_virtual = uinput.Device([
        (ecodes.EV_KEY, ecodes.BTN_LEFT),
        (ecodes.EV_KEY, ecodes.BTN_RIGHT),
        (ecodes.EV_KEY, ecodes.BTN_MIDDLE),
        (ecodes.EV_REL, ecodes.REL_X),
        (ecodes.EV_REL, ecodes.REL_Y)
    ])

    print("Listening. Intercepting only defined keypad keys.")

    try:
        for event in src.read_loop():
            if event.type == ecodes.EV_REL:
                mouse_virtual.emit((event.type, event.code), event.value)
                continue

            if event.type != ecodes.EV_KEY:
                continue

            key_event = evdev.categorize(event)
            code = key_event.scancode

            if code in INTERCEPT:
                if key_event.keystate == key_event.key_down:
                    publish_message(MQTT_TOPIC, INTERCEPT[code])
                continue  # Block intercepted keys

            # Route normal events
            name = ecodes.keys.get(code, "")
            if isinstance(name, tuple):
                name = name[0]
            if isinstance(name, str) and name.startswith("BTN_"):
                mouse_virtual.emit((ecodes.EV_KEY, code), key_event.keystate)
            else:
                keyboard_virtual.emit((ecodes.EV_KEY, code), key_event.keystate)

    finally:
        print("Cleaning up input device grab and virtual devices.")
        try:
            src.ungrab()
            print("Ungrabbed physical input device.")
        except Exception as e:
            print(f"Failed to ungrab: {e}")

        try:
            del keyboard_virtual
            #keyboard_virtual.close()
        except Exception as e:
            print(f"Error closing keyboard virtual device: {e}")

        try:
            del mouse_virtual
            #mouse_virtual.close()
        except Exception as e:
            print(f"Error closing mouse virtual device: {e}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Stopped.")

