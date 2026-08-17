Placed all files in SD card
---------------------------
/SD card
│
├── adjustraypolygon.py
├── adjustrayrect.py
├── main.py
├── lbp_db.mpy
├── hog_db.mpy
└── hog_lbp_db.mpy

Hardware Requirements Prerequisite
---------------------------------

- OpenMV H7 Plus Camera

- OpenMV IDE

- Stable lighting environment

- Chilli placement tray

- External hardware connected to GPIO outputs

PROCEDURE
---------

1. Connect the OpenMV camera to the OpenMV IDE.

2. Open calibration script:

	i. adjustraypolygon.py

	ii. adjustrayrect.py

   Note 1: Run both the scripts, adjustrayrect.py and adjustraypolygon.py, one after another)

   Adjust coordinates until the overlay matches the tray edges.

   Copy the final coordinates into main.py

   Calibration must be performed after the camera mounting position is finalized. Also please adjust the distance of 13 cm (130 mm)from Tray to camera lens

3. Run the script main.py 
Note: To start the test, keep the tray empty for 1 or 2 seconds to train the empty tray

4. GPIO Output Mapping
	P0 → POD LEFT Signal
	P1 → POD RIGHT Signal

