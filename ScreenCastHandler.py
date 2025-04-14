import os
import uuid
import time
# --- Use Gio directly ---
from gi.repository import GLib, Gst, GObject, Gio
# --- Remove dasbus/pydbus imports ---
# from dasbus.connection import SessionMessageBus
# from dasbus.typing import Variant, Str, Dict, UInt32, Bool, List, ObjPath
# from dasbus.error import DBusError
from PyQt5.QtCore import QObject, pyqtSignal, QTimer
from PIL import Image
import traceback

# Initialize GStreamer
Gst.init(None)

# --- Portal Constants ---
PORTAL_BUS_NAME = "org.freedesktop.portal.Desktop"
PORTAL_OBJECT_PATH = "/org/freedesktop/portal/desktop"
PORTAL_IFACE_SCREENCAST = "org.freedesktop.portal.ScreenCast"
PORTAL_IFACE_REQUEST = "org.freedesktop.portal.Request"
PORTAL_IFACE_SESSION = "org.freedesktop.portal.Session"
# --- Remove dasbus XML Interface Definitions ---


class ScreenCastHandler(QObject):
    capture_successful = pyqtSignal(object) # Emits PIL Image
    capture_failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.portal_bus_name = PORTAL_BUS_NAME
        self.portal_proxy = None
        self.connection = None
        self.signal_subscription_id = 0 # Store Gio signal subscription ID

        try:
            # --- Get Gio DBus connection ---
            self.connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            if not self.connection:
                 raise Exception("Failed to get DBus session bus connection.")

            # --- Create main portal proxy using Gio ---
            # We'll use this proxy for ScreenCast method calls
            self.portal_proxy = Gio.DBusProxy.new_sync(
                self.connection,
                Gio.DBusProxyFlags.NONE,
                None,  # GDBusInterfaceInfo
                self.portal_bus_name,
                PORTAL_OBJECT_PATH,
                PORTAL_IFACE_SCREENCAST, # Interface for this proxy
                None   # GCancellable
            )
            if not self.portal_proxy:
                 raise Exception(f"Failed to create DBus proxy for {self.portal_bus_name} {PORTAL_OBJECT_PATH} [{PORTAL_IFACE_SCREENCAST}]")
            # ---

        except Exception as e:
            # Catch GLib.Error which might occur if service is unavailable
            print(f"FATAL: Could not connect/setup DBus proxy for portal service ({self.portal_bus_name}). Ensure xdg-desktop-portal is running.")
            print(f"Error: {e}")
            self.capture_failed.emit(f"Failed to connect to DBus portal service: {e}")
            # No 'return' here, allow object creation but it will be non-functional
            # Calls in start_capture will fail if self.portal_proxy is None

        self.request_token_counter = 0
        self.session_token_counter = 0
        self.session_handle_token = None
        self.request_handle_token = None
        self.session_object_path = None
        self.request_object_path = None
        self.pipewire_node_id = None
        self.pipeline = None
        self.appsink = None
        self.source = None

        print("ScreenCastHandler initialized (using Gio).")

    # --- Handle generation (remains the same) ---
    def _get_request_token(self):
        self.request_token_counter += 1
        return f"sauroneye_req_{os.getpid()}_{self.request_token_counter}"

    def _get_session_token(self):
        self.session_token_counter += 1
        return f"sauroneye_sess_{os.getpid()}_{self.session_token_counter}"

    # --- Start Capture Process ---
    def start_capture(self):
        """Initiates the screen capture process via the portal."""
        print("Starting screen capture process...") # DEBUG

        if not self.portal_proxy or not self.connection:
             err_msg = "DBus connection or portal proxy not initialized."
             print(f"ERROR: {err_msg}")
             self.capture_failed.emit(err_msg)
             return

        # --- Reset state variables (remains the same) ---
        self.session_handle_token = None
        self.request_handle_token = None
        self.session_object_path = None
        self.request_object_path = None
        self.pipewire_node_id = None
        if self.pipeline:
             print("Stopping lingering pipeline before new capture.")
             try:
                 self.pipeline.set_state(Gst.State.NULL)
             except Exception as gst_e:
                 print(f"Error stopping lingering pipeline: {gst_e}")
             self.pipeline = None
             self.appsink = None
        # --- Unsubscribe from any lingering signal ---
        self._unsubscribe_signal()
        # ---

        try:
            # 1. Create Session
            self.session_handle_token = self._get_session_token()
            print(f"Generated Session Token: {self.session_handle_token}") # DEBUG

            # --- Prepare options dictionary ---
            options = {
                'session_handle_token': GLib.Variant("s", self.session_handle_token)
                # 'handle_token': GLib.Variant("s", self.request_handle_token) # Still omitting handle_token
            }
            print(f"Calling CreateSession with minimal options: {options}") # DEBUG

            # --- Wrap arguments in GLib.Variant tuple for the call ---
            # CreateSession expects (a{sv})
            params = GLib.Variant("(a{sv})", (options,))
            # ---

            # --- Call method using Gio proxy ---
            # Returns a GLib.Variant tuple, e.g., (<handle>,)
            result_variant = self.portal_proxy.call_sync(
                "CreateSession",         # Method name
                params,                  # Arguments as GLib.Variant tuple
                Gio.DBusCallFlags.NONE,  # flags
                -1,                      # timeout_msec (-1 for default)
                None                     # cancellable
            )
            # ---

            # --- Extract object path from result ---
            # result_variant is a tuple variant, get the first element (which is the object path variant 'o')
            self.request_object_path = result_variant.unpack()[0] # unpack() gets python tuple, [0] gets the path string
            # ---
            print(f"CreateSession called via Gio. Request Object Path: {self.request_object_path}") # DEBUG

            # --- Subscribe to the Response signal using Gio.DBusConnection ---
            self.signal_subscription_id = self.connection.signal_subscribe(
                self.portal_bus_name,      # sender_name (service we are calling)
                PORTAL_IFACE_REQUEST,      # interface_name
                "Response",                # member (signal name)
                self.request_object_path,  # object_path we expect signal from
                None,                      # arg0 (match specific first arg value, None for any)
                Gio.DBusSignalFlags.NONE,  # flags
                self._on_portal_response_gio, # callback function
                None                       # user_data
            )
            if self.signal_subscription_id == 0:
                 raise Exception("Failed to subscribe to portal Response signal.")
            # ---
            print(f"Subscribed to Response signal on {self.request_object_path} (ID: {self.signal_subscription_id})") # DEBUG
            # Now wait for the response signal...

        except GLib.Error as e: # Catch Gio/GLib errors
            error_message = f"Portal CreateSession failed: {e.message} (Domain: {e.domain}, Code: {e.code})"
            print(f"ERROR: {error_message}") # DEBUG
            self.capture_failed.emit(error_message)
            self.cleanup() # Attempt cleanup
        except Exception as e:
            error_message = f"An unexpected error occurred during CreateSession call: {e}"
            print(f"ERROR: {error_message}") # DEBUG
            traceback.print_exc()
            self.capture_failed.emit(error_message)
            self.cleanup()

    # --- Gio Signal Callback ---
    def _on_portal_response_gio(self, connection, sender_name, object_path, interface_name, signal_name, parameters, user_data):
        """Callback for the portal's Response signal connected via Gio."""
        print(f"Gio Signal: sender='{sender_name}', object='{object_path}', iface='{interface_name}', signal='{signal_name}'") # DEBUG

        # Check if it's the signal we are waiting for (redundant due to subscription filter, but safe)
        if object_path != self.request_object_path or signal_name != "Response":
            print("Ignoring unexpected signal.")
            return

        # --- Unsubscribe signal handler ---
        # We do this first, before processing, to avoid potential race conditions if processing triggers another signal somehow
        current_sub_id = self.signal_subscription_id
        self.signal_subscription_id = 0 # Mark as unsubscribed immediately
        self._unsubscribe_signal(current_sub_id) # Pass ID to ensure we unsubscribe the correct one
        # ---

        # --- Extract response code and results ---
        try:
            response_code = parameters.unpack()[0]
            results_variant = parameters.unpack()[1]

            # --- Revised Unpacking Logic ---
            results = {}
            # Iterate through the dictionary provided by the results_variant
            for key, value in results_variant.items():
                # Check if the value is still a GLib.Variant
                if isinstance(value, GLib.Variant):
                    # If it is, unpack it to get the Python type
                    results[key] = value.unpack()
                else:
                    # Otherwise, assume it's already the correct Python type
                    results[key] = value
            # --- End Revised Unpacking Logic ---

        except Exception as e:
             print(f"ERROR: Failed to unpack portal response parameters: {e}")
             traceback.print_exc() # Add traceback for detail
             self.capture_failed.emit("Failed to parse portal response.")
             self.cleanup()
             return

        print(f"Portal Response received for object: {object_path}") # DEBUG
        print(f"  Response Code: {response_code}") # DEBUG
        print(f"  Results: {results}") # DEBUG

        # Handle failed response
        if response_code != 0:
            err_msg = f"Portal request failed for {object_path} (code {response_code})"
            print(err_msg) # DEBUG
            self.capture_failed.emit(err_msg)
            self.cleanup()
            return

        # --- Handle successful responses ---
        try:
            if 'session_handle' in results: # Response from CreateSession
                print("CreateSession successful.") # DEBUG
                self.session_object_path = results['session_handle'] # Should be string object path
                print(f"Using Portal-provided Session Object Path: {self.session_object_path}") # DEBUG

                # 2. Select Sources - Use Gio call_sync
                print("Calling SelectSources...") # DEBUG
                self.request_handle_token = self._get_request_token()
                select_options = {
                    "multiple": GLib.Variant('b', False),
                    "types": GLib.Variant('u', 1),
                    "handle_token": GLib.Variant('s', self.request_handle_token)
                }
                # SelectSources expects (o, a{sv})
                params = GLib.Variant("(oa{sv})", (self.session_object_path, select_options))
                select_result = self.portal_proxy.call_sync("SelectSources", params, Gio.DBusCallFlags.NONE, -1, None)
                self.request_object_path = select_result.unpack()[0]
                print(f"SelectSources called via Gio. New Request Object Path: {self.request_object_path}") # DEBUG

                # Re-subscribe signal handler to the new request object
                self.signal_subscription_id = self.connection.signal_subscribe(
                    self.portal_bus_name, PORTAL_IFACE_REQUEST, "Response",
                    self.request_object_path, None, Gio.DBusSignalFlags.NONE,
                    self._on_portal_response_gio, None
                )
                if self.signal_subscription_id == 0: raise Exception("Failed to re-subscribe to portal Response signal.")
                print(f"Re-subscribed to Response signal on {self.request_object_path} (ID: {self.signal_subscription_id})") # DEBUG
                print("Waiting for user interaction (SelectSources)...") # DEBUG

            elif 'streams' in results: # Response from Start
                print("Start successful. Received streams.") # DEBUG
                streams = results.get('streams', []) # Should be list of tuples [(uint32, dict), ...]
                if not streams:
                    print("Error: No streams found in portal response.") # DEBUG
                    self.capture_failed.emit("No streams provided by portal.")
                    self.cleanup()
                    return

                # --- Correctly access the stream tuple ---
                stream_tuple = streams[0] # Get the first stream tuple (uint32, dict)
                self.pipewire_node_id = stream_tuple[0] # First element is the Node ID
                stream_props = stream_tuple[1] # Second element is the properties dictionary
                # ---

                # Optional: Check if node ID is valid (should be uint32)
                if not isinstance(self.pipewire_node_id, int): # Or check specific GLib/GObject type if needed
                     print(f"Error: Invalid PipeWire node ID type received: {type(self.pipewire_node_id)}")
                     self.capture_failed.emit("Invalid PipeWire node ID received.")
                     self.cleanup()
                     return

                print(f"PipeWire Node ID: {self.pipewire_node_id}") # DEBUG
                # You can optionally print properties from stream_props if needed
                # print(f"Stream Properties: {stream_props}")

                # 4. Setup GStreamer pipeline
                self._setup_and_run_gstreamer()

            else: # Potentially response from SelectSources (user interaction done)
                print("SelectSources successful (user interaction likely complete).") # DEBUG
                # 3. Call Start - Use Gio call_sync
                print("Calling Start...") # DEBUG
                self.request_handle_token = self._get_request_token()
                start_options = {
                    "handle_token": GLib.Variant('s', self.request_handle_token)
                }
                # Start expects (o, s, a{sv})
                params = GLib.Variant("(osa{sv})", (self.session_object_path, "", start_options))
                start_result = self.portal_proxy.call_sync("Start", params, Gio.DBusCallFlags.NONE, -1, None)
                self.request_object_path = start_result.unpack()[0]
                print(f"Start called via Gio. New Request Object Path: {self.request_object_path}") # DEBUG

                # Re-subscribe signal handler to the new request object
                self.signal_subscription_id = self.connection.signal_subscribe(
                    self.portal_bus_name, PORTAL_IFACE_REQUEST, "Response",
                    self.request_object_path, None, Gio.DBusSignalFlags.NONE,
                    self._on_portal_response_gio, None
                )
                if self.signal_subscription_id == 0: raise Exception("Failed to re-subscribe to portal Response signal.")
                print(f"Re-subscribed to Response signal on {self.request_object_path} (ID: {self.signal_subscription_id})") # DEBUG
                print("Waiting for Start response...") # DEBUG

        except GLib.Error as e: # Catch Gio/GLib errors
            error_message = f"Portal interaction failed during response handling: {e.message} (Domain: {e.domain}, Code: {e.code})"
            print(f"ERROR: {error_message}") # DEBUG
            self.capture_failed.emit(error_message)
            self.cleanup()
        except Exception as e:
            error_message = f"An unexpected error occurred during portal response handling: {e}"
            print(f"ERROR: {error_message}") # DEBUG
            traceback.print_exc()
            self.capture_failed.emit(error_message)
            self.cleanup()

    # --- Helper to unsubscribe ---
    def _unsubscribe_signal(self, sub_id=None):
        """Unsubscribes from the portal signal using the stored ID."""
        _id = sub_id if sub_id is not None else self.signal_subscription_id
        if self.connection and _id > 0:
            print(f"Unsubscribing from signal subscription ID: {_id}") # DEBUG
            try:
                self.connection.signal_unsubscribe(_id)
            except Exception as e:
                 print(f"Warning: Error unsubscribing from signal ID {_id}: {e}")
            # Reset stored ID if we unsubscribed the main one
            if sub_id is None:
                self.signal_subscription_id = 0


    # --- GStreamer Pipeline Setup and Handling (remains the same) ---
    def _setup_and_run_gstreamer(self):
        print("Setting up GStreamer pipeline...") # DEBUG
        if not self.pipewire_node_id:
            self.capture_failed.emit("Missing PipeWire Node ID.")
            self.cleanup()
            return
        try:
            pipeline_str = (
                f"pipewiresrc path={self.pipewire_node_id} ! "
                "videoconvert ! "
                "video/x-raw,format=RGB ! "
                "appsink name=sink emit-signals=true max-buffers=1 drop=true"
            )
            print(f"Pipeline: {pipeline_str}") # DEBUG
            self.pipeline = Gst.parse_launch(pipeline_str)
            self.appsink = self.pipeline.get_by_name("sink")
            if not self.appsink:
                 raise RuntimeError("Failed to get appsink element from pipeline.")
            self.appsink.connect("new-sample", self._on_new_sample)
            bus = self.pipeline.get_bus()
            bus.add_signal_watch()
            bus.connect("message::error", self._on_gst_error)
            bus.connect("message::eos", self._on_gst_eos)
            print("Starting GStreamer pipeline...") # DEBUG
            ret = self.pipeline.set_state(Gst.State.PLAYING)
            if ret == Gst.StateChangeReturn.FAILURE:
                print("Error: Unable to set the pipeline to the playing state.") # DEBUG
                self.capture_failed.emit("Failed to start GStreamer pipeline.")
                self.cleanup()
            elif ret == Gst.StateChangeReturn.ASYNC:
                 print("Pipeline state change is ASYNC.") # DEBUG
            else:
                 print("Pipeline state change successful (SYNC).") # DEBUG
        except Exception as e:
            print(f"Error setting up GStreamer: {e}") # DEBUG
            traceback.print_exc()
            self.capture_failed.emit(f"GStreamer setup error: {e}")
            self.cleanup()

    # --- _on_new_sample, _on_gst_error, _on_gst_eos (remain the same) ---
    def _on_new_sample(self, appsink_param): # Rename param to avoid confusion with self.appsink
        """Callback for the 'new-sample' signal from appsink."""
        # --- Debug Prints ---
        print(f"DEBUG: _on_new_sample called with type: {type(appsink_param)}")
        # print(f"DEBUG: dir(appsink_param): {dir(appsink_param)}") # Can comment this out now
        # ---

        # Ensure we are calling the method on the object passed by the signal
        try:
            # --- Workaround: Emit the 'pull-sample' action signal ---
            print("DEBUG: Attempting to emit 'pull-sample' signal...")
            sample = appsink_param.emit("pull-sample")
            # ---
        except Exception as e: # Catch broader exceptions as emit might raise different errors
             print(f"FATAL: Failed to emit 'pull-sample' on {type(appsink_param)}: {e}")
             traceback.print_exc()
             if self.pipeline:
                 self.pipeline.set_state(Gst.State.NULL)
             self.cleanup()
             return Gst.FlowReturn.ERROR # Indicate an error downstream

        # --- Sample processing logic remains the same ---
        if sample:
            try:
                # Check if the returned object is actually a Gst.Sample
                if not isinstance(sample, Gst.Sample):
                    print(f"ERROR: Emit 'pull-sample' returned unexpected type: {type(sample)}")
                    self.capture_failed.emit("Failed to retrieve valid sample via emit.")
                    self.cleanup()
                    return Gst.FlowReturn.ERROR

                buffer = sample.get_buffer()
                caps = sample.get_caps()
                structure = caps.get_structure(0)
                width = structure.get_value("width")
                height = structure.get_value("height")
                success, map_info = buffer.map(Gst.MapFlags.READ)
                if not success: raise RuntimeError("Could not map GStreamer buffer")
                expected_size = width * height * 3
                if map_info.size < expected_size:
                    print(f"Warning: Buffer size ({map_info.size}) < expected ({expected_size}).")
                    buffer.unmap(map_info)
                    self.capture_failed.emit("Received incomplete frame buffer.")
                    self.cleanup(); return Gst.FlowReturn.ERROR
                image = Image.frombytes("RGB", (width, height), map_info.data[:expected_size])
                buffer.unmap(map_info)
                print(f"Frame captured successfully ({width}x{height}).") # DEBUG
                self.capture_successful.emit(image.copy())
            except Exception as e:
                print(f"Error processing GStreamer sample: {e}") # DEBUG
                traceback.print_exc()
                self.capture_failed.emit(f"Failed to process frame: {e}")
            finally:
                print("Stopping pipeline after capturing frame.") # DEBUG
                if self.pipeline: self.pipeline.set_state(Gst.State.NULL)
                self.cleanup(); return Gst.FlowReturn.EOS # Use EOS to signal we are done
        else:
             print("Could not pull sample from appsink (EOS or error likely).") # DEBUG
             # If pull_sample returns None, it often means EOS or an issue upstream
             if self.pipeline: print("Pull sample failed, ensuring cleanup."); self.cleanup()
             # Return OK here as None from pull_sample isn't necessarily a fatal error for the callback itself
             return Gst.FlowReturn.OK

        # Should not be reached if sample is processed, but needed for consistent return
        # Return OK if we pulled a sample but didn't hit the finally block (shouldn't happen here)
        return Gst.FlowReturn.OK

    def _on_gst_error(self, bus, message):
        err, debug = message.parse_error()
        print(f"GStreamer Error: {err}, {debug}") # DEBUG
        self.capture_failed.emit(f"GStreamer error: {err}")
        self.cleanup()

    def _on_gst_eos(self, bus, message):
        print("GStreamer: End of stream reached.") # DEBUG
        if self.pipeline: print("EOS reached, ensuring cleanup."); self.cleanup()


    # --- Cleanup Method (Updated for Gio) ---
    def cleanup(self):
        """Cleans up GStreamer pipeline and portal session."""
        print("Cleaning up ScreenCastHandler resources...") # DEBUG

        # --- Unsubscribe signal handler ---
        self._unsubscribe_signal()

        # --- Stop GStreamer pipeline (remains the same) ---
        if hasattr(self, 'pipeline') and self.pipeline:
            print("Setting pipeline state to NULL.") # DEBUG
            try:
                self.pipeline.set_state(Gst.State.NULL)
            except Exception as gst_e:
                 print(f"Error setting GStreamer state to NULL during cleanup: {gst_e}")
            finally:
                 self.pipeline = None
                 self.appsink = None

        # --- Close Portal Session using Gio ---
        if hasattr(self, 'session_object_path') and self.session_object_path:
            current_session_path = self.session_object_path
            self.session_object_path = None # Clear path
            print(f"Closing portal session: {current_session_path}") # DEBUG
            if not self.connection:
                 print("Warning: No DBus connection available to close session.")
            else:
                try:
                    # Create a temporary proxy for the session object
                    session_proxy = Gio.DBusProxy.new_sync(
                        self.connection, Gio.DBusProxyFlags.NONE, None,
                        self.portal_bus_name, current_session_path, PORTAL_IFACE_SESSION, None
                    )
                    if session_proxy:
                        # Close takes no arguments (pass None) and returns nothing
                        session_proxy.call_sync("Close", None, Gio.DBusCallFlags.NONE, -1, None)
                        print("Portal session Close called via Gio.") # DEBUG
                    else:
                        print(f"Warning: Failed to create proxy for session {current_session_path} to close it.")
                except GLib.Error as e: # Catch Gio/GLib errors
                     # Handle specific errors, e.g., session already closed or object path invalid
                     print(f"GLib Error closing portal session {current_session_path}: {e.message}")
                except Exception as e:
                    print(f"Unexpected Error closing portal session {current_session_path}: {e}")
                    traceback.print_exc()
        else:
            print("No active portal session object path to close.") # DEBUG

        # --- Reset state variables (remains the same) ---
        self.session_handle_token = None
        self.request_handle_token = None
        self.request_object_path = None
        self.pipewire_node_id = None

        print("ScreenCastHandler Cleanup complete.") # DEBUG

    # __del__ remains the same
    def __del__(self):
        print(f"__del__ called for ScreenCastHandler {id(self)}") # DEBUG
        # Ensure connection resources are potentially released if the object is GC'd
        # Although explicit cleanup is better.
        self.connection = None
        self.portal_proxy = None
        # self.cleanup() # Avoid calling complex cleanup here