# Acoustic-Camera-DIY
In this repo our files for the acoustic camera project.

## Steps to test UDP reciver performance
 - download the repo 
 - open `./software/` folder on  **VScode**
 - install requirements using `pip install -r ./software/requiremnts.txt`
 - Ensure in `./software/temp_final/config.py` `UDP_IP = 0.0.0.0` UDP_PORT=5002 which matches the config in Firmware 
 - Run `./software/temp_final/main.py` & connect the STM32 to send data
 - read the pkt/s shown

 ```software/temp_final/config.py
 UDP_IP      = "0.0.0.0"   # should listen to all interfaces
 UDP_PORT    = 5002        # must match dest_port in firmware 
 ```
