#!/usr/bin/env python3
"""
Stress Monitor

This application connects to a BLE device that provides EEG data.
It processes incoming BLE packets to compute stress values 
(from the meditation reading as: 100 - meditation).
The stress values are plotted continuously (with a moving window)
and also summarized in 10-second intervals.

Features:
  - Scans for nearby BLE devices and allows the user to select one.
  - Displays an instruction: "Press the front left key of the device to turn on the device and look for mirolab mindease."
  - Plots continuous stress values for left and right channels.
  - Computes interval (denoised) stress values and displays a summary bar chart.
  - Logs connection events and errors.
  
Author: Your Name
Date: 2025-03-25
"""

import sys
import asyncio
import threading
import logging
from collections import deque

from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QLabel,
    QPushButton,
    QStatusBar,
    QDialog,
    QListWidget,
    QMessageBox,
)
from PyQt5.QtCore import QTimer, Qt, QThread, pyqtSignal, pyqtSlot

from qasync import QEventLoop

import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

from bleak import BleakClient, BleakScanner

# Configure logging
logging.basicConfig(level=logging.INFO)
logging.getLogger("matplotlib").setLevel(logging.WARNING)
logging.getLogger("bleak").setLevel(logging.WARNING)

# Characteristic UUIDs (fixed)
CHARACTERISTIC_UUID_1 = "6e400003-b5b0-f393-e0a9-e50e24dcca9f"
CHARACTERISTIC_UUID_2 = "6e400003-b5b1-f393-e0a9-e50e24dcca9f"
PACKET_SIZE = 36

def denoise_signal(values):
    if not values:
        return None
    return sum(values) / len(values)

def categorize_stress_5(value):
    if value is None:
        return "No Data"
    if value < 20:
        return "Very Low"
    elif value < 40:
        return "Low"
    elif value < 60:
        return "Moderate"
    elif value < 80:
        return "High"
    else:
        return "Very High"

# -----------------------------------------------------------------------------
# Device Selection Dialog
# -----------------------------------------------------------------------------
class DeviceSelectionDialog(QDialog):
    def __init__(self, devices, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select BLE Device")
        self.devices = devices
        self.selected_device = None
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        label = QLabel("Select a BLE device:")
        layout.addWidget(label)
        self.list_widget = QListWidget(self)
        for device in self.devices:
            name = device.name if device.name else "Unknown"
            item_text = f"{name} ({device.address})"
            self.list_widget.addItem(item_text)
        layout.addWidget(self.list_widget)
        button_layout = QHBoxLayout()
        ok_button = QPushButton("OK")
        ok_button.clicked.connect(self.accept_selection)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
    
    def accept_selection(self):
        current_row = self.list_widget.currentRow()
        if current_row >= 0:
            self.selected_device = self.devices[current_row]
            self.accept()
        else:
            QMessageBox.warning(self, "No Selection", "Please select a device.")

# -----------------------------------------------------------------------------
# BLEWorker – Handles BLE connection and notifications
# -----------------------------------------------------------------------------
class BLEWorker(QThread):
    data_received = pyqtSignal(str, float, float, int)
    connection_status = pyqtSignal(bool)
    log_message = pyqtSignal(str)

    def __init__(self, device_address, parent=None):
        super().__init__(parent)
        self.device_address = device_address
        self._stop_event = threading.Event()
        self.buffer_left = bytearray()
        self.buffer_right = bytearray()

    def run(self):
        asyncio.run(self.ble_loop())

    async def ble_loop(self):
        uuids = [CHARACTERISTIC_UUID_1, CHARACTERISTIC_UUID_2]
        while not self._stop_event.is_set():
            try:
                client = BleakClient(self.device_address)
                await client.connect()
                self.log_message.emit(f"Connected to {self.device_address}")
                self.connection_status.emit(True)
                for uuid in uuids:
                    channel = "left" if uuid == CHARACTERISTIC_UUID_1 else "right"
                    await client.start_notify(
                        uuid,
                        lambda sender, data, ch=channel: asyncio.create_task(
                            self.notification_handler(sender, data, ch)
                        ),
                    )
                    self.log_message.emit(f"Subscribed to {uuid} ({channel} channel)")
                while not self._stop_event.is_set():
                    await asyncio.sleep(1)
                for uuid in uuids:
                    await client.stop_notify(uuid)
                await client.disconnect()
                self.log_message.emit(f"Disconnected from {self.device_address}")
                self.connection_status.emit(False)
            except Exception as e:
                self.log_message.emit(f"Connection error: {e}")
                self.connection_status.emit(False)
                await asyncio.sleep(5)

    async def notification_handler(self, sender, data, channel):
        buffer = self.buffer_left if channel == "left" else self.buffer_right
        buffer += data
        while b"\xAA\xAA\x20" in buffer:
            start_index = buffer.find(b"\xAA\xAA\x20")
            if len(buffer) >= start_index + PACKET_SIZE:
                packet = buffer[start_index : start_index + PACKET_SIZE]
                self.process_long_packet(packet, channel)
                buffer = buffer[start_index + PACKET_SIZE :]
            else:
                break
        if channel == "left":
            self.buffer_left = buffer
        else:
            self.buffer_right = buffer

    def process_long_packet(self, packet, channel):
        try:
            hex_values = [f"{byte:02X}" for byte in packet]
            meditation_hex = hex_values[32]
            attention_hex = hex_values[34]
            signal_quality_hex = hex_values[4]
            meditation_int = int(meditation_hex, 16)
            attention_int = int(attention_hex, 16)
            signal_quality_int = int(signal_quality_hex, 16)
            stress_int = 100 - meditation_int
        except Exception as e:
            self.log_message.emit(f"Error processing packet: {e}")
            return
        self.data_received.emit(channel, float(stress_int), float(attention_int), signal_quality_int)

    def stop(self):
        self._stop_event.set()

# -----------------------------------------------------------------------------
# Main Application Window – Stress Monitor
# -----------------------------------------------------------------------------
class MyApp(QMainWindow):
    def __init__(self, device_address):
        super().__init__()
        self.device_address = device_address
        self.init_data_buffers()
        self.initUI()
        self.ble_worker = BLEWorker(self.device_address)
        self.connect_ble_worker()

    def init_data_buffers(self):
        self.stress_values_left = deque(maxlen=15)
        self.stress_values_right = deque(maxlen=15)
        self.interval_stress_buffer_left = []
        self.interval_stress_buffer_right = []
        self.interval_stress_left = deque(maxlen=5)
        self.interval_stress_right = deque(maxlen=5)

    def initUI(self):
        self.setWindowTitle("Stress Monitor")
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.setup_monitor_page()

    def connect_ble_worker(self):
        self.ble_worker.data_received.connect(self.handle_new_data)
        self.ble_worker.connection_status.connect(self.handle_connection_status)
        self.ble_worker.log_message.connect(self.append_text)
        self.ble_worker.start()

    def setup_monitor_page(self):
        self.clear_layout(self.main_layout)
        self.add_title_bar("Stress Monitor")
        self.fig, self.axs = plt.subplots(2, 1, figsize=(12, 8))
        self.ax1, self.ax2 = self.axs
        self.canvas = FigureCanvas(self.fig)
        self.main_layout.addWidget(self.canvas)
        self.text_edit = QTextEdit(self)
        self.text_edit.setReadOnly(True)
        self.text_edit.setStyleSheet("font-size: 14px; background-color: #f0f0f0; margin: 10px;")
        self.main_layout.addWidget(self.text_edit)
        self.signal_quality_label_left = self.setup_signal_label("Left")
        self.signal_quality_label_right = self.setup_signal_label("Right")
        reconnect_button = QPushButton("Reconnect")
        reconnect_button.setStyleSheet("font-size: 18px; margin: 10px;")
        reconnect_button.clicked.connect(self.restart_ble_worker)
        self.main_layout.addWidget(reconnect_button)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_continuous_plot)
        self.timer.start(1000)
        self.interval_timer = QTimer()
        self.interval_timer.timeout.connect(self.update_interval)
        self.interval_timer.start(10000)

    def add_title_bar(self, title):
        title_bar = QHBoxLayout()
        back_button = QPushButton("Back")
        back_button.setStyleSheet("font-size: 18px; margin: 10px;")
        back_button.clicked.connect(self.close)
        title_bar.addWidget(back_button)
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 24px; font-weight: bold; margin: 10px;")
        title_bar.addWidget(title_label)
        title_bar.addStretch(1)
        close_button = QPushButton("X")
        close_button.setStyleSheet("font-size: 18px; margin: 10px; background-color: red; color: white;")
        close_button.clicked.connect(self.close)
        title_bar.addWidget(close_button)
        self.main_layout.addLayout(title_bar)

    def setup_signal_label(self, side):
        label = QLabel(self)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-size: 18px; color: black; margin: 10px;")
        label.setText(f"{side} Signal Quality: Unknown")
        self.main_layout.addWidget(label)
        return label

    @pyqtSlot()
    def update_continuous_plot(self):
        self.ax1.clear()
        if self.stress_values_left:
            self.ax1.plot(list(self.stress_values_left), label="Left Stress", color="blue")
        if self.stress_values_right:
            self.ax1.plot(list(self.stress_values_right), label="Right Stress", color="red")
        self.ax1.axhline(20, color="gray", linestyle="--")
        self.ax1.axhline(40, color="gray", linestyle="--")
        self.ax1.axhline(60, color="gray", linestyle="--")
        self.ax1.axhline(80, color="gray", linestyle="--")
        self.ax1.set_xlabel("Time (s)")
        self.ax1.set_ylabel("Stress")
        self.ax1.set_title("Continuous Stress Values")
        self.ax1.legend()
        self.ax1.set_ylim([0, 100])
        self.canvas.draw()

    @pyqtSlot()
    def update_interval(self):
        if self.interval_stress_buffer_left:
            avg_left = sum(self.interval_stress_buffer_left) / len(self.interval_stress_buffer_left)
            self.interval_stress_left.append(avg_left)
            self.interval_stress_buffer_left.clear()
        if self.interval_stress_buffer_right:
            avg_right = sum(self.interval_stress_buffer_right) / len(self.interval_stress_buffer_right)
            self.interval_stress_right.append(avg_right)
            self.interval_stress_buffer_right.clear()
        self.update_interval_plot()
        self.update_interval_summary()

    def update_interval_plot(self):
        self.ax2.clear()
        intervals = list(range(1, 6))
        left_values = list(self.interval_stress_left)
        right_values = list(self.interval_stress_right)
        while len(left_values) < 5:
            left_values.insert(0, 0)
        while len(right_values) < 5:
            right_values.insert(0, 0)
        bar_width = 0.35
        x = range(5)
        bars_left = self.ax2.bar([i - bar_width/2 for i in x], left_values, width=bar_width, color="blue", label="Left")
        bars_right = self.ax2.bar([i + bar_width/2 for i in x], right_values, width=bar_width, color="red", label="Right")
        for bar in bars_left:
            height = bar.get_height()
            self.ax2.text(bar.get_x() + bar.get_width()/2.0, height + 2, categorize_stress_5(height),
                          ha="center", va="bottom", fontsize=10, color="blue")
        for bar in bars_right:
            height = bar.get_height()
            self.ax2.text(bar.get_x() + bar.get_width()/2.0, height + 2, categorize_stress_5(height),
                          ha="center", va="bottom", fontsize=10, color="red")
        self.ax2.set_xlabel("10-second Intervals")
        self.ax2.set_ylabel("Averaged Stress")
        self.ax2.set_title("Stress over Last 5 Intervals")
        self.ax2.set_xticks(x)
        self.ax2.set_xticklabels([f"Int {i+1}" for i in x])
        self.ax2.legend()
        self.ax2.set_ylim([0, 100])
        self.canvas.draw()

    def update_interval_summary(self):
        if self.interval_stress_left and self.interval_stress_right:
            left_latest = self.interval_stress_left[-1]
            right_latest = self.interval_stress_right[-1]
            summary_text = (
                f"Latest Interval Stress:\n"
                f"  Left: {left_latest:.2f} ({categorize_stress_5(left_latest)})\n"
                f"  Right: {right_latest:.2f} ({categorize_stress_5(right_latest)})\n"
            )
            self.text_edit.append(summary_text)

    @pyqtSlot(str, float, float, int)
    def handle_new_data(self, channel, stress, attention, signal_quality):
        if channel == "left":
            self.update_signal_quality(self.signal_quality_label_left, signal_quality, "Left")
            if signal_quality == 0:
                self.stress_values_left.append(stress)
                self.interval_stress_buffer_left.append(stress)
        else:
            self.update_signal_quality(self.signal_quality_label_right, signal_quality, "Right")
            if signal_quality == 0:
                self.stress_values_right.append(stress)
                self.interval_stress_buffer_right.append(stress)

    def update_signal_quality(self, label, quality, side):
        if quality == 0:
            label.setText(f"{side} Signal Quality: Good")
            label.setStyleSheet("font-size: 18px; color: green; margin: 10px;")
        elif 1 <= quality <= 50:
            label.setText(f"{side} Signal Quality: Poor ({quality})")
            label.setStyleSheet("font-size: 18px; color: orange; margin: 10px;")
        else:
            label.setText(f"{side} Signal Quality: Very Poor ({quality})")
            label.setStyleSheet("font-size: 18px; color: red; margin: 10px;")

    @pyqtSlot(bool)
    def handle_connection_status(self, connected):
        if connected:
            self.status_bar.showMessage("Connected to device")
        else:
            self.status_bar.showMessage("Disconnected from device")

    @pyqtSlot(str)
    def append_text(self, text):
        self.text_edit.append(text)

    def restart_ble_worker(self):
        self.ble_worker.stop()
        self.ble_worker.wait(2000)
        self.ble_worker = BLEWorker(self.device_address)
        self.connect_ble_worker()

    def clear_layout(self, layout):
        if layout is not None:
            while layout.count():
                child = layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
                elif child.layout():
                    self.clear_layout(child.layout())

    def closeEvent(self, event):
        self.ble_worker.stop()
        self.ble_worker.wait(2000)
        super().closeEvent(event)

# -----------------------------------------------------------------------------
# Main Entry Point
# -----------------------------------------------------------------------------
def main():
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    global main_window  # Global reference to keep the main window alive

    async def run_app():
        try:
            devices = await BleakScanner.discover()
        except Exception as e:
            QMessageBox.critical(None, "Error", f"Error scanning for BLE devices: {e}")
            sys.exit(1)
        if not devices:
            QMessageBox.information(None, "No Devices Found", "No BLE devices found. Exiting.")
            sys.exit(0)
        selection_dialog = DeviceSelectionDialog(devices)
        if selection_dialog.exec_() == QDialog.Accepted:
            selected_device = selection_dialog.selected_device
            device_address = selected_device.address
        else:
            sys.exit(0)
        QMessageBox.information(None, "Instructions",
            "Press the front left key of the device to turn on the device and look for mirolab mindease.")
        global main_window
        main_window = MyApp(device_address)
        main_window.show()

    with loop:
        loop.run_until_complete(run_app())
        loop.run_forever()

if __name__ == "__main__":
    main()
