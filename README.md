# Stress Monitor

Stress Monitor is a Python application that connects to a Bluetooth Low Energy (BLE) device to monitor and visualize stress levels in real time. The application computes stress using the formula: **Stress = 100 - Meditation**, based on data received from the device. It scans for nearby BLE devices, allows the user to select one, and then displays both continuous and interval-averaged stress values alongside signal quality indicators.

## Features

- **BLE Device Scanning & Selection:**  
  Automatically scans for nearby BLE devices and presents a list for the user to select the desired device.

- **Real-Time Visualization:**  
  Continuously plots stress values for the left and right channels over a moving window. Additionally, it calculates and displays averaged stress values in 10-second intervals using a grouped bar chart.

- **User Guidance:**  
  Provides a clear on-screen instruction:  
  **"Press the front left key of the device to turn on the device and look for mirolab mindease."**

- **Logging & Signal Quality Indicators:**  
  Displays connection status, logs events and errors, and shows signal quality for each channel.

## Requirements

- Python 3.7 or later (Python 3.9+ recommended)
- [PyQt5](https://pypi.org/project/PyQt5/)
- [qasync](https://pypi.org/project/qasync/)
- [bleak](https://pypi.org/project/bleak/)
- [matplotlib](https://pypi.org/project/matplotlib/)

## Installation

1. **Clone the repository:**

   ```bash
   git clone https://github.com/your-username/Stress-Monitor.git
   cd Stress-Monitor

## Install dependencies:

2.  **You can install all required packages using pip. If you have a requirements.txt file, run:**

    ```bash
    pip install -r requirements.txt

  **Or install the packages individually: **
  ```bash
      pip install PyQt5 qasync bleak matplotlib
  ```
## Usage
To run the Stress Monitor application, execute:

  ```bash
    python stress_monitor.py
```
Upon launch, the application will:

Scan for nearby BLE devices.

Present a dialog for selecting your desired device.

Display an instruction message:
"Press the front left key of the device to turn on the device and look for mirolab mindease."

Begin monitoring and visualizing stress values in real time.

## Contributing
Contributions, bug reports, and feature requests are welcome!
Feel free to open an issue or submit a pull request on GitHub.

## License
This project is licensed under the MIT License. See the LICENSE file for details.

## Contact
For further questions or suggestions, please contact mrnorz@gmail.com.








